#!/usr/bin/env python3
"""
NEAR Account Guardian — Telegram Bot

Monitors NEAR accounts for balance changes, new transactions, and staking
activity. Sends real-time alerts to Telegram chats.

Requires: python-telegram-bot, aiohttp
Environment: TG_BOT_TOKEN, NEAR_ACCOUNT_ID
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ─── Config ────────────────────────────────────────────────────────

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
DEFAULT_ACCOUNT_ID = os.environ.get("NEAR_ACCOUNT_ID", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "60"))

RPC_MAINNET = "https://rpc.mainnet.near.org"
RPC_TESTNET = "https://rpc.testnet.near.org"

DATA_DIR = Path(__file__).parent / "data"
WATCHERS_FILE = DATA_DIR / "watchers.json"

DATA_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("account_guardian")


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


def get_watchers() -> dict:
    return _load_json(WATCHERS_FILE)


def save_watchers(data: dict):
    _save_json(WATCHERS_FILE, data)


# ─── NEAR RPC Client ─────────────────────────────────────────────

def _rpc_url(account_id: str) -> str:
    """Pick mainnet or testnet RPC based on account suffix."""
    if account_id.endswith(".testnet"):
        return RPC_TESTNET
    return RPC_MAINNET


def _network_label(account_id: str) -> str:
    if account_id.endswith(".testnet"):
        return "testnet"
    return "mainnet"


async def rpc_call(account_id: str, method: str, params: dict) -> dict | None:
    """Make a JSON-RPC call to the appropriate NEAR RPC endpoint."""
    url = _rpc_url(account_id)
    payload = {
        "jsonrpc": "2.0",
        "id": "guardian",
        "method": method,
        "params": params,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                if "result" in data:
                    return data["result"]
                if "error" in data:
                    logger.warning("RPC error for %s: %s", account_id, data["error"])
                return None
    except Exception as e:
        logger.error("RPC request failed for %s: %s", account_id, e)
        return None


async def get_account_info(account_id: str) -> dict | None:
    """Fetch account balance, storage, and code hash."""
    return await rpc_call(account_id, "query", {
        "request_type": "view_account",
        "finality": "final",
        "account_id": account_id,
    })


async def get_access_keys(account_id: str) -> list | None:
    """Fetch all access keys for an account."""
    result = await rpc_call(account_id, "query", {
        "request_type": "view_access_key_list",
        "finality": "final",
        "account_id": account_id,
    })
    if result and "keys" in result:
        return result["keys"]
    return None


async def get_recent_txns(account_id: str, limit: int = 10) -> list:
    """Fetch recent transactions using the NEAR enhanced API (Fastnear/NEAR Explorer).

    Falls back to an empty list if the indexer is unavailable.
    """
    base = "https://api.nearblocks.io/v1"
    url = f"{base}/account/{account_id}/txns?per_page={limit}&order=desc"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("txns", [])
                return []
    except Exception as e:
        logger.debug("Nearblocks API unavailable: %s", e)
        return []


async def get_staking_info(account_id: str) -> list:
    """Get staking pools the account has delegated to via validators RPC."""
    result = await rpc_call(account_id, "validators", {"finality": "final"})
    if not result:
        return []
    validators = result.get("current_validators", [])
    return [v for v in validators if v.get("account_id", "").endswith(".poolv1.near")]


# ─── Formatting Helpers ──────────────────────────────────────────

def yocto_to_near(yocto: str | int) -> float:
    """Convert yoctoNEAR to NEAR."""
    return int(yocto) / 1e24


def format_near(yocto: str | int) -> str:
    """Format yoctoNEAR as a human-readable NEAR value."""
    near = yocto_to_near(yocto)
    if near >= 1000:
        return f"{near:,.2f}"
    return f"{near:.4f}"


def short_hash(h: str) -> str:
    """Shorten a transaction hash for display."""
    if len(h) > 16:
        return h[:8] + "..." + h[-6:]
    return h


def explorer_url(account_id: str) -> str:
    """Return the NearBlocks URL for an account."""
    network = _network_label(account_id)
    if network == "testnet":
        return f"https://testnet.nearblocks.io/address/{account_id}"
    return f"https://nearblocks.io/address/{account_id}"


def tx_explorer_url(tx_hash: str, account_id: str) -> str:
    """Return the NearBlocks URL for a transaction."""
    network = _network_label(account_id)
    if network == "testnet":
        return f"https://testnet.nearblocks.io/txns/{tx_hash}"
    return f"https://nearblocks.io/txns/{tx_hash}"


# ─── Bot Commands ────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start — welcome message and usage guide."""
    text = (
        "NEAR Account Guardian\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "I monitor NEAR accounts and alert you to balance changes, "
        "new transactions, and staking activity.\n\n"
        "Commands:\n"
        "/watch <account_id> — Start watching an account\n"
        "/balance — Check current balance\n"
        "/alerts — Show active alert settings\n"
        "/history — Recent transaction history\n\n"
        "Quick start:\n"
        "/watch alice.near\n"
    )
    if DEFAULT_ACCOUNT_ID:
        text += f"\nDefault account: {DEFAULT_ACCOUNT_ID}"
    await update.message.reply_text(text)


