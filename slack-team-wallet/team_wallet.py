#!/usr/bin/env python3
"""
NEAR Team Wallet — Slack Bot

Multi-sig style team treasury management for NEAR Protocol.
Slash commands for balance checks, transfer requests with approval flows,
transaction history, and staking overview.

Requires: slack_bolt, aiohttp, requests
Environment: SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, NEAR_ACCOUNT_ID, NEAR_RPC_URL
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# ─── Logging ──────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("team_wallet")

# ─── Config ───────────────────────────────────────────────────────

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "")  # for socket mode
NEAR_ACCOUNT_ID = os.environ.get("NEAR_ACCOUNT_ID", "")
NEAR_RPC_URL = os.environ.get("NEAR_RPC_URL", "https://rpc.mainnet.near.org")
REQUIRED_APPROVALS = int(os.environ.get("REQUIRED_APPROVALS", "2"))
APPROVER_SLACK_IDS = set(
    filter(None, os.environ.get("APPROVER_SLACK_IDS", "").split(","))
)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
PENDING_TX_FILE = DATA_DIR / "pending_transfers.json"
TX_HISTORY_FILE = DATA_DIR / "tx_history.json"

app = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)

# ─── Persistence ──────────────────────────────────────────────────


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def _save_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2))


def _load_pending() -> dict:
    return _load_json(PENDING_TX_FILE)


def _save_pending(data: dict):
    _save_json(PENDING_TX_FILE, data)


def _load_history() -> list:
    raw = _load_json(TX_HISTORY_FILE)
    return raw.get("transactions", [])


def _save_history(txns: list):
    _save_json(TX_HISTORY_FILE, {"transactions": txns})


# ─── NEAR RPC Helpers ─────────────────────────────────────────────


def _rpc_call(method: str, params: dict) -> dict | None:
    """Make a JSON-RPC call to the NEAR node."""
    payload = {"jsonrpc": "2.0", "id": "teamwallet", "method": method, "params": params}
    try:
        resp = requests.post(
            NEAR_RPC_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            log.error("RPC error: %s", data["error"])
            return None
        return data.get("result")
    except requests.RequestException as exc:
        log.error("RPC request failed: %s", exc)
        return None


def get_account_balance(account_id: str | None = None) -> dict | None:
    """Fetch account balance via NEAR RPC view_account."""
    acct = account_id or NEAR_ACCOUNT_ID
    if not acct:
        return None
    result = _rpc_call("query", {"request_type": "view_account", "finality": "final", "account_id": acct})
    if not result:
        return None
    return {
        "account_id": acct,
        "total": _yocto_to_near(result.get("amount", "0")),
        "locked": _yocto_to_near(result.get("locked", "0")),
        "storage_used": result.get("storage_usage", 0),
        "block_height": result.get("block_height", 0),
    }


def get_staking_info(account_id: str | None = None) -> dict | None:
    """Fetch staking (locked balance) info for the account."""
    acct = account_id or NEAR_ACCOUNT_ID
    if not acct:
        return None
    result = _rpc_call("query", {"request_type": "view_account", "finality": "final", "account_id": acct})
    if not result:
        return None
    locked = int(result.get("locked", "0"))
    total = int(result.get("amount", "0"))
    return {
        "account_id": acct,
        "staked": _yocto_to_near(str(locked)),
        "staked_yocto": str(locked),
        "available": _yocto_to_near(str(total)),
        "is_staking": locked > 0,
    }


def get_recent_transactions(account_id: str | None = None, limit: int = 10) -> list:
    """
    Get recent transactions from the NEAR Indexer public API.
    Falls back to local history if the indexer is unavailable.
    """
    acct = account_id or NEAR_ACCOUNT_ID
    if not acct:
        return []
    try:
        # NEAR Enhanced API (NEAR Blocks / Pagoda) — public endpoint
        api_url = f"https://api.nearblocks.io/v1/account/{acct}/txns?per_page={limit}&order=desc"
        resp = requests.get(api_url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            txns = data.get("txns", [])
            results = []
            for tx in txns[:limit]:
                results.append({
                    "hash": tx.get("transaction_hash", ""),
                    "signer": tx.get("signer_account_id", ""),
                    "receiver": tx.get("receiver_account_id", ""),
                    "block_timestamp": tx.get("block_timestamp", ""),
                    "status": "Success" if tx.get("outcomes", {}).get("status") else tx.get("outcomes_agg", {}).get("status", "Unknown"),
                })
            return results
    except requests.RequestException:
        pass

    # Fallback: return local history
    return _load_history()[-limit:]


def _yocto_to_near(yocto: str) -> str:
    """Convert yoctoNEAR string to human-readable NEAR amount."""
    try:
        val = int(yocto)
        near = val / (10**24)
        return f"{near:,.4f}"
    except (ValueError, TypeError):
        return "0.0000"


def _generate_tx_id(requester: str, recipient: str, amount: str) -> str:
    """Generate a short deterministic ID for a transfer request."""
    raw = f"{requester}:{recipient}:{amount}:{time.time()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


# ─── Slack Formatters ─────────────────────────────────────────────


def _balance_blocks(bal: dict) -> list:
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Team Wallet Balance"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Account:*\n`{bal['account_id']}`"},
                {"type": "mrkdwn", "text": f"*Available:*\n{bal['total']} NEAR"},
                {"type": "mrkdwn", "text": f"*Locked (Staked):*\n{bal['locked']} NEAR"},
                {"type": "mrkdwn", "text": f"*Storage Used:*\n{bal['storage_used']:,} bytes"},
            ],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Block height: {bal['block_height']:,} | RPC: `{NEAR_RPC_URL}`"},
            ],
        },
    ]


def _transfer_request_blocks(tx_id: str, requester: str, recipient: str, amount: str, memo: str, approvals: list, required: int) -> list:
    approval_text = ", ".join(f"<@{a}>" for a in approvals) if approvals else "_None yet_"
    status = f"{len(approvals)}/{required} approvals"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Transfer Request"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*TX ID:*\n`{tx_id}`"},
                {"type": "mrkdwn", "text": f"*Requested by:*\n<@{requester}>"},
                {"type": "mrkdwn", "text": f"*Recipient:*\n`{recipient}`"},
                {"type": "mrkdwn", "text": f"*Amount:*\n{amount} NEAR"},
            ],
        },
    ]

    if memo:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Memo:* {memo}"},
        })

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*Approvals:* {status}\n{approval_text}"},
    })

    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve"},
                "style": "primary",
                "action_id": "approve_transfer",
                "value": tx_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Reject"},
                "style": "danger",
                "action_id": "reject_transfer",
                "value": tx_id,
            },
        ],
    })

    return blocks


def _history_blocks(txns: list) -> list:
    if not txns:
        return [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "No recent transactions found."},
            }
        ]

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Recent Transactions"},
        },
    ]

    for tx in txns[:10]:
        tx_hash = tx.get("hash", "unknown")
        signer = tx.get("signer", "?")
        receiver = tx.get("receiver", "?")
        status = tx.get("status", "Unknown")
        ts = tx.get("block_timestamp", "")

        # Format timestamp if it's a nanosecond unix timestamp
        time_str = ""
        if ts:
            try:
                ts_val = int(ts)
                if ts_val > 1e15:
                    ts_val = ts_val / 1e9
                time_str = datetime.fromtimestamp(ts_val, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            except (ValueError, TypeError, OSError):
                time_str = str(ts)

        short_hash = tx_hash[:12] + "..." if len(tx_hash) > 12 else tx_hash

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"`{short_hash}` | {status}\n"
                    f"*From:* `{signer}` *To:* `{receiver}`"
                    + (f"\n{time_str}" if time_str else "")
                ),
            },
        })

    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"Account: `{NEAR_ACCOUNT_ID}` | Showing last {len(txns)} transactions"},
        ],
    })

    return blocks


def _staking_blocks(info: dict) -> list:
    status_text = "Active" if info["is_staking"] else "Not staking"

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Staking Overview"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Account:*\n`{info['account_id']}`"},
                {"type": "mrkdwn", "text": f"*Status:*\n{status_text}"},
                {"type": "mrkdwn", "text": f"*Staked:*\n{info['staked']} NEAR"},
                {"type": "mrkdwn", "text": f"*Available:*\n{info['available']} NEAR"},
            ],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "Staking data reflects the locked balance on the account. For validator-specific details, check your staking pool contract."},
            ],
        },
    ]


def _pending_tx_summary_blocks(pending: dict) -> list:
    if not pending:
        return [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "No pending transfer requests."},
            }
        ]

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Pending Transfer Requests"},
        },
    ]

    for tx_id, tx in pending.items():
        approvals = tx.get("approvals", [])
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"`{tx_id}` | {tx['amount']} NEAR -> `{tx['recipient']}`\n"
                    f"Requested by <@{tx['requester']}> | "
                    f"Approvals: {len(approvals)}/{REQUIRED_APPROVALS}"
                ),
            },
        })

    return blocks


# ─── Slash Commands ───────────────────────────────────────────────


@app.command("/near-balance")
def handle_balance(ack, respond):
    """Check the team wallet balance."""
    ack()

    if not NEAR_ACCOUNT_ID:
        respond(text="NEAR_ACCOUNT_ID is not configured. Set it in environment variables.")
        return

    bal = get_account_balance()
    if not bal:
        respond(text=f"Failed to fetch balance for `{NEAR_ACCOUNT_ID}`. Check RPC connectivity.")
        return

    respond(blocks=_balance_blocks(bal), response_type="in_channel")


@app.command("/near-send")
def handle_send(ack, respond, command):
    """Create a transfer request that requires multi-sig approval."""
    ack()

    text = (command.get("text") or "").strip()
    parts = text.split(maxsplit=2)

    if len(parts) < 2:
        respond(
            text=(
                "Usage: `/near-send <recipient> <amount> [memo]`\n"
                "Example: `/near-send alice.near 5.0 Payment for audit`"
            )
        )
        return

    recipient = parts[0]
    amount_str = parts[1]
    memo = parts[2] if len(parts) > 2 else ""

    # Validate amount
    try:
        amount_val = float(amount_str)
        if amount_val <= 0:
            raise ValueError
    except ValueError:
        respond(text=f"Invalid amount: `{amount_str}`. Must be a positive number.")
        return

    # Validate recipient looks like a NEAR account
    if not ("." in recipient or len(recipient) == 64):
        respond(
            text=(
                f"Invalid recipient: `{recipient}`.\n"
                "NEAR accounts should be named (e.g. `alice.near`) or a 64-char hex implicit account."
            )
        )
        return

    requester = command["user_id"]
    tx_id = _generate_tx_id(requester, recipient, amount_str)

    # Store pending transfer
    pending = _load_pending()
    pending[tx_id] = {
        "requester": requester,
        "recipient": recipient,
        "amount": amount_str,
        "memo": memo,
        "approvals": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "channel": command.get("channel_id", ""),
    }
    _save_pending(pending)

    log.info("Transfer request created: %s -> %s %s NEAR (by %s)", tx_id, recipient, amount_str, requester)

    respond(
        blocks=_transfer_request_blocks(tx_id, requester, recipient, amount_str, memo, [], REQUIRED_APPROVALS),
        response_type="in_channel",
    )


@app.command("/near-approve")
def handle_approve_command(ack, respond, command):
    """Approve a pending transfer via slash command."""
    ack()

    tx_id = (command.get("text") or "").strip()
    if not tx_id:
        # Show all pending
        pending = _load_pending()
        active = {k: v for k, v in pending.items() if v.get("status") == "pending"}
        respond(blocks=_pending_tx_summary_blocks(active))
        return

    user_id = command["user_id"]
    _process_approval(tx_id, user_id, respond, command.get("channel_id"))


@app.command("/near-history")
def handle_history(ack, respond):
    """Show recent transactions."""
    ack()

    if not NEAR_ACCOUNT_ID:
        respond(text="NEAR_ACCOUNT_ID is not configured.")
        return

    txns = get_recent_transactions(limit=10)
    respond(blocks=_history_blocks(txns), response_type="in_channel")


@app.command("/near-stake")
def handle_stake(ack, respond):
    """View staking information."""
    ack()

    if not NEAR_ACCOUNT_ID:
        respond(text="NEAR_ACCOUNT_ID is not configured.")
        return

    info = get_staking_info()
    if not info:
        respond(text=f"Failed to fetch staking info for `{NEAR_ACCOUNT_ID}`.")
        return

    respond(blocks=_staking_blocks(info), response_type="in_channel")


# ─── Interactive Actions (Button Clicks) ──────────────────────────


@app.action("approve_transfer")
def handle_approve_button(ack, body, respond):
    """Handle the Approve button click on a transfer request."""
    ack()
    tx_id = body["actions"][0]["value"]
    user_id = body["user"]["id"]
    channel_id = body.get("channel", {}).get("id")
    _process_approval(tx_id, user_id, respond, channel_id)


@app.action("reject_transfer")
def handle_reject_button(ack, body, respond):
    """Handle the Reject button click on a transfer request."""
    ack()
    tx_id = body["actions"][0]["value"]
    user_id = body["user"]["id"]

    pending = _load_pending()
    tx = pending.get(tx_id)

    if not tx:
        respond(text=f"Transfer `{tx_id}` not found.", replace_original=False)
        return

    if tx["status"] != "pending":
        respond(text=f"Transfer `{tx_id}` is already {tx['status']}.", replace_original=False)
        return

    # Only the requester or an approver can reject
    if user_id != tx["requester"] and (APPROVER_SLACK_IDS and user_id not in APPROVER_SLACK_IDS):
        respond(text="You don't have permission to reject this transfer.", replace_original=False)
        return

    tx["status"] = "rejected"
    tx["rejected_by"] = user_id
    tx["rejected_at"] = datetime.now(timezone.utc).isoformat()
    _save_pending(pending)

    # Record in history
    history = _load_history()
    history.append({
        "hash": tx_id,
        "signer": NEAR_ACCOUNT_ID,
        "receiver": tx["recipient"],
        "status": "Rejected",
        "block_timestamp": str(int(time.time())),
        "amount": tx["amount"],
        "rejected_by": user_id,
    })
    _save_history(history)

    log.info("Transfer %s rejected by %s", tx_id, user_id)

    respond(
        text=f"Transfer `{tx_id}` ({tx['amount']} NEAR to `{tx['recipient']}`) was *rejected* by <@{user_id}>.",
        response_type="in_channel",
        replace_original=True,
    )


# ─── Approval Logic ──────────────────────────────────────────────


def _process_approval(tx_id: str, user_id: str, respond, channel_id: str | None = None):
    """Process an approval for a pending transfer."""
    pending = _load_pending()
    tx = pending.get(tx_id)

    if not tx:
        respond(text=f"Transfer `{tx_id}` not found. Use `/near-approve` with no args to see pending requests.")
        return

    if tx["status"] != "pending":
        respond(text=f"Transfer `{tx_id}` is already *{tx['status']}*.")
        return

    # Check approver permissions
    if APPROVER_SLACK_IDS and user_id not in APPROVER_SLACK_IDS:
        respond(text="You are not authorized to approve transfers. Contact a team admin.")
        return

    # Prevent self-approval
    if user_id == tx["requester"]:
        respond(text="You cannot approve your own transfer request.")
        return

    # Prevent duplicate approvals
    if user_id in tx.get("approvals", []):
        respond(text=f"You already approved transfer `{tx_id}`.")
        return

    tx.setdefault("approvals", []).append(user_id)
    approvals = tx["approvals"]

    if len(approvals) >= REQUIRED_APPROVALS:
        # Fully approved — execute
        tx["status"] = "approved"
        tx["approved_at"] = datetime.now(timezone.utc).isoformat()
        _save_pending(pending)

        # Record in history
        history = _load_history()
        history.append({
            "hash": tx_id,
            "signer": NEAR_ACCOUNT_ID,
            "receiver": tx["recipient"],
            "status": "Approved",
            "block_timestamp": str(int(time.time())),
            "amount": tx["amount"],
            "approvers": approvals,
        })
        _save_history(history)

        log.info(
            "Transfer %s fully approved (%d/%d): %s NEAR -> %s",
            tx_id, len(approvals), REQUIRED_APPROVALS, tx["amount"], tx["recipient"],
        )

        respond(
            text=(
                f"Transfer `{tx_id}` is *fully approved* ({len(approvals)}/{REQUIRED_APPROVALS}).\n"
                f"*{tx['amount']} NEAR* will be sent to `{tx['recipient']}`.\n"
                f"Approvers: {', '.join(f'<@{a}>' for a in approvals)}\n\n"
                "_Transaction execution requires the signing key to be configured on the server. "
                "The transfer has been recorded and is ready for on-chain submission._"
            ),
            response_type="in_channel",
            replace_original=True,
        )
    else:
        _save_pending(pending)

        log.info("Transfer %s approved by %s (%d/%d)", tx_id, user_id, len(approvals), REQUIRED_APPROVALS)

        respond(
            blocks=_transfer_request_blocks(
                tx_id, tx["requester"], tx["recipient"], tx["amount"],
                tx.get("memo", ""), approvals, REQUIRED_APPROVALS,
            ),
            response_type="in_channel",
            replace_original=True,
        )


# ─── App Home ─────────────────────────────────────────────────────


@app.event("app_home_opened")
def handle_app_home(client, event):
    """Render the App Home tab with wallet overview."""
    user_id = event["user"]

    home_blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "NEAR Team Wallet"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "Manage your team's NEAR treasury directly from Slack.\n\n"
                    "*Commands:*\n"
                    "- `/near-balance` — Check wallet balance\n"
                    "- `/near-send <recipient> <amount> [memo]` — Request a transfer\n"
                    "- `/near-approve [tx_id]` — Approve a pending transfer\n"
                    "- `/near-history` — View recent transactions\n"
                    "- `/near-stake` — View staking info"
                ),
            },
        },
        {"type": "divider"},
    ]

    # Add live balance if configured
    if NEAR_ACCOUNT_ID:
        bal = get_account_balance()
        if bal:
            home_blocks.extend(_balance_blocks(bal))
            home_blocks.append({"type": "divider"})

    # Add pending transfers
    pending = _load_pending()
    active = {k: v for k, v in pending.items() if v.get("status") == "pending"}
    if active:
        home_blocks.extend(_pending_tx_summary_blocks(active))
    else:
        home_blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "_No pending transfer requests._"},
        })

    home_blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"Account: `{NEAR_ACCOUNT_ID or 'Not configured'}` | Required approvals: {REQUIRED_APPROVALS}"},
        ],
    })

    try:
        client.views_publish(
            user_id=user_id,
            view={"type": "home", "blocks": home_blocks},
        )
    except Exception as exc:
        log.error("Failed to publish App Home: %s", exc)


# ─── Message Handler (bonus: inline help) ────────────────────────


@app.event("message")
def handle_message(event, say):
    """Respond to direct messages with help text."""
    # Only respond to DMs
    if event.get("channel_type") != "im":
        return

    text = (event.get("text") or "").lower().strip()
    if text in ("help", "hi", "hello"):
        say(
            text=(
                "*NEAR Team Wallet Commands:*\n\n"
                "`/near-balance` — Check team wallet balance\n"
                "`/near-send <recipient> <amount> [memo]` — Create a transfer request\n"
                "`/near-approve` — List pending transfers\n"
                "`/near-approve <tx_id>` — Approve a specific transfer\n"
                "`/near-history` — View recent transactions\n"
                "`/near-stake` — View staking overview\n\n"
                f"_Transfers require {REQUIRED_APPROVALS} approval(s) before execution._"
            )
        )


# ─── Entry Point ──────────────────────────────────────────────────


def main():
    if not SLACK_BOT_TOKEN:
        log.error("SLACK_BOT_TOKEN is not set")
        raise SystemExit(1)

    if SLACK_APP_TOKEN:
        # Socket Mode (recommended for development and private deployments)
        log.info("Starting in Socket Mode")
        handler = SocketModeHandler(app, SLACK_APP_TOKEN)
        handler.start()
    else:
        # HTTP mode (use behind a reverse proxy for production)
        log.info("Starting HTTP server on port 3000")
        app.start(port=3000)


if __name__ == "__main__":
    main()
