#!/usr/bin/env python3
"""
OpenClaw Skill: NEAR DAO Governance

Participate in NEAR DAO governance — list DAOs, view proposals,
vote, create proposals, and inspect treasury.

Uses Sputnik DAO v2 contract interface.

Commands:
    near_dao_list        — List active DAOs on NEAR
    near_dao_info        — Get DAO details and policy
    near_proposals_list  — List proposals for a DAO
    near_proposal_vote   — Vote on a proposal
    near_proposal_create — Create a new proposal
    near_dao_treasury    — View DAO treasury

Environment:
    NEAR_ACCOUNT_ID  — Your NEAR account
    NEAR_RPC_URL     — RPC endpoint (default: mainnet)
"""

import base64
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ─── Config ────────────────────────────────────────────────────────

NEAR_ACCOUNT = os.environ.get("NEAR_ACCOUNT_ID", "")
NEAR_RPC = os.environ.get("NEAR_RPC_URL", "https://rpc.mainnet.near.org")

# Well-known Sputnik DAOs
KNOWN_DAOS = [
    "sputnik-dao.near",
    "nearweek-news.sputnik-dao.near",
    "marketing-dao.sputnik-dao.near",
    "creativesdao.sputnik-dao.near",
    "near-analytics.sputnik-dao.near",
    "human-guild.sputnik-dao.near",
    "move-dao.sputnik-dao.near",
    "ref-community-board.sputnik-dao.near",
]


# ─── NEAR RPC Client ──────────────────────────────────────────────

def rpc_call(method: str, params: dict) -> dict:
    """Make a NEAR JSON-RPC call."""
    payload = {
        "jsonrpc": "2.0",
        "id": "dao-governance",
        "method": method,
        "params": params,
    }
    req = Request(
        NEAR_RPC,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if "error" in result:
                return {"error": result["error"]}
            return result.get("result", {})
    except (HTTPError, URLError, json.JSONDecodeError) as e:
        return {"error": str(e)}


def view_call(contract: str, method: str, args: dict | None = None):
    """Call a view method on a NEAR contract."""
    args_b64 = base64.b64encode(json.dumps(args or {}).encode()).decode()
    result = rpc_call("query", {
        "request_type": "call_function",
        "finality": "final",
        "account_id": contract,
        "method_name": method,
        "args_base64": args_b64,
    })

    if "error" in result:
        return result

    result_bytes = result.get("result", [])
    if isinstance(result_bytes, list):
        try:
            decoded = bytes(result_bytes).decode("utf-8")
            return json.loads(decoded)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"raw": str(result_bytes)}

    return result


def view_account(account_id: str) -> dict:
    """Get NEAR account info."""
    return rpc_call("query", {
        "request_type": "view_account",
        "finality": "final",
        "account_id": account_id,
    })


def yocto_to_near(yocto) -> float:
    return int(yocto) / 1e24


# ─── Skill Commands ───────────────────────────────────────────────

def near_dao_list() -> dict:
    """List active DAOs on NEAR.

    Returns:
        Dict with list of known DAOs and their basic info
    """
    daos = []
    for dao_id in KNOWN_DAOS:
        info = view_account(dao_id)
        if "error" in info:
            continue

        balance = yocto_to_near(info.get("amount", 0))

        # Try to get policy for member count
        policy = view_call(dao_id, "get_policy")
        council_count = 0
        if isinstance(policy, dict):
            roles = policy.get("roles", [])
            for role in roles:
                if role.get("name") == "council":
                    kind = role.get("kind", {})
                    if isinstance(kind, dict) and "Group" in kind:
                        council_count = len(kind["Group"])

        daos.append({
            "dao_id": dao_id,
            "balance_near": round(balance, 2),
            "council_members": council_count,
        })

    return {
        "daos": daos,
        "total": len(daos),
    }


def near_dao_info(dao_id: str) -> dict:
    """Get DAO details including policy, council, and treasury.

    Args:
        dao_id: DAO contract address (e.g. marketing-dao.sputnik-dao.near)

    Returns:
        Dict with full DAO information
    """
    # Get account info for balance
    account = view_account(dao_id)
    if "error" in account:
        return {"error": f"DAO not found: {dao_id}", "details": account}

    balance = yocto_to_near(account.get("amount", 0))

    # Get policy
    policy = view_call(dao_id, "get_policy")
    if not isinstance(policy, dict):
        return {"error": f"Could not read policy for {dao_id}"}

    # Extract roles and council
    roles = []
    council_members = []
    for role in policy.get("roles", []):
        role_info = {
            "name": role.get("name", ""),
            "permissions": role.get("permissions", []),
        }
        kind = role.get("kind", {})
        if isinstance(kind, dict):
            if "Group" in kind:
                role_info["members"] = kind["Group"]
                if role.get("name") == "council":
                    council_members = kind["Group"]
            elif "Member" in kind:
                role_info["type"] = "member"
        elif kind == "Everyone":
            role_info["type"] = "everyone"

        roles.append(role_info)

    # Get proposal count
    last_proposal = view_call(dao_id, "get_last_proposal_id")
    proposal_count = last_proposal if isinstance(last_proposal, int) else 0

    return {
        "dao_id": dao_id,
        "balance_near": round(balance, 2),
        "proposal_bond": policy.get("proposal_bond", ""),
        "bounty_bond": policy.get("bounty_bond", ""),
        "proposal_period": policy.get("proposal_period", ""),
        "council_members": council_members,
        "council_count": len(council_members),
        "roles": roles,
        "total_proposals": proposal_count,
    }