async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /watch <account_id> — register an account to monitor."""
    chat_id = str(update.effective_chat.id)

    if context.args:
        account_id = context.args[0].strip().lower()
    elif DEFAULT_ACCOUNT_ID:
        account_id = DEFAULT_ACCOUNT_ID
    else:
        await update.message.reply_text(
            "Usage: /watch <account_id>\n"
            "Example: /watch alice.near"
        )
        return

    # Validate the account exists
    info = await get_account_info(account_id)
    if not info:
        await update.message.reply_text(
            f"Could not find account: {account_id}\n"
            f"Network: {_network_label(account_id)}\n\n"
            "Make sure the account exists and the name is correct."
        )
        return

    balance = format_near(info.get("amount", "0"))
    network = _network_label(account_id)

    # Save watcher state
    watchers = get_watchers()
    watchers[chat_id] = {
        "account_id": account_id,
        "network": network,
        "last_balance": info.get("amount", "0"),
        "last_block_height": info.get("block_height", 0),
        "last_key_count": len(await get_access_keys(account_id) or []),
        "alerts_enabled": True,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    save_watchers(watchers)

    await update.message.reply_text(
        f"Now watching: {account_id}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Network: {network}\n"
        f"Balance: {balance} NEAR\n"
        f"Storage used: {info.get('storage_usage', 0):,} bytes\n\n"
        f"You'll receive alerts for:\n"
        f"  - Balance changes (> 0.01 NEAR)\n"
        f"  - New transactions\n"
        f"  - Access key changes\n\n"
        f"Explorer: {explorer_url(account_id)}",
        disable_web_page_preview=True,
    )


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /balance — show current account balance and details."""
    chat_id = str(update.effective_chat.id)
    watchers = get_watchers()
    watcher = watchers.get(chat_id)

    if context.args:
        account_id = context.args[0].strip().lower()
    elif watcher:
        account_id = watcher["account_id"]
    elif DEFAULT_ACCOUNT_ID:
        account_id = DEFAULT_ACCOUNT_ID
    else:
        await update.message.reply_text(
            "No account configured. Use /watch <account_id> first."
        )
        return

    info = await get_account_info(account_id)
    if not info:
        await update.message.reply_text(f"Could not fetch data for {account_id}")
        return

    balance_near = yocto_to_near(info.get("amount", "0"))
    locked = yocto_to_near(info.get("locked", "0"))
    storage = info.get("storage_usage", 0)
    code_hash = info.get("code_hash", "")
    has_contract = code_hash != "11111111111111111111111111111111"

    keys = await get_access_keys(account_id)
    key_count = len(keys) if keys else 0

    lines = [
        f"Account: {account_id}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Network: {_network_label(account_id)}",
        f"",
        f"Available: {format_near(info.get('amount', '0'))} NEAR",
    ]

    if locked > 0:
        lines.append(f"Locked (staked): {format_near(info.get('locked', '0'))} NEAR")

    lines.extend([
        f"Total: {format_near(str(int(info.get('amount', '0')) + int(info.get('locked', '0'))))} NEAR",
        f"",
        f"Storage: {storage:,} bytes",
        f"Access keys: {key_count}",
        f"Contract deployed: {'Yes' if has_contract else 'No'}",
        f"",
        f"Explorer: {explorer_url(account_id)}",
    ])

    await update.message.reply_text(
        "\n".join(lines),
        disable_web_page_preview=True,
    )


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /alerts — show current alert configuration."""
    chat_id = str(update.effective_chat.id)
    watchers = get_watchers()
    watcher = watchers.get(chat_id)

    if not watcher:
        await update.message.reply_text(
            "No account being watched. Use /watch <account_id> first."
        )
        return

    account_id = watcher["account_id"]
    enabled = watcher.get("alerts_enabled", True)
    started = watcher.get("started_at", "unknown")

    lines = [
        f"Alert Settings",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Account: {account_id}",
        f"Network: {watcher.get('network', 'mainnet')}",
        f"Status: {'Active' if enabled else 'Paused'}",
        f"Watching since: {started[:19]}",
        f"Poll interval: {POLL_INTERVAL}s",
        f"",
        f"Monitored events:",
        f"  - Balance changes (> 0.01 NEAR)",
        f"  - New transactions",
        f"  - Access key additions/removals",
        f"",
        f"Last known balance: {format_near(watcher.get('last_balance', '0'))} NEAR",
        f"Last known keys: {watcher.get('last_key_count', '?')}",
    ]

    await update.message.reply_text("\n".join(lines))


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /history — show recent transactions."""
    chat_id = str(update.effective_chat.id)
    watchers = get_watchers()
    watcher = watchers.get(chat_id)

    if context.args:
        account_id = context.args[0].strip().lower()
    elif watcher:
        account_id = watcher["account_id"]
    elif DEFAULT_ACCOUNT_ID:
        account_id = DEFAULT_ACCOUNT_ID
    else:
        await update.message.reply_text(
            "No account configured. Use /watch <account_id> first."
        )
        return

    txns = await get_recent_txns(account_id, limit=10)

    if not txns:
        await update.message.reply_text(
            f"No recent transactions found for {account_id}.\n\n"
            f"This may happen if the indexer API is temporarily unavailable. "
            f"Check the explorer directly:\n{explorer_url(account_id)}"
        )
        return

    lines = [
        f"Recent Transactions: {account_id}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    for tx in txns[:10]:
        tx_hash = tx.get("transaction_hash", "?")
        signer = tx.get("signer_account_id", "?")
        receiver = tx.get("receiver_account_id", "?")
        block_ts = tx.get("block_timestamp", "")

        # Format timestamp
        ts_display = ""
        if block_ts:
            try:
                # Nearblocks returns nanosecond timestamps
                ts_sec = int(block_ts) / 1e9 if int(block_ts) > 1e12 else int(block_ts)
                dt = datetime.fromtimestamp(ts_sec, tz=timezone.utc)
                ts_display = dt.strftime("%m/%d %H:%M")
            except (ValueError, TypeError):
                ts_display = ""

        direction = "OUT" if signer == account_id else "IN"
        counterparty = receiver if direction == "OUT" else signer

        lines.append(f"")
        lines.append(f"[{direction}] {ts_display}")
        lines.append(f"  {'To' if direction == 'OUT' else 'From'}: {counterparty}")
        lines.append(f"  Tx: {short_hash(tx_hash)}")

    lines.append(f"\nExplorer: {explorer_url(account_id)}")

    await update.message.reply_text(
        "\n".join(lines),
        disable_web_page_preview=True,
    )


# ─── Background Monitor ─────────────────────────────────────────

async def monitor_loop(app: Application):
    """Periodically check watched accounts and send alerts."""
    logger.info("Monitor loop started (interval: %ds)", POLL_INTERVAL)

    while True:
        try:
            await asyncio.sleep(POLL_INTERVAL)
            watchers = get_watchers()
            if not watchers:
                continue

            for chat_id, watcher in watchers.items():
                if not watcher.get("alerts_enabled", True):
                    continue

                account_id = watcher["account_id"]
                alerts = []

                # Check balance
                info = await get_account_info(account_id)
                if not info:
                    continue

                current_balance = info.get("amount", "0")
                last_balance = watcher.get("last_balance", "0")
                balance_diff = int(current_balance) - int(last_balance)
                diff_near = abs(balance_diff) / 1e24

                if diff_near > 0.01:
                    direction = "increased" if balance_diff > 0 else "decreased"
                    alerts.append(
                        f"Balance {direction} by {diff_near:.4f} NEAR\n"
                        f"  Previous: {format_near(last_balance)} NEAR\n"
                        f"  Current:  {format_near(current_balance)} NEAR"
                    )

                # Check access keys
                keys = await get_access_keys(account_id)
                current_key_count = len(keys) if keys else 0
                last_key_count = watcher.get("last_key_count", 0)

                if current_key_count != last_key_count:
                    diff = current_key_count - last_key_count
                    if diff > 0:
                        alerts.append(
                            f"New access key(s) added ({diff})\n"
                            f"  Total keys: {current_key_count}"
                        )
                    else:
                        alerts.append(
                            f"Access key(s) removed ({abs(diff)})\n"
                            f"  Total keys: {current_key_count}"
                        )

                # Check staking changes (locked balance)
                current_locked = info.get("locked", "0")
                last_locked = watcher.get("last_locked", "0")
                locked_diff = int(current_locked) - int(last_locked)
                locked_diff_near = abs(locked_diff) / 1e24

                if locked_diff_near > 0.01:
                    direction = "increased" if locked_diff > 0 else "decreased"
                    alerts.append(
                        f"Staked balance {direction} by {locked_diff_near:.4f} NEAR\n"
                        f"  Locked: {format_near(current_locked)} NEAR"
                    )

                # Send alerts
                if alerts:
                    header = (
                        f"Alert: {account_id}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    )
                    body = "\n\n".join(alerts)
                    footer = f"\n\nExplorer: {explorer_url(account_id)}"

                    try:
                        await app.bot.send_message(
                            chat_id=int(chat_id),
                            text=header + body + footer,
                            disable_web_page_preview=True,
                        )
                    except Exception as e:
                        logger.error("Failed to send alert to %s: %s", chat_id, e)

                # Update watcher state
                watcher["last_balance"] = current_balance
                watcher["last_locked"] = current_locked
                watcher["last_key_count"] = current_key_count
                watcher["last_block_height"] = info.get("block_height", 0)
                watcher["last_checked"] = datetime.now(timezone.utc).isoformat()

            save_watchers(watchers)

        except asyncio.CancelledError:
            logger.info("Monitor loop cancelled")
            break
        except Exception as e:
            logger.error("Monitor loop error: %s", e)
            await asyncio.sleep(10)


async def post_init(app: Application):
    """Start the background monitor after the bot initializes."""
    app.create_task(monitor_loop(app))


# ─── Entry Point ─────────────────────────────────────────────────

def main():
    if not TG_BOT_TOKEN:
        print("ERROR: Set TG_BOT_TOKEN environment variable")
        print("  export TG_BOT_TOKEN='your-telegram-bot-token'")
        return

    app = Application.builder().token(TG_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("history", cmd_history))

    logger.info("Starting NEAR Account Guardian bot...")
    if DEFAULT_ACCOUNT_ID:
        logger.info("Default account: %s", DEFAULT_ACCOUNT_ID)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
