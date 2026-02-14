#!/usr/bin/env python3
"""
NEAR DAO Helper — Discord Bot

Discord bot for NEAR Sputnik DAO v2 governance operations.
Browse proposals, vote, create proposals, and inspect DAO treasury
directly from Discord.

Requires: discord.py, aiohttp, python-dotenv
Environment:
    DISCORD_BOT_TOKEN  — Discord bot token
    NEAR_ACCOUNT_ID    — Your NEAR account (for building CLI commands)
    NEAR_RPC_URL       — RPC endpoint (default: mainnet)
    DEFAULT_DAO_ID     — Default DAO contract to interact with
"""

import asyncio
import base64
import json
import os
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# ─── Config ────────────────────────────────────────────────────────

DISCORD_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
NEAR_ACCOUNT = os.environ.get("NEAR_ACCOUNT_ID", "")
NEAR_RPC = os.environ.get("NEAR_RPC_URL", "https://rpc.mainnet.near.org")
DEFAULT_DAO = os.environ.get("DEFAULT_DAO_ID", "")

# Well-known Sputnik DAOs for autocomplete suggestions
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

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ─── NEAR RPC Client (async) ─────────────────────────────────────

async def rpc_call(method: str, params: dict) -> dict:
    """Make an async NEAR JSON-RPC call."""
    payload = {
        "jsonrpc": "2.0",
        "id": "dao-helper",
        "method": method,
        "params": params,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                NEAR_RPC,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                result = await resp.json()
                if "error" in result:
                    return {"error": result["error"]}
                return result.get("result", {})
    except Exception as e:
        return {"error": str(e)}


async def view_call(contract: str, method: str, args: dict | None = None):
    """Call a view method on a NEAR contract."""
    args_b64 = base64.b64encode(json.dumps(args or {}).encode()).decode()
    result = await rpc_call("query", {
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


async def view_account(account_id: str) -> dict:
    """Get NEAR account info."""
    return await rpc_call("query", {
        "request_type": "view_account",
        "finality": "final",
        "account_id": account_id,
    })


def yocto_to_near(yocto) -> float:
    """Convert yoctoNEAR to NEAR."""
    try:
        return int(yocto) / 1e24
    except (ValueError, TypeError):
        return 0.0


def format_near(amount: float) -> str:
    """Format a NEAR amount for display."""
    if amount >= 1000:
        return f"{amount:,.2f}"
    return f"{amount:.4f}"


def nano_to_days(nanos) -> str:
    """Convert nanoseconds to a human-readable duration."""
    try:
        seconds = int(nanos) / 1e9
        days = seconds / 86400
        if days >= 1:
            return f"{days:.0f} day{'s' if days != 1 else ''}"
        hours = seconds / 3600
        return f"{hours:.1f} hour{'s' if hours != 1 else ''}"
    except (ValueError, TypeError):
        return "unknown"


def resolve_dao(dao_id: str | None) -> str | None:
    """Resolve a DAO ID, falling back to the default if unset."""
    if dao_id:
        return dao_id
    if DEFAULT_DAO:
        return DEFAULT_DAO
    return None


# ─── Autocomplete ─────────────────────────────────────────────────

async def dao_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete for DAO IDs."""
    matches = [
        d for d in KNOWN_DAOS if current.lower() in d.lower()
    ]
    if not matches:
        matches = KNOWN_DAOS
    return [
        app_commands.Choice(name=d, value=d)
        for d in matches[:25]
    ]


async def vote_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete for vote actions."""
    choices = [
        app_commands.Choice(name="Approve", value="approve"),
        app_commands.Choice(name="Reject", value="reject"),
        app_commands.Choice(name="Remove", value="remove"),
    ]
    if current:
        choices = [c for c in choices if current.lower() in c.name.lower()]
    return choices


async def proposal_kind_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete for proposal kinds."""
    choices = [
        app_commands.Choice(name="Transfer NEAR or tokens", value="transfer"),
        app_commands.Choice(name="Function call", value="function_call"),
        app_commands.Choice(name="Poll / vote", value="vote"),
        app_commands.Choice(name="Add council member", value="add_member"),
        app_commands.Choice(name="Remove council member", value="remove_member"),
    ]
    if current:
        choices = [c for c in choices if current.lower() in c.name.lower()]
    return choices


# ─── Embeds ───────────────────────────────────────────────────────

STATUS_COLORS = {
    "InProgress": discord.Color.blue(),
    "Approved": discord.Color.green(),
    "Rejected": discord.Color.red(),
    "Expired": discord.Color.dark_grey(),
    "Removed": discord.Color.dark_red(),
    "Moved": discord.Color.purple(),
    "Failed": discord.Color.dark_red(),
}

STATUS_LABELS = {
    "InProgress": "Active",
    "Approved": "Approved",
    "Rejected": "Rejected",
    "Expired": "Expired",
    "Removed": "Removed",
    "Moved": "Moved",
    "Failed": "Failed",
}

KIND_LABELS = {
    "Transfer": "Transfer",
    "FunctionCall": "Function Call",
    "ChangePolicy": "Policy Change",
    "ChangePolicyAddOrUpdateRole": "Add/Update Role",
    "ChangePolicyRemoveRole": "Remove Role",
    "ChangePolicyUpdateDefaultVotePolicy": "Update Vote Policy",
    "ChangePolicyUpdateParameters": "Update Parameters",
    "AddMemberToRole": "Add Member",
    "RemoveMemberFromRole": "Remove Member",
    "UpgradeSelf": "Upgrade DAO",
    "UpgradeRemote": "Remote Upgrade",
    "SetStakingContract": "Set Staking Contract",
    "AddBounty": "Add Bounty",
    "BountyDone": "Bounty Done",
    "Vote": "Poll",
}


def proposal_embed(proposal: dict, dao_id: str) -> discord.Embed:
    """Build a rich embed for a single proposal."""
    status = proposal.get("status", "Unknown")
    kind = proposal.get("kind", {})

    # Parse kind
    if isinstance(kind, dict):
        kind_key = list(kind.keys())[0] if kind else "Unknown"
        kind_details = kind.get(kind_key, {})
    elif isinstance(kind, str):
        kind_key = kind
        kind_details = {}
    else:
        kind_key = "Unknown"
        kind_details = {}

    kind_label = KIND_LABELS.get(kind_key, kind_key)
    color = STATUS_COLORS.get(status, discord.Color.greyple())
    status_label = STATUS_LABELS.get(status, status)

    # Description
    desc = proposal.get("description", "") or ""
    # Sputnik proposals sometimes have description as JSON with link/text
    display_desc = desc[:400]
    if len(desc) > 400:
        display_desc += "..."

    embed = discord.Embed(
        title=f"Proposal #{proposal.get('id', '?')} — {kind_label}",
        description=display_desc or "No description provided.",
        color=color,
    )

    embed.add_field(name="Status", value=status_label, inline=True)
    embed.add_field(name="Proposer", value=f"`{proposal.get('proposer', 'unknown')}`", inline=True)
    embed.add_field(name="DAO", value=f"`{dao_id}`", inline=True)

    # Vote tally
    votes = proposal.get("votes", {})
    approve_count = sum(1 for v in votes.values() if v == "Approve")
    reject_count = sum(1 for v in votes.values() if v == "Reject")
    remove_count = sum(1 for v in votes.values() if v == "Remove")

    vote_str = f"Approve: {approve_count} | Reject: {reject_count}"
    if remove_count > 0:
        vote_str += f" | Remove: {remove_count}"
    embed.add_field(name="Votes", value=vote_str, inline=False)

    # Kind-specific details
    if kind_key == "Transfer" and isinstance(kind_details, dict):
        receiver = kind_details.get("receiver_id", "?")
        amount = kind_details.get("amount", "0")
        token = kind_details.get("token_id", "")
        if token:
            embed.add_field(name="Transfer", value=f"`{amount}` of `{token}` to `{receiver}`", inline=False)
        else:
            near_amt = yocto_to_near(amount)
            embed.add_field(name="Transfer", value=f"{format_near(near_amt)} NEAR to `{receiver}`", inline=False)

    elif kind_key == "FunctionCall" and isinstance(kind_details, dict):
        receiver = kind_details.get("receiver_id", "?")
        actions = kind_details.get("actions", [])
        methods = [a.get("method_name", "?") for a in actions if isinstance(a, dict)]
        embed.add_field(name="Contract", value=f"`{receiver}`", inline=True)
        if methods:
            embed.add_field(name="Methods", value=", ".join(f"`{m}`" for m in methods), inline=True)

    elif kind_key in ("AddMemberToRole", "RemoveMemberFromRole") and isinstance(kind_details, dict):
        member = kind_details.get("member_id", "?")
        role = kind_details.get("role", "?")
        embed.add_field(name="Member", value=f"`{member}`", inline=True)
        embed.add_field(name="Role", value=role, inline=True)

    # Submission time
    sub_time = proposal.get("submission_time", "")
    if sub_time:
        try:
            ts = int(sub_time) / 1e9
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            embed.set_footer(text=f"Submitted {dt.strftime('%Y-%m-%d %H:%M UTC')}")
        except (ValueError, TypeError, OSError):
            pass

    return embed


def dao_info_embed(info: dict) -> discord.Embed:
    """Build a rich embed for DAO information."""
    dao_id = info.get("dao_id", "Unknown DAO")
    embed = discord.Embed(
        title=f"DAO: {dao_id}",
        color=discord.Color.teal(),
    )

    embed.add_field(
        name="Treasury",
        value=f"{format_near(info.get('balance_near', 0))} NEAR",
        inline=True,
    )
    embed.add_field(
        name="Council Members",
        value=str(info.get("council_count", 0)),
        inline=True,
    )
    embed.add_field(
        name="Total Proposals",
        value=str(info.get("total_proposals", 0)),
        inline=True,
    )

    # Bonds
    bond = info.get("proposal_bond", "")
    if bond:
        bond_near = yocto_to_near(bond)
        embed.add_field(name="Proposal Bond", value=f"{format_near(bond_near)} NEAR", inline=True)

    period = info.get("proposal_period", "")
    if period:
        embed.add_field(name="Voting Period", value=nano_to_days(period), inline=True)

    bounty_bond = info.get("bounty_bond", "")
    if bounty_bond:
        bb_near = yocto_to_near(bounty_bond)
        embed.add_field(name="Bounty Bond", value=f"{format_near(bb_near)} NEAR", inline=True)

    # Council list
    council = info.get("council_members", [])
    if council:
        member_list = "\n".join(f"  `{m}`" for m in council[:15])
        if len(council) > 15:
            member_list += f"\n  ... and {len(council) - 15} more"
        embed.add_field(name="Council", value=member_list, inline=False)

    embed.set_footer(text=f"Sputnik DAO v2 | {dao_id}")
    return embed


def treasury_embed(treasury: dict) -> discord.Embed:
    """Build a rich embed for DAO treasury."""
    dao_id = treasury.get("dao_id", "Unknown DAO")
    embed = discord.Embed(
        title=f"Treasury: {dao_id}",
        color=discord.Color.gold(),
    )

    embed.add_field(
        name="NEAR Balance",
        value=f"{format_near(treasury.get('near_balance', 0))} NEAR",
        inline=True,
    )
    embed.add_field(
        name="Staked",
        value=f"{format_near(treasury.get('near_staked', 0))} NEAR",
        inline=True,
    )
    embed.add_field(
        name="Total",
        value=f"{format_near(treasury.get('near_total', 0))} NEAR",
        inline=True,
    )

    storage = treasury.get("storage_bytes", 0)
    if storage:
        embed.add_field(
            name="Storage Used",
            value=f"{storage:,} bytes ({storage / 1024:.1f} KB)",
            inline=True,
        )

    # Token holdings
    tokens = treasury.get("token_holdings", [])
    if tokens:
        token_lines = [f"  {t['balance']:,.4f} {t['token']} (`{t['contract']}`)" for t in tokens]
        embed.add_field(name="Token Holdings", value="\n".join(token_lines), inline=False)
    else:
        embed.add_field(name="Token Holdings", value="No fungible token holdings detected.", inline=False)

    embed.set_footer(text=f"Sputnik DAO v2 | {dao_id}")
    return embed


# ─── DAO Data Fetchers ────────────────────────────────────────────

async def fetch_dao_info(dao_id: str) -> dict:
    """Fetch full DAO information from on-chain."""
    account = await view_account(dao_id)
    if "error" in account:
        return {"error": f"DAO not found: {dao_id}", "details": account}

    balance = yocto_to_near(account.get("amount", 0))

    policy = await view_call(dao_id, "get_policy")
    if not isinstance(policy, dict):
        return {"error": f"Could not read policy for {dao_id}"}

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

    last_proposal = await view_call(dao_id, "get_last_proposal_id")
    proposal_count = last_proposal if isinstance(last_proposal, int) else 0

    return {
        "dao_id": dao_id,
        "balance_near": round(balance, 4),
        "proposal_bond": policy.get("proposal_bond", ""),
        "bounty_bond": policy.get("bounty_bond", ""),
        "proposal_period": policy.get("proposal_period", ""),
        "council_members": council_members,
        "council_count": len(council_members),
        "roles": roles,
        "total_proposals": proposal_count,
    }


async def fetch_proposals(dao_id: str, status: str = "all", limit: int = 10) -> dict:
    """Fetch proposals from a DAO contract."""
    last_id = await view_call(dao_id, "get_last_proposal_id")
    if not isinstance(last_id, int) or last_id == 0:
        return {"proposals": [], "total": 0, "dao_id": dao_id}

    from_index = max(0, last_id - limit)
    proposals_raw = await view_call(dao_id, "get_proposals", {
        "from_index": from_index,
        "limit": limit,
    })

    if not isinstance(proposals_raw, list):
        return {"error": f"Could not fetch proposals from {dao_id}"}

    proposals = []
    for i, p in enumerate(proposals_raw):
        p_status = p.get("status", "Unknown")

        if status != "all":
            status_map = {
                "active": "InProgress",
                "approved": "Approved",
                "rejected": "Rejected",
                "expired": "Expired",
            }
            if p_status != status_map.get(status, status):
                continue

        p["id"] = from_index + i
        proposals.append(p)

    return {
        "dao_id": dao_id,
        "proposals": proposals,
        "total": len(proposals),
        "last_proposal_id": last_id,
    }


async def fetch_treasury(dao_id: str) -> dict:
    """Fetch DAO treasury details."""
    account = await view_account(dao_id)
    if "error" in account:
        return {"error": f"DAO not found: {dao_id}"}

    near_balance = yocto_to_near(account.get("amount", 0))
    staked = yocto_to_near(account.get("locked", 0))
    storage_bytes = account.get("storage_usage", 0)

    known_tokens = [
        ("wrap.near", "wNEAR"),
        ("token.ref-finance.near", "REF"),
        ("usn", "USN"),
        ("meta-pool.near", "stNEAR"),
        ("aurora", "AURORA"),
    ]

    token_balances = []
    for token_contract, symbol in known_tokens:
        result = await view_call(token_contract, "ft_balance_of", {
            "account_id": dao_id,
        })
        if isinstance(result, str) and result != "0":
            metadata = await view_call(token_contract, "ft_metadata")
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


# ─── Slash Commands ───────────────────────────────────────────────

@bot.tree.command(name="proposals", description="List active DAO proposals")
@app_commands.describe(
    dao="DAO contract address (e.g. marketing-dao.sputnik-dao.near)",
    status="Filter by status",
    limit="Number of proposals to show (max 10)",
)
@app_commands.autocomplete(dao=dao_autocomplete)
@app_commands.choices(status=[
    app_commands.Choice(name="All", value="all"),
    app_commands.Choice(name="Active", value="active"),
    app_commands.Choice(name="Approved", value="approved"),
    app_commands.Choice(name="Rejected", value="rejected"),
    app_commands.Choice(name="Expired", value="expired"),
])
async def proposals_command(
    interaction: discord.Interaction,
    dao: str | None = None,
    status: str = "active",
    limit: int = 5,
):
    dao_id = resolve_dao(dao)
    if not dao_id:
        await interaction.response.send_message(
            "Specify a DAO: `/proposals dao:marketing-dao.sputnik-dao.near`\n"
            "Or set `DEFAULT_DAO_ID` in the bot's environment.",
            ephemeral=True,
        )
        return

    await interaction.response.defer()
    limit = max(1, min(limit, 10))

    data = await fetch_proposals(dao_id, status=status, limit=limit)

    if "error" in data:
        await interaction.followup.send(f"Error: {data['error']}")
        return

    proposals = data.get("proposals", [])
    if not proposals:
        await interaction.followup.send(
            f"No **{status}** proposals found on `{dao_id}`.\n"
            f"Total proposals ever: {data.get('last_proposal_id', 0)}"
        )
        return

    embeds = [proposal_embed(p, dao_id) for p in proposals[:10]]
    header = f"**{len(embeds)} {status.title()} Proposal{'s' if len(embeds) != 1 else ''} on `{dao_id}`**"
    await interaction.followup.send(header, embeds=embeds[:10])


@bot.tree.command(name="vote", description="Vote on a DAO proposal (generates near-cli command)")
@app_commands.describe(
    proposal_id="Proposal ID number",
    action="Vote action",
    dao="DAO contract address",
)
@app_commands.autocomplete(dao=dao_autocomplete, action=vote_autocomplete)
async def vote_command(
    interaction: discord.Interaction,
    proposal_id: int,
    action: str = "approve",
    dao: str | None = None,
):
    dao_id = resolve_dao(dao)
    if not dao_id:
        await interaction.response.send_message(
            "Specify a DAO: `/vote proposal_id:42 action:approve dao:marketing-dao.sputnik-dao.near`",
            ephemeral=True,
        )
        return

    vote_map = {
        "approve": "VoteApprove",
        "reject": "VoteReject",
        "remove": "VoteRemove",
    }

    if action not in vote_map:
        await interaction.response.send_message(
            f"Invalid action `{action}`. Use: approve, reject, remove.",
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    # Fetch the proposal to show what they're voting on
    proposal_data = await view_call(dao_id, "get_proposal", {"id": proposal_id})

    args = {"id": proposal_id, "action": vote_map[action]}
    signer = NEAR_ACCOUNT or "<your-account.near>"

    cli_cmd = (
        f"near call {dao_id} act_proposal "
        f"'{json.dumps(args)}' "
        f"--accountId {signer} --gas 200000000000000"
    )

    action_colors = {
        "approve": discord.Color.green(),
        "reject": discord.Color.red(),
        "remove": discord.Color.dark_red(),
    }

    embed = discord.Embed(
        title=f"Vote {action.title()} on Proposal #{proposal_id}",
        color=action_colors.get(action, discord.Color.blue()),
    )
    embed.add_field(name="DAO", value=f"`{dao_id}`", inline=True)
    embed.add_field(name="Action", value=vote_map[action], inline=True)
    embed.add_field(name="Gas", value="200 TGas", inline=True)

    # Show proposal info if we could fetch it
    if isinstance(proposal_data, dict) and "error" not in proposal_data:
        desc = (proposal_data.get("description", "") or "")[:200]
        if desc:
            embed.add_field(name="Proposal Description", value=desc, inline=False)

        p_status = proposal_data.get("status", "Unknown")
        embed.add_field(name="Current Status", value=STATUS_LABELS.get(p_status, p_status), inline=True)

        votes = proposal_data.get("votes", {})
        approve_n = sum(1 for v in votes.values() if v == "Approve")
        reject_n = sum(1 for v in votes.values() if v == "Reject")
        embed.add_field(name="Current Votes", value=f"Approve: {approve_n} | Reject: {reject_n}", inline=True)

    embed.add_field(
        name="Execute via near-cli",
        value=f"```bash\n{cli_cmd}\n```",
        inline=False,
    )
    embed.set_footer(text="You must be a council member to vote. Run the command above to submit your vote on-chain.")

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="propose", description="Create a new DAO proposal (generates near-cli command)")
@app_commands.describe(
    kind="Proposal type",
    description="Proposal description",
    receiver="Receiver account (for transfers and function calls)",
    amount="Amount in NEAR (for transfers)",
    member="Account ID (for add/remove member proposals)",
    dao="DAO contract address",
)
@app_commands.autocomplete(dao=dao_autocomplete, kind=proposal_kind_autocomplete)
async def propose_command(
    interaction: discord.Interaction,
    kind: str,
    description: str,
    receiver: str = "",
    amount: float = 0.0,
    member: str = "",
    dao: str | None = None,
):
    dao_id = resolve_dao(dao)
    if not dao_id:
        await interaction.response.send_message(
            "Specify a DAO: `/propose kind:transfer description:\"Fund project\" dao:marketing-dao.sputnik-dao.near`",
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    # Build the proposal kind payload
    kind_payload = {}
    if kind == "transfer":
        if not receiver:
            await interaction.followup.send("Transfer proposals require a `receiver` account.")
            return
        amount_yocto = str(int(amount * 1e24))
        kind_payload = {
            "Transfer": {
                "token_id": "",
                "receiver_id": receiver,
                "amount": amount_yocto,
            }
        }
    elif kind == "function_call":
        if not receiver:
            await interaction.followup.send("Function call proposals require a `receiver` contract.")
            return
        kind_payload = {
            "FunctionCall": {
                "receiver_id": receiver,
                "actions": [{
                    "method_name": "execute",
                    "args": base64.b64encode(b"{}").decode(),
                    "deposit": "0",
                    "gas": "150000000000000",
                }],
            }
        }
    elif kind == "vote":
        kind_payload = {"Vote": {}}
    elif kind == "add_member":
        if not member:
            await interaction.followup.send("Add member proposals require a `member` account ID.")
            return
        kind_payload = {
            "AddMemberToRole": {
                "member_id": member,
                "role": "council",
            }
        }
    elif kind == "remove_member":
        if not member:
            await interaction.followup.send("Remove member proposals require a `member` account ID.")
            return
        kind_payload = {
            "RemoveMemberFromRole": {
                "member_id": member,
                "role": "council",
            }
        }
    else:
        await interaction.followup.send(
            f"Unknown proposal kind `{kind}`. Use: transfer, function_call, vote, add_member, remove_member."
        )
        return

    # Get proposal bond from the DAO policy
    policy = await view_call(dao_id, "get_policy")
    bond = "100000000000000000000000"  # Default 0.1 NEAR
    if isinstance(policy, dict):
        bond = policy.get("proposal_bond", bond)
    bond_near = yocto_to_near(bond)

    args = {
        "proposal": {
            "description": description,
            "kind": kind_payload,
        }
    }

    signer = NEAR_ACCOUNT or "<your-account.near>"
    cli_cmd = (
        f"near call {dao_id} add_proposal "
        f"'{json.dumps(args)}' "
        f"--accountId {signer} --deposit {bond_near}"
    )

    embed = discord.Embed(
        title="New Proposal",
        description=description[:500],
        color=discord.Color.purple(),
    )
    embed.add_field(name="DAO", value=f"`{dao_id}`", inline=True)
    embed.add_field(name="Type", value=KIND_LABELS.get(list(kind_payload.keys())[0], kind), inline=True)
    embed.add_field(name="Bond Required", value=f"{format_near(bond_near)} NEAR", inline=True)

    if kind == "transfer":
        embed.add_field(name="Transfer", value=f"{amount} NEAR to `{receiver}`", inline=False)
    elif kind == "function_call":
        embed.add_field(name="Contract", value=f"`{receiver}`", inline=False)
    elif kind in ("add_member", "remove_member"):
        embed.add_field(name="Member", value=f"`{member}`", inline=True)
        embed.add_field(name="Role", value="council", inline=True)

    embed.add_field(
        name="Execute via near-cli",
        value=f"```bash\n{cli_cmd}\n```",
        inline=False,
    )
    embed.set_footer(text=f"Bond: {format_near(bond_near)} NEAR (refunded if approved). Execute the command above to submit on-chain.")

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="dao-info", description="Show DAO stats — members, treasury, proposal count")
@app_commands.describe(dao="DAO contract address")
@app_commands.autocomplete(dao=dao_autocomplete)
async def dao_info_command(
    interaction: discord.Interaction,
    dao: str | None = None,
):
    dao_id = resolve_dao(dao)
    if not dao_id:
        await interaction.response.send_message(
            "Specify a DAO: `/dao-info dao:marketing-dao.sputnik-dao.near`",
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    info = await fetch_dao_info(dao_id)
    if "error" in info:
        await interaction.followup.send(f"Error: {info['error']}")
        return

    embed = dao_info_embed(info)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="members", description="List DAO council members")
@app_commands.describe(dao="DAO contract address")
@app_commands.autocomplete(dao=dao_autocomplete)
async def members_command(
    interaction: discord.Interaction,
    dao: str | None = None,
):
    dao_id = resolve_dao(dao)
    if not dao_id:
        await interaction.response.send_message(
            "Specify a DAO: `/members dao:marketing-dao.sputnik-dao.near`",
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    policy = await view_call(dao_id, "get_policy")
    if not isinstance(policy, dict):
        await interaction.followup.send(f"Could not read policy for `{dao_id}`.")
        return

    embed = discord.Embed(
        title=f"Members: {dao_id}",
        color=discord.Color.teal(),
    )

    roles = policy.get("roles", [])
    for role in roles:
        role_name = role.get("name", "unknown")
        kind = role.get("kind", {})

        if isinstance(kind, dict) and "Group" in kind:
            members = kind["Group"]
            if not members:
                continue
            member_list = "\n".join(f"  `{m}`" for m in members[:25])
            if len(members) > 25:
                member_list += f"\n  ... and {len(members) - 25} more"
            embed.add_field(
                name=f"{role_name.title()} ({len(members)})",
                value=member_list,
                inline=False,
            )
        elif kind == "Everyone":
            perms = role.get("permissions", [])
            perm_str = ", ".join(perms[:5]) if perms else "none"
            if len(perms) > 5:
                perm_str += "..."
            embed.add_field(
                name=f"{role_name.title()} (public)",
                value=f"Open to everyone\nPermissions: {perm_str}",
                inline=False,
            )

    embed.set_footer(text=f"Sputnik DAO v2 | {dao_id}")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="treasury", description="View DAO treasury — NEAR balance and token holdings")
@app_commands.describe(dao="DAO contract address")
@app_commands.autocomplete(dao=dao_autocomplete)
async def treasury_command(
    interaction: discord.Interaction,
    dao: str | None = None,
):
    dao_id = resolve_dao(dao)
    if not dao_id:
        await interaction.response.send_message(
            "Specify a DAO: `/treasury dao:marketing-dao.sputnik-dao.near`",
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    data = await fetch_treasury(dao_id)
    if "error" in data:
        await interaction.followup.send(f"Error: {data['error']}")
        return

    embed = treasury_embed(data)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="proposal-detail", description="View a single proposal in detail")
@app_commands.describe(
    proposal_id="Proposal ID number",
    dao="DAO contract address",
)
@app_commands.autocomplete(dao=dao_autocomplete)
async def proposal_detail_command(
    interaction: discord.Interaction,
    proposal_id: int,
    dao: str | None = None,
):
    dao_id = resolve_dao(dao)
    if not dao_id:
        await interaction.response.send_message(
            "Specify a DAO: `/proposal-detail proposal_id:42 dao:marketing-dao.sputnik-dao.near`",
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    proposal = await view_call(dao_id, "get_proposal", {"id": proposal_id})

    if not isinstance(proposal, dict) or "error" in proposal:
        await interaction.followup.send(f"Proposal #{proposal_id} not found on `{dao_id}`.")
        return

    proposal["id"] = proposal_id
    embed = proposal_embed(proposal, dao_id)

    # Add voter breakdown
    votes = proposal.get("votes", {})
    if votes:
        voter_lines = []
        for voter, vote_val in list(votes.items())[:20]:
            icon = {"Approve": "Approve", "Reject": "Reject", "Remove": "Remove"}.get(vote_val, vote_val)
            voter_lines.append(f"  `{voter}` -- {icon}")
        if voter_lines:
            embed.add_field(name="Voter Breakdown", value="\n".join(voter_lines), inline=False)

    await interaction.followup.send(embed=embed)


# ─── Bot Events ───────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"Bot ready: {bot.user} (ID: {bot.user.id})")
    print(f"RPC: {NEAR_RPC}")
    if DEFAULT_DAO:
        print(f"Default DAO: {DEFAULT_DAO}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Sync error: {e}")


# ─── Entry Point ──────────────────────────────────────────────────

def main():
    if not DISCORD_TOKEN:
        print("ERROR: Set DISCORD_BOT_TOKEN environment variable")
        print("  export DISCORD_BOT_TOKEN=your-token-here")
        return
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