def near_proposals_list(dao_id: str, status: str = "all",
                        limit: int = 20) -> dict:
    """List proposals for a DAO.

    Args:
        dao_id: DAO contract address
        status: Filter by status (all, active, approved, rejected, expired)
        limit: Max proposals to return

    Returns:
        Dict with proposals list
    """
    # Get last proposal ID to know the range
    last_id = view_call(dao_id, "get_last_proposal_id")
    if not isinstance(last_id, int) or last_id == 0:
        return {"proposals": [], "total": 0, "dao_id": dao_id}

    # Fetch recent proposals
    from_index = max(0, last_id - limit)
    proposals_raw = view_call(dao_id, "get_proposals", {
        "from_index": from_index,
        "limit": limit,
    })

    if not isinstance(proposals_raw, list):
        return {"error": f"Could not fetch proposals from {dao_id}"}

    proposals = []
    for p in proposals_raw:
        p_status = p.get("status", "Unknown")

        # Apply status filter
        if status != "all":
            status_map = {
                "active": "InProgress",
                "approved": "Approved",
                "rejected": "Rejected",
                "expired": "Expired",
            }
            if p_status != status_map.get(status, status):
                continue

        # Parse votes
        votes = p.get("votes", {})
        approve_count = sum(1 for v in votes.values() if v == "Approve")
        reject_count = sum(1 for v in votes.values() if v == "Reject")

        # Parse proposal kind
        kind = p.get("kind", {})
        kind_type = "Unknown"
        if isinstance(kind, dict):
            kind_type = list(kind.keys())[0] if kind else "Unknown"
        elif isinstance(kind, str):
            kind_type = kind

        proposals.append({
            "id": p.get("id", from_index + proposals_raw.index(p)),
            "proposer": p.get("proposer", ""),
            "kind": kind_type,
            "description": (p.get("description", "") or "")[:200],
            "status": p_status,
            "votes_approve": approve_count,
            "votes_reject": reject_count,
            "votes_total": len(votes),
            "submission_time": p.get("submission_time", ""),
        })

    return {
        "dao_id": dao_id,
        "proposals": proposals,
        "total": len(proposals),
        "last_proposal_id": last_id,
    }


def near_proposal_vote(dao_id: str, proposal_id: int,
                       vote: str = "approve") -> dict:
    """Build a vote transaction for a DAO proposal.

    Note: Actual execution requires signing via near-cli or wallet.

    Args:
        dao_id: DAO contract address
        proposal_id: Proposal ID to vote on
        vote: Vote type (approve, reject, remove)

    Returns:
        Dict with transaction parameters
    """
    vote_map = {
        "approve": "VoteApprove",
        "reject": "VoteReject",
        "remove": "VoteRemove",
    }

    if vote not in vote_map:
        return {"error": f"Invalid vote: {vote}. Use: approve, reject, remove"}

    args = {
        "id": proposal_id,
        "action": vote_map[vote],
    }

    return {
        "action": "act_proposal",
        "dao_id": dao_id,
        "method": "act_proposal",
        "args": args,
        "deposit": "0",
        "gas": "200000000000000",  # 200 TGas
        "near_cli": (
            f'near call {dao_id} act_proposal '
            f'\'{json.dumps(args)}\' '
            f'--accountId {NEAR_ACCOUNT} --gas 200000000000000'
        ),
        "note": "Execute via near-cli or wallet. You must be a council member to vote.",
    }


