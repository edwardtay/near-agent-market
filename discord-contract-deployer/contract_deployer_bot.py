#!/usr/bin/env python3
"""
NEAR Contract Deployer Discord Bot

Deploy, verify, and manage NEAR smart contracts directly from Discord.
Uses NEAR RPC API for on-chain operations.

Requires: discord.py, aiohttp, python-dotenv
Environment: DISCORD_BOT_TOKEN, NEAR_ACCOUNT_ID, NEAR_PRIVATE_KEY
"""

import asyncio
import base64
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# --- Config -----------------------------------------------------------------

DISCORD_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
NEAR_ACCOUNT_ID = os.environ.get("NEAR_ACCOUNT_ID", "")
NEAR_PRIVATE_KEY = os.environ.get("NEAR_PRIVATE_KEY", "")
NEAR_NETWORK = os.environ.get("NEAR_NETWORK", "testnet")

RPC_URLS = {
    "mainnet": "https://rpc.mainnet.near.org",
    "testnet": "https://rpc.testnet.near.org",
}
EXPLORER_URLS = {
    "mainnet": "https://nearblocks.io",
    "testnet": "https://testnet.nearblocks.io",
}

RPC_URL = RPC_URLS.get(NEAR_NETWORK, RPC_URLS["testnet"])
EXPLORER_URL = EXPLORER_URLS.get(NEAR_NETWORK, EXPLORER_URLS["testnet"])

DATA_DIR = Path(__file__).parent / "data"
DEPLOYMENTS_FILE = DATA_DIR / "deployments.json"
DATA_DIR.mkdir(exist_ok=True)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# --- Persistence ------------------------------------------------------------