def near_proposal_create(dao_id: str, kind: str, description: str,
                         details: dict | None = None) -> dict:
    """Build a proposal creation transaction.

    Note: Actual execution requires signing and proposal bond deposit.

    Args:
        dao_id: DAO contract address
        kind: Proposal type (transfer, function_call, policy, vote)
        description: Proposal description
        details: Kind-specific details

    Returns:
        Dict with transaction parameters
    """
    details = details or {}

    kind_payload = {}
    if kind == "transfer":
        kind_payload = {
            "Transfer": {
                "token_id": details.get("token_id", ""),
                "receiver_id": details.get("receiver_id", ""),
                "amount": details.get("amount", "0"),
            }
        }
    elif kind == "function_call":
        kind_payload = {
            "FunctionCall": {
                "receiver_id": details.get("receiver_id", ""),
                "actions": details.get("actions", []),
            }
        }
    elif kind == "policy":
        kind_payload = {
            "ChangePolicy": {
                "policy": details.get("policy", {}),
            }
        }
    elif kind == "vote":
        kind_payload = {"Vote": {}}
    else:
        return {"error": f"Unknown proposal kind: {kind}. Use: transfer, function_call, policy, vote"}

    args = {
        "proposal": {
            "description": description,
            "kind": kind_payload,
        }
    }

    # Get proposal bond from policy
    policy = view_call(dao_id, "get_policy")
    bond = "100000000000000000000000"  # Default 0.1 NEAR
    if isinstance(policy, dict):
        bond = policy.get("proposal_bond", bond)

    bond_near = yocto_to_near(bond)

    return {
        "action": "add_proposal",
        "dao_id": dao_id,
        "method": "add_proposal",
        "args": args,
        "deposit": bond,
        "deposit_near": round(bond_near, 4),
        "gas": "200000000000000",
        "near_cli": (
            f'near call {dao_id} add_proposal '
            f'\'{json.dumps(args)}\' '
            f'--accountId {NEAR_ACCOUNT} --deposit {bond_near}'
        ),
        "note": f"Requires {bond_near} NEAR proposal bond. Execute via near-cli or wallet.",
    }


def near_dao_treasury(dao_id: str) -> dict:
    """View DAO treasury details — NEAR balance and token holdings.

    Args:
        dao_id: DAO contract address

    Returns:
        Dict with treasury breakdown
    """
    account = view_account(dao_id)
    if "error" in account:
        return {"error": f"DAO not found: {dao_id}"}

    near_balance = yocto_to_near(account.get("amount", 0))
    staked = yocto_to_near(account.get("locked", 0))
    storage_bytes = account.get("storage_usage", 0)

    # Check common FT balances
    known_tokens = [
        ("wrap.near", "wNEAR"),
        ("token.ref-finance.near", "REF"),
        ("usn", "USN"),
        ("meta-pool.near", "stNEAR"),
        ("aurora", "AURORA"),
    ]

    token_balances = []
    for token_contract, symbol in known_tokens:
        result = view_call(token_contract, "ft_balance_of", {
            "account_id": dao_id,
        })
        if isinstance(result, str) and result != "0":
            # Get decimals
            metadata = view_call(token_contract, "ft_metadata")
            decimals = 24
            if isinstance(metadata, dict):
                decimals = metadata.get("decimals", 24)
            balance = int(result) / (10 ** decimals)
            if balance > 0.001:
                token_balances.append({
                    "token": symbol,
                    "contract": token_contract,
                    "balance": round(balance, 4),
                })

    return {
        "dao_id": dao_id,
        "near_balance": round(near_balance, 4),
        "near_staked": round(staked, 4),
        "near_total": round(near_balance + staked, 4),
        "storage_bytes": storage_bytes,
        "token_holdings": token_balances,
    }


# ─── CLI ───────────────────────────────────────────────────────────

def main():
    commands = {
        "daos": ("List DAOs", near_dao_list),
        "info": ("DAO info", near_dao_info),
        "proposals": ("List proposals", near_proposals_list),
        "vote": ("Vote on proposal", near_proposal_vote),
        "propose": ("Create proposal", near_proposal_create),
        "treasury": ("View treasury", near_dao_treasury),
    }

    if len(sys.argv) < 2:
        print("NEAR DAO Governance Skill")
        print(f"\nCommands:")
        for cmd, (desc, _) in commands.items():
            print(f"  {cmd:12} — {desc}")
        print(f"\nUsage: python {sys.argv[0]} <command> [json_kwargs]")
        print(f"\nExamples:")
        print(f'  python {sys.argv[0]} daos')
        print(f'  python {sys.argv[0]} info \'{{"dao_id": "marketing-dao.sputnik-dao.near"}}\'')
        print(f'  python {sys.argv[0]} proposals \'{{"dao_id": "marketing-dao.sputnik-dao.near", "status": "active"}}\'')
        print(f'  python {sys.argv[0]} treasury \'{{"dao_id": "marketing-dao.sputnik-dao.near"}}\'')
        return

    cmd = sys.argv[1]
    if cmd not in commands:
        print(f"Unknown command: {cmd}")
        return

    kwargs = {}
    if len(sys.argv) > 2:
        try:
            kwargs = json.loads(sys.argv[2])
        except json.JSONDecodeError:
            print(f"Invalid JSON: {sys.argv[2]}")
            return

    _, func = commands[cmd]
    result = func(**kwargs)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