def _load_deployments() -> dict:
    if DEPLOYMENTS_FILE.exists():
        try:
            return json.loads(DEPLOYMENTS_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def _save_deployments(data: dict):
    DEPLOYMENTS_FILE.write_text(json.dumps(data, indent=2))


def _record_deployment(
    user_id: str,
    contract_name: str,
    tx_hash: str,
    network: str,
    wasm_hash: str,
    status: str = "deployed",
):
    deployments = _load_deployments()
    key = f"{contract_name}@{network}"
    deployments[key] = {
        "contract_name": contract_name,
        "tx_hash": tx_hash,
        "network": network,
        "wasm_hash": wasm_hash,
        "status": status,
        "deployed_by": user_id,
        "deployed_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_deployments(deployments)


# --- NEAR RPC Client -------------------------------------------------------

async def rpc_call(method: str, params: dict | list) -> dict:
    """Send a JSON-RPC request to the NEAR RPC endpoint."""
    payload = {
        "jsonrpc": "2.0",
        "id": "deployer",
        "method": method,
        "params": params,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                RPC_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()
                return data
    except aiohttp.ClientError as exc:
        return {"error": {"message": str(exc)}}
    except asyncio.TimeoutError:
        return {"error": {"message": "RPC request timed out"}}


async def view_account(account_id: str) -> dict | None:
    """Fetch account info from NEAR RPC."""
    result = await rpc_call("query", {
        "request_type": "view_account",
        "finality": "final",
        "account_id": account_id,
    })
    if "error" in result:
        return None
    return result.get("result")


async def view_code(account_id: str) -> dict | None:
    """Fetch contract code metadata from NEAR RPC."""
    result = await rpc_call("query", {
        "request_type": "view_code",
        "finality": "final",
        "account_id": account_id,
    })
    if "error" in result:
        return None
    return result.get("result")


async def get_tx_status(tx_hash: str, sender_id: str) -> dict | None:
    """Query transaction status."""
    result = await rpc_call("tx", {
        "tx_hash": tx_hash,
        "sender_account_id": sender_id,
        "wait_until": "EXECUTED",
    })
    if "error" in result:
        return None
    return result.get("result")


async def download_wasm(url: str) -> bytes | None:
    """Download a WASM binary from a URL."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=60),
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                # Basic WASM magic number check: \x00asm
                if len(data) < 8 or data[:4] != b"\x00asm":
                    return None
                return data
    except Exception:
        return None


async def send_deploy_tx(account_id: str, wasm_bytes: bytes) -> dict:
    """
    Build and broadcast a DeployContract transaction via NEAR RPC.

    This constructs the transaction using the broadcast_tx_commit endpoint.
    In production you would sign the transaction locally with the private key;
    here we prepare the unsigned payload and use the RPC to broadcast.
    """
    # Get the current access key nonce and block hash
    access_key_resp = await rpc_call("query", {
        "request_type": "view_access_key",
        "finality": "final",
        "account_id": account_id,
        "public_key": _derive_public_key(),
    })

    if "error" in access_key_resp or "result" not in access_key_resp:
        return {
            "error": {
                "message": (
                    "Could not fetch access key. "
                    "Ensure NEAR_ACCOUNT_ID and NEAR_PRIVATE_KEY are configured."
                )
            }
        }

    ak_result = access_key_resp["result"]
    nonce = ak_result["nonce"] + 1
    block_hash = ak_result["block_hash"]

    # Encode the WASM as base64 for the deploy action
    wasm_b64 = base64.b64encode(wasm_bytes).decode("ascii")

    # Use broadcast_tx_async for large deploys; the caller polls status
    # For the bot we use the signed-transaction flow
    # NOTE: Full local signing requires ed25519 — we simulate via RPC helper
    return await _broadcast_deploy(account_id, nonce, block_hash, wasm_b64)


def _derive_public_key() -> str:
    """
    Derive the ed25519 public key from NEAR_PRIVATE_KEY.

    Expects the key in the format 'ed25519:<base58-encoded-key>' as used
    by NEAR CLI.  The first 32 bytes are the secret, the last 32 are
    the public key (for 64-byte combined keys), or the key is 32 bytes
    and the public part must be derived.
    """
    if not NEAR_PRIVATE_KEY:
        return ""
    # Placeholder — in production use the ed25519 library
    # Return configured public key if available
    pub = os.environ.get("NEAR_PUBLIC_KEY", "")
    return pub


async def _broadcast_deploy(
    account_id: str, nonce: int, block_hash: str, wasm_b64: str
) -> dict:
    """
    Broadcast a signed DeployContract transaction.

    Full local signing requires the `ed25519` or `py-near` library.
    This function prepares the transaction parameters and delegates
    to the RPC.  For a working deployment, install `py-near` and
    use its transaction builder, or call `near-cli` as a subprocess.
    """
    # Fallback: use near-cli subprocess for signing and sending
    import subprocess
    import shutil

    near_cli = shutil.which("near") or shutil.which("near-cli")
    if not near_cli:
        return {"error": {"message": "near-cli not found. Install with `npm i -g near-cli`."}}

    # Write wasm to temp file
    tmp_wasm = DATA_DIR / f"_deploy_{int(time.time())}.wasm"
    tmp_wasm.write_bytes(base64.b64decode(wasm_b64))

    try:
        env = os.environ.copy()
        cmd = [
            near_cli, "deploy",
            "--accountId", account_id,
            "--wasmFile", str(tmp_wasm),
            "--networkId", NEAR_NETWORK,
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, env=env,
        )
        if proc.returncode != 0:
            return {"error": {"message": proc.stderr or "near-cli deploy failed"}}

        # Try to extract tx hash from output
        tx_hash = _extract_tx_hash(proc.stdout)
        return {"result": {"tx_hash": tx_hash, "output": proc.stdout[-500:]}}
    except subprocess.TimeoutExpired:
        return {"error": {"message": "Deploy timed out after 120 seconds"}}
    except Exception as exc:
        return {"error": {"message": str(exc)}}
    finally:
        tmp_wasm.unlink(missing_ok=True)


def _extract_tx_hash(output: str) -> str:
    """Pull the transaction hash from near-cli output."""
    for line in output.splitlines():
        line = line.strip()
        # near-cli prints: Transaction Id <hash>
        if "transaction id" in line.lower():
            parts = line.split()
            for part in parts:
                if len(part) >= 40 and part.isalnum():
                    return part
        # Also check for raw base58 hashes on their own line
        if len(line) >= 43 and len(line) <= 44 and line.isalnum():
            return line
    return "unknown"


# --- Embeds -----------------------------------------------------------------

def deploy_progress_embed(stage: str, contract: str) -> discord.Embed:
    stages = {
        "downloading": ("Downloading WASM", discord.Color.blue()),
        "validating": ("Validating contract", discord.Color.blue()),
        "deploying": ("Deploying to NEAR", discord.Color.orange()),
        "success": ("Deployment successful", discord.Color.green()),
        "failed": ("Deployment failed", discord.Color.red()),
    }
    title, color = stages.get(stage, ("Processing", discord.Color.greyple()))
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Contract", value=f"`{contract}`", inline=True)
    embed.add_field(name="Network", value=NEAR_NETWORK, inline=True)
    return embed


def contract_info_embed(account_id: str, account: dict, code: dict | None) -> discord.Embed:
    balance_near = int(account.get("amount", "0")) / 1e24
    storage_bytes = account.get("storage_usage", 0)

    embed = discord.Embed(
        title=f"Contract: {account_id}",
        color=discord.Color.green() if code else discord.Color.greyple(),
        url=f"{EXPLORER_URL}/address/{account_id}",
    )
    embed.add_field(name="Balance", value=f"{balance_near:.4f} NEAR", inline=True)
    embed.add_field(name="Storage", value=f"{storage_bytes:,} bytes", inline=True)
    embed.add_field(
        name="Has Contract",
        value="Yes" if code and code.get("code_base64") else "No",
        inline=True,
    )

    if code and code.get("hash"):
        embed.add_field(name="Code Hash", value=f"`{code['hash'][:16]}...`", inline=False)

    embed.set_footer(text=f"Network: {NEAR_NETWORK}")
    return embed


def deployment_record_embed(record: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"Deployment: {record['contract_name']}",
        color=discord.Color.green() if record["status"] == "deployed" else discord.Color.red(),
    )
    embed.add_field(name="Network", value=record["network"], inline=True)
    embed.add_field(name="Status", value=record["status"].upper(), inline=True)
    embed.add_field(name="Deployed At", value=record["deployed_at"][:19], inline=True)
    if record.get("tx_hash") and record["tx_hash"] != "unknown":
        embed.add_field(
            name="Transaction",
            value=f"[View on Explorer]({EXPLORER_URL}/txns/{record['tx_hash']})",
            inline=False,
        )
    if record.get("wasm_hash"):
        embed.add_field(name="WASM Hash", value=f"`{record['wasm_hash'][:16]}...`", inline=False)
    return embed


def help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="NEAR Contract Deployer",
        description="Deploy and manage NEAR smart contracts from Discord.",
        color=discord.Color.dark_teal(),
    )
    embed.add_field(
        name="/deploy",
        value=(
            "Deploy a compiled WASM contract to NEAR.\n"
            "Provide the target account and a URL to the `.wasm` file."
        ),
        inline=False,
    )
    embed.add_field(
        name="/status",
        value="Check the status of a deployed contract or a deployment transaction.",
        inline=False,
    )
    embed.add_field(
        name="/view",
        value="Call a read-only view method on a contract and display the result.",
        inline=False,
    )
    embed.add_field(
        name="/call",
        value="Generate a near-cli command for a state-changing contract method call.",
        inline=False,
    )
    embed.add_field(
        name="/contracts",
        value="List all contracts deployed through this bot.",
        inline=False,
    )
    embed.add_field(
        name="/verify",
        value="Verify that a contract's on-chain code matches a known WASM binary.",
        inline=False,
    )
    embed.add_field(
        name="Deployment Workflow",
        value=(
            "1. Compile your contract: `cargo build --target wasm32-unknown-unknown --release`\n"
            "2. Host the `.wasm` file (GitHub release, IPFS, direct URL)\n"
            "3. Run `/deploy` with the contract account and WASM URL\n"
            "4. Confirm the deployment with `/status`\n"
            "5. Verify integrity with `/verify`"
        ),
        inline=False,
    )
    embed.set_footer(text=f"Network: {NEAR_NETWORK} | RPC: {RPC_URL}")
    return embed


# --- Slash Commands ---------------------------------------------------------

@bot.tree.command(name="deploy", description="Deploy a WASM contract to NEAR")
@app_commands.describe(
    contract_account="NEAR account to deploy to (e.g. myapp.testnet)",
    wasm_url="URL to the compiled .wasm file",
)
async def deploy_command(
    interaction: discord.Interaction,
    contract_account: str,
    wasm_url: str,
):
    await interaction.response.defer()

    # Validate account name
    if not contract_account or len(contract_account) < 2:
        await interaction.followup.send(
            embed=discord.Embed(
                title="Invalid account",
                description="Provide a valid NEAR account ID (e.g. `myapp.testnet`).",
                color=discord.Color.red(),
            )
        )
        return

    # Validate URL
    if not wasm_url.startswith(("http://", "https://")):
        await interaction.followup.send(
            embed=discord.Embed(
                title="Invalid URL",
                description="The WASM URL must start with `http://` or `https://`.",
                color=discord.Color.red(),
            )
        )
        return

    user_id = str(interaction.user.id)

    # Stage 1: Download
    progress = deploy_progress_embed("downloading", contract_account)
    msg = await interaction.followup.send(embed=progress)

    wasm_bytes = await download_wasm(wasm_url)
    if wasm_bytes is None:
        fail = deploy_progress_embed("failed", contract_account)
        fail.add_field(
            name="Error",
            value="Could not download WASM file. Check the URL and ensure it points to a valid `.wasm` binary.",
            inline=False,
        )
        await msg.edit(embed=fail)
        return

    wasm_hash = hashlib.sha256(wasm_bytes).hexdigest()
    wasm_size_kb = len(wasm_bytes) / 1024

    # Stage 2: Validate
    progress = deploy_progress_embed("validating", contract_account)
    progress.add_field(name="WASM Size", value=f"{wasm_size_kb:.1f} KB", inline=True)
    progress.add_field(name="SHA-256", value=f"`{wasm_hash[:16]}...`", inline=True)
    await msg.edit(embed=progress)

    # Size sanity check (NEAR max is ~4MB for contract code)
    if len(wasm_bytes) > 4 * 1024 * 1024:
        fail = deploy_progress_embed("failed", contract_account)
        fail.add_field(
            name="Error",
            value=f"WASM file is too large ({wasm_size_kb:.0f} KB). NEAR contracts must be under 4 MB.",
            inline=False,
        )
        await msg.edit(embed=fail)
        return

    # Stage 3: Deploy
    progress = deploy_progress_embed("deploying", contract_account)
    progress.add_field(name="WASM Size", value=f"{wasm_size_kb:.1f} KB", inline=True)
    progress.add_field(name="SHA-256", value=f"`{wasm_hash[:16]}...`", inline=True)
    await msg.edit(embed=progress)

    deploy_result = await send_deploy_tx(contract_account, wasm_bytes)

    if "error" in deploy_result:
        err_msg = deploy_result["error"].get("message", "Unknown error")
        fail = deploy_progress_embed("failed", contract_account)
        fail.add_field(name="Error", value=err_msg[:1024], inline=False)
        await msg.edit(embed=fail)
        _record_deployment(user_id, contract_account, "", NEAR_NETWORK, wasm_hash, "failed")
        return

    # Stage 4: Success
    tx_hash = deploy_result.get("result", {}).get("tx_hash", "unknown")

    success = deploy_progress_embed("success", contract_account)
    success.add_field(name="WASM Size", value=f"{wasm_size_kb:.1f} KB", inline=True)
    success.add_field(name="SHA-256", value=f"`{wasm_hash[:16]}...`", inline=True)
    if tx_hash != "unknown":
        success.add_field(
            name="Transaction",
            value=f"[View on Explorer]({EXPLORER_URL}/txns/{tx_hash})",
            inline=False,
        )
    success.set_footer(text=f"Deployed by {interaction.user.display_name} | {NEAR_NETWORK}")
    await msg.edit(embed=success)

    _record_deployment(user_id, contract_account, tx_hash, NEAR_NETWORK, wasm_hash, "deployed")


@bot.tree.command(name="status", description="Check contract or transaction status")
@app_commands.describe(
    contract_account="NEAR account ID of the contract",
    tx_hash="(Optional) Transaction hash to check",
)
async def status_command(
    interaction: discord.Interaction,
    contract_account: str,
    tx_hash: str | None = None,
):
    await interaction.response.defer()

    # If a tx hash was given, look up the transaction
    if tx_hash:
        tx_result = await get_tx_status(tx_hash, contract_account)
        if tx_result is None:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Transaction not found",
                    description=f"Could not find transaction `{tx_hash}` for `{contract_account}`.",
                    color=discord.Color.red(),
                )
            )
            return

        status_val = tx_result.get("status", {})
        if isinstance(status_val, dict) and "SuccessValue" in status_val:
            outcome = "Success"
            color = discord.Color.green()
        elif isinstance(status_val, dict) and "Failure" in status_val:
            outcome = "Failed"
            color = discord.Color.red()
        else:
            outcome = "Unknown"
            color = discord.Color.greyple()

        embed = discord.Embed(title="Transaction Status", color=color)
        embed.add_field(name="Hash", value=f"`{tx_hash[:20]}...`", inline=False)
        embed.add_field(name="Signer", value=f"`{contract_account}`", inline=True)
        embed.add_field(name="Outcome", value=outcome, inline=True)
        embed.add_field(
            name="Explorer",
            value=f"[View]({EXPLORER_URL}/txns/{tx_hash})",
            inline=False,
        )
        await interaction.followup.send(embed=embed)
        return

    # Otherwise look up the account / contract state
    account = await view_account(contract_account)
    if account is None:
        await interaction.followup.send(
            embed=discord.Embed(
                title="Account not found",
                description=f"`{contract_account}` does not exist on {NEAR_NETWORK}.",
                color=discord.Color.red(),
            )
        )
        return

    code = await view_code(contract_account)
    embed = contract_info_embed(contract_account, account, code)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="contracts", description="List contracts deployed through this bot")
@app_commands.describe(
    show_all="Show contracts from all users (default: your own)",
)
async def contracts_command(
    interaction: discord.Interaction,
    show_all: bool = False,
):
    await interaction.response.defer()
    deployments = _load_deployments()

    if not deployments:
        await interaction.followup.send(
            embed=discord.Embed(
                title="No deployments",
                description="No contracts have been deployed through this bot yet.\nUse `/deploy` to get started.",
                color=discord.Color.greyple(),
            )
        )
        return

    user_id = str(interaction.user.id)
    records = list(deployments.values())

    if not show_all:
        records = [r for r in records if r.get("deployed_by") == user_id]

    if not records:
        await interaction.followup.send(
            embed=discord.Embed(
                title="No deployments found",
                description="You haven't deployed any contracts yet. Use `/deploy` to deploy one.",
                color=discord.Color.greyple(),
            )
        )
        return

    # Sort newest first
    records.sort(key=lambda r: r.get("deployed_at", ""), reverse=True)

    embeds = [deployment_record_embed(r) for r in records[:10]]
    label = "All Deployments" if show_all else "Your Deployments"
    await interaction.followup.send(
        f"**{label} ({len(records)} total):**",
        embeds=embeds[:10],
    )


@bot.tree.command(name="verify", description="Verify on-chain contract code against a WASM file")
@app_commands.describe(
    contract_account="NEAR account ID of the deployed contract",
    wasm_url="URL to the original .wasm file to compare against",
)
async def verify_command(
    interaction: discord.Interaction,
    contract_account: str,
    wasm_url: str,
):
    await interaction.response.defer()

    # Fetch on-chain code
    code = await view_code(contract_account)
    if code is None or not code.get("code_base64"):
        await interaction.followup.send(
            embed=discord.Embed(
                title="No contract found",
                description=f"`{contract_account}` has no deployed contract on {NEAR_NETWORK}.",
                color=discord.Color.red(),
            )
        )
        return

    # Download reference WASM
    ref_wasm = await download_wasm(wasm_url)
    if ref_wasm is None:
        await interaction.followup.send(
            embed=discord.Embed(
                title="Download failed",
                description="Could not download the reference WASM file. Check the URL.",
                color=discord.Color.red(),
            )
        )
        return

    # Compare hashes
    on_chain_bytes = base64.b64decode(code["code_base64"])
    on_chain_hash = hashlib.sha256(on_chain_bytes).hexdigest()
    ref_hash = hashlib.sha256(ref_wasm).hexdigest()
    match = on_chain_hash == ref_hash

    embed = discord.Embed(
        title="Verification Result",
        color=discord.Color.green() if match else discord.Color.red(),
    )
    embed.add_field(name="Contract", value=f"`{contract_account}`", inline=True)
    embed.add_field(name="Network", value=NEAR_NETWORK, inline=True)
    embed.add_field(
        name="Result",
        value="MATCH - Code is identical" if match else "MISMATCH - Code differs",
        inline=False,
    )
    embed.add_field(name="On-chain Hash", value=f"`{on_chain_hash[:32]}...`", inline=False)
    embed.add_field(name="Reference Hash", value=f"`{ref_hash[:32]}...`", inline=False)
    embed.add_field(
        name="On-chain Size",
        value=f"{len(on_chain_bytes) / 1024:.1f} KB",
        inline=True,
    )
    embed.add_field(
        name="Reference Size",
        value=f"{len(ref_wasm) / 1024:.1f} KB",
        inline=True,
    )

    if not match:
        embed.set_footer(
            text="The on-chain code does not match the provided WASM. "
                 "This could indicate a different build or version."
        )

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="view", description="Call a read-only view method on a NEAR contract")
@app_commands.describe(
    contract_account="NEAR account ID of the contract",
    method="View method name to call",
    args="JSON arguments (default: {})",
)
async def view_command(
    interaction: discord.Interaction,
    contract_account: str,
    method: str,
    args: str = "{}",
):
    await interaction.response.defer()

    # Parse JSON args
    try:
        parsed_args = json.loads(args)
    except json.JSONDecodeError:
        await interaction.followup.send(
            embed=discord.Embed(
                title="Invalid JSON",
                description="The `args` parameter must be valid JSON (e.g. `{\"account_id\": \"alice.near\"}`).",
                color=discord.Color.red(),
            )
        )
        return

    # Encode args as base64
    args_b64 = base64.b64encode(json.dumps(parsed_args).encode()).decode()

    result = await rpc_call("query", {
        "request_type": "call_function",
        "finality": "final",
        "account_id": contract_account,
        "method_name": method,
        "args_base64": args_b64,
    })

    if "error" in result:
        err_msg = result["error"].get("message", "Unknown error")
        if isinstance(err_msg, dict):
            err_msg = json.dumps(err_msg, indent=2)[:1000]
        await interaction.followup.send(
            embed=discord.Embed(
                title="View call failed",
                description=f"```\n{str(err_msg)[:1000]}\n```",
                color=discord.Color.red(),
            )
        )
        return

    # Decode the result bytes
    result_data = result.get("result", {})
    raw_result = result_data.get("result", [])
    if isinstance(raw_result, list):
        try:
            decoded = bytes(raw_result).decode("utf-8")
            try:
                parsed = json.loads(decoded)
                display = json.dumps(parsed, indent=2)
            except json.JSONDecodeError:
                display = decoded
        except (UnicodeDecodeError, ValueError):
            display = str(raw_result)
    else:
        display = str(raw_result)

    # Truncate long output
    if len(display) > 3800:
        display = display[:3800] + "\n... (truncated)"

    embed = discord.Embed(
        title=f"View: {contract_account}.{method}()",
        color=discord.Color.green(),
    )
    embed.add_field(name="Contract", value=f"`{contract_account}`", inline=True)
    embed.add_field(name="Method", value=f"`{method}`", inline=True)
    embed.add_field(name="Network", value=NEAR_NETWORK, inline=True)
    if parsed_args:
        args_display = json.dumps(parsed_args, indent=2)
        if len(args_display) > 500:
            args_display = args_display[:500] + "..."
        embed.add_field(name="Arguments", value=f"```json\n{args_display}\n```", inline=False)
    embed.add_field(name="Result", value=f"```json\n{display}\n```", inline=False)

    logs = result_data.get("logs", [])
    if logs:
        log_text = "\n".join(logs[:10])
        embed.add_field(name="Logs", value=f"```\n{log_text[:500]}\n```", inline=False)

    embed.set_footer(text=f"Network: {NEAR_NETWORK}")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="call", description="Generate a near-cli command for a contract method call")
@app_commands.describe(
    contract_account="NEAR account ID of the contract",
    method="Method name to call",
    args="JSON arguments (default: {})",
    gas="Gas in TGas (default: 30)",
    deposit="Deposit in NEAR (default: 0)",
)
async def call_command(
    interaction: discord.Interaction,
    contract_account: str,
    method: str,
    args: str = "{}",
    gas: int = 30,
    deposit: float = 0.0,
):
    await interaction.response.defer()

    # Parse JSON args
    try:
        parsed_args = json.loads(args)
    except json.JSONDecodeError:
        await interaction.followup.send(
            embed=discord.Embed(
                title="Invalid JSON",
                description="The `args` parameter must be valid JSON (e.g. `{\"key\": \"value\"}`).",
                color=discord.Color.red(),
            )
        )
        return

    signer = NEAR_ACCOUNT_ID or "<your-account.near>"
    gas_yocto = str(gas * 10**12)

    if deposit > 0:
        deposit_str = str(deposit)
        cli_cmd = (
            f"near call {contract_account} {method} "
            f"'{json.dumps(parsed_args)}' "
            f"--accountId {signer} --gas {gas_yocto} --deposit {deposit_str}"
        )
    else:
        cli_cmd = (
            f"near call {contract_account} {method} "
            f"'{json.dumps(parsed_args)}' "
            f"--accountId {signer} --gas {gas_yocto}"
        )

    embed = discord.Embed(
        title=f"Call: {contract_account}.{method}()",
        description="This is a state-changing transaction. Run the command below with near-cli to execute it.",
        color=discord.Color.orange(),
    )
    embed.add_field(name="Contract", value=f"`{contract_account}`", inline=True)
    embed.add_field(name="Method", value=f"`{method}`", inline=True)
    embed.add_field(name="Network", value=NEAR_NETWORK, inline=True)
    embed.add_field(name="Gas", value=f"{gas} TGas", inline=True)
    if deposit > 0:
        embed.add_field(name="Deposit", value=f"{deposit} NEAR", inline=True)

    if parsed_args:
        args_display = json.dumps(parsed_args, indent=2)
        if len(args_display) > 500:
            args_display = args_display[:500] + "..."
        embed.add_field(name="Arguments", value=f"```json\n{args_display}\n```", inline=False)

    embed.add_field(
        name="Execute via near-cli",
        value=f"```bash\n{cli_cmd}\n```",
        inline=False,
    )
    embed.set_footer(
        text=f"Network: {NEAR_NETWORK} | Run this command in your terminal with near-cli installed."
    )

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="deployer-help", description="Show contract deployer help and workflow guide")
async def deployer_help_command(interaction: discord.Interaction):
    await interaction.response.send_message(embed=help_embed())


# --- Bot Events -------------------------------------------------------------

@bot.event
async def on_ready():
    print(f"Contract Deployer Bot ready: {bot.user} (ID: {bot.user.id})")
    print(f"Network: {NEAR_NETWORK} | RPC: {RPC_URL}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Sync error: {e}")


# --- Entry Point ------------------------------------------------------------

def main():
    if not DISCORD_TOKEN:
        print("ERROR: Set DISCORD_BOT_TOKEN environment variable")
        print("  export DISCORD_BOT_TOKEN=your_token_here")
        return
    if not NEAR_ACCOUNT_ID:
        print("WARNING: NEAR_ACCOUNT_ID not set. Deploy commands will fail.")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
