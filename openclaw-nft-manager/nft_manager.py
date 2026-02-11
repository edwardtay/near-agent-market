#!/usr/bin/env python3
"""
OpenClaw Skill: NEAR NFT Manager

Manage NEAR NFTs — view collections, get metadata, transfer,
mint, and browse marketplace listings.

Commands:
    near_nft_owned       — List NFTs owned by an account
    near_nft_details     — Get NFT metadata and history
    near_nft_transfer    — Transfer an NFT (build transaction)
    near_nft_mint        — Mint a new NFT
    near_nft_collections — List popular NEAR NFT collections
    near_nft_marketplace — Browse marketplace listings

Environment:
    NEAR_ACCOUNT_ID  — Your NEAR account
    NEAR_RPC_URL     — RPC endpoint (default: mainnet)

Uses NEP-171 standard (nft_token, nft_tokens_for_owner, nft_transfer, nft_mint).
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

# Well-known NEAR NFT contracts
KNOWN_COLLECTIONS = [
    {
        "name": "Paras",
        "contract": "x.paras.near",
        "description": "Digital art marketplace on NEAR",
        "website": "https://paras.id",
    },
    {
        "name": "Mintbase",
        "contract": "mintbase1.near",
        "description": "NFT infrastructure and marketplace",
        "website": "https://mintbase.xyz",
    },
    {
        "name": "Few and Far",
        "contract": "fewandfar.near",
        "description": "Curated NFT marketplace",
        "website": "https://fewandfar.xyz",
    },
    {
        "name": "Nearton",
        "contract": "nearton.near",
        "description": "Metaverse NFTs on NEAR",
        "website": "https://nearton.app",
    },
    {
        "name": "Antisocial Ape Club",
        "contract": "asac.near",
        "description": "PFP collection on NEAR",
        "website": "https://antisocialapeclub.com",
    },
    {
        "name": "NEARNauts",
        "contract": "nearnauts.near",
        "description": "Space explorer PFP collection",
        "website": "https://nearnauts.io",
    },
    {
        "name": "NEAR Misfits",
        "contract": "nearmisfits.near",
        "description": "Community PFP collection",
        "website": "",
    },
    {
        "name": "Tenk DAO",
        "contract": "tenk.near",
        "description": "10k PFP generator platform",
        "website": "https://tenk.dev",
    },
]


# ─── NEAR RPC Client ──────────────────────────────────────────────

def rpc_call(method: str, params: dict) -> dict:
    """Make a NEAR JSON-RPC call."""
    payload = {
        "jsonrpc": "2.0",
        "id": "nft-manager",
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


def view_call(contract: str, method: str, args: dict | None = None) -> dict | list | None:
    """Call a view method on a NEAR contract and decode result."""
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

    # Decode result bytes
    result_bytes = result.get("result", [])
    if isinstance(result_bytes, list):
        try:
            decoded = bytes(result_bytes).decode("utf-8")
            return json.loads(decoded)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"raw": decoded if 'decoded' in dir() else str(result_bytes)}

    return result


# ─── Skill Commands ───────────────────────────────────────────────

def near_nft_owned(account_id: str | None = None, contracts: list | None = None,
                   limit: int = 50) -> dict:
    """List NFTs owned by an account.

    Args:
        account_id: NEAR account to check (defaults to NEAR_ACCOUNT_ID)
        contracts: List of NFT contract addresses to query
        limit: Max NFTs per contract

    Returns:
        Dict with owned NFTs grouped by contract
    """
    account = account_id or NEAR_ACCOUNT
    if not account:
        return {"error": "No account_id specified. Set NEAR_ACCOUNT_ID or pass account_id."}

    check_contracts = contracts or [c["contract"] for c in KNOWN_COLLECTIONS]
    all_nfts = []

    for contract in check_contracts:
        result = view_call(contract, "nft_tokens_for_owner", {
            "account_id": account,
            "from_index": "0",
            "limit": limit,
        })

        if isinstance(result, list):
            for nft in result:
                metadata = nft.get("metadata", {})
                all_nfts.append({
                    "contract": contract,
                    "token_id": nft.get("token_id", ""),
                    "owner": nft.get("owner_id", account),
                    "title": metadata.get("title", "Untitled"),
                    "description": (metadata.get("description") or "")[:200],
                    "media": metadata.get("media", ""),
                    "copies": metadata.get("copies"),
                })

    return {
        "account": account,
        "nfts": all_nfts,
        "total": len(all_nfts),
        "contracts_checked": len(check_contracts),
    }


def near_nft_details(contract: str, token_id: str) -> dict:
    """Get NFT metadata and details.

    Args:
        contract: NFT contract address
        token_id: Token ID

    Returns:
        Dict with full NFT metadata
    """
    result = view_call(contract, "nft_token", {"token_id": token_id})

    if not result or "error" in result:
        return {"error": f"NFT not found: {contract}:{token_id}", "details": result}

    metadata = result.get("metadata", {})
    return {
        "contract": contract,
        "token_id": result.get("token_id", token_id),
        "owner": result.get("owner_id", ""),
        "title": metadata.get("title", "Untitled"),
        "description": metadata.get("description", ""),
        "media": metadata.get("media", ""),
        "media_hash": metadata.get("media_hash"),
        "copies": metadata.get("copies"),
        "issued_at": metadata.get("issued_at"),
        "expires_at": metadata.get("expires_at"),
        "reference": metadata.get("reference", ""),
        "extra": metadata.get("extra", ""),
        "approved_account_ids": result.get("approved_account_ids", {}),
    }


def near_nft_transfer(contract: str, token_id: str, receiver_id: str,
                      memo: str = "") -> dict:
    """Build an NFT transfer transaction (NEP-171 nft_transfer).

    Note: Actual execution requires signing. This returns the transaction
    parameters for use with near-cli or a wallet.

    Args:
        contract: NFT contract address
        token_id: Token ID to transfer
        receiver_id: Receiving NEAR account
        memo: Optional transfer memo

    Returns:
        Dict with transaction parameters
    """
    if not receiver_id:
        return {"error": "receiver_id is required"}

    args = {
        "receiver_id": receiver_id,
        "token_id": token_id,
    }
    if memo:
        args["memo"] = memo

    return {
        "action": "nft_transfer",
        "contract": contract,
        "method": "nft_transfer",
        "args": args,
        "deposit": "1",  # 1 yoctoNEAR required for transfer
        "gas": "30000000000000",  # 30 TGas
        "near_cli": (
            f'near call {contract} nft_transfer '
            f'\'{json.dumps(args)}\' '
            f'--accountId {NEAR_ACCOUNT} --depositYocto 1'
        ),
        "note": "Execute this transaction via near-cli or your wallet to complete the transfer.",
    }


def near_nft_mint(contract: str, token_id: str | None = None,
                  title: str = "", description: str = "",
                  media: str = "", receiver_id: str | None = None) -> dict:
    """Build an NFT mint transaction.

    Note: Only works on contracts that support public minting.
    Actual execution requires signing.

    Args:
        contract: NFT contract address
        token_id: Token ID (auto-generated if not provided)
        title: NFT title
        description: NFT description
        media: Media URL (IPFS or HTTP)
        receiver_id: Mint to this account (defaults to self)

    Returns:
        Dict with mint transaction parameters
    """
    import uuid as _uuid
    tid = token_id or str(_uuid.uuid4())[:8]
    receiver = receiver_id or NEAR_ACCOUNT

    args = {
        "token_id": tid,
        "receiver_id": receiver,
        "token_metadata": {
            "title": title or f"NFT #{tid}",
            "description": description,
            "media": media,
            "copies": 1,
        },
    }

    return {
        "action": "nft_mint",
        "contract": contract,
        "method": "nft_mint",
        "args": args,
        "deposit": "10000000000000000000000",  # 0.01 NEAR for storage
        "gas": "30000000000000",
        "near_cli": (
            f'near call {contract} nft_mint '
            f'\'{json.dumps(args)}\' '
            f'--accountId {NEAR_ACCOUNT} --deposit 0.01'
        ),
        "note": "Execute via near-cli or wallet. Contract must support public minting.",
    }


def near_nft_collections() -> dict:
    """List popular NEAR NFT collections with live supply data.

    Returns:
        Dict with collection info and supply counts
    """
    collections = []
    for col in KNOWN_COLLECTIONS:
        entry = {**col}

        # Try to get supply
        result = view_call(col["contract"], "nft_total_supply", {})
        if isinstance(result, str):
            entry["total_supply"] = int(result)
        elif isinstance(result, int):
            entry["total_supply"] = result
        else:
            entry["total_supply"] = "unknown"

        collections.append(entry)

    return {
        "collections": collections,
        "total": len(collections),
    }


def near_nft_marketplace(contract: str | None = None,
                         limit: int = 10) -> dict:
    """Browse NFT marketplace listings.

    Args:
        contract: Filter by contract (or browse all known)
        limit: Max listings to return

    Returns:
        Dict with marketplace listings
    """
    # Query Paras marketplace API for listings
    listings = []

    if contract:
        # Get recent tokens from specific contract
        result = view_call(contract, "nft_tokens", {
            "from_index": "0",
            "limit": limit,
        })

        if isinstance(result, list):
            for nft in result:
                metadata = nft.get("metadata", {})
                listings.append({
                    "contract": contract,
                    "token_id": nft.get("token_id", ""),
                    "owner": nft.get("owner_id", ""),
                    "title": metadata.get("title", "Untitled"),
                    "media": metadata.get("media", ""),
                })
    else:
        # Browse multiple collections
        for col in KNOWN_COLLECTIONS[:3]:
            result = view_call(col["contract"], "nft_tokens", {
                "from_index": "0",
                "limit": min(limit, 5),
            })
            if isinstance(result, list):
                for nft in result:
                    metadata = nft.get("metadata", {})
                    listings.append({
                        "contract": col["contract"],
                        "collection": col["name"],
                        "token_id": nft.get("token_id", ""),
                        "owner": nft.get("owner_id", ""),
                        "title": metadata.get("title", "Untitled"),
                        "media": metadata.get("media", ""),
                    })

    return {
        "listings": listings[:limit],
        "total": len(listings),
    }


# ─── CLI ───────────────────────────────────────────────────────────

def main():
    commands = {
        "owned": ("near_nft_owned", near_nft_owned),
        "details": ("near_nft_details", near_nft_details),
        "transfer": ("near_nft_transfer", near_nft_transfer),
        "mint": ("near_nft_mint", near_nft_mint),
        "collections": ("near_nft_collections", near_nft_collections),
        "marketplace": ("near_nft_marketplace", near_nft_marketplace),
    }

    if len(sys.argv) < 2:
        print("NEAR NFT Manager Skill")
        print(f"\nCommands: {', '.join(commands.keys())}")
        print(f"\nUsage: python {sys.argv[0]} <command> [json_kwargs]")
        print(f"\nExamples:")
        print(f'  python {sys.argv[0]} owned \'{{"account_id": "alice.near"}}\'')
        print(f'  python {sys.argv[0]} details \'{{"contract": "x.paras.near", "token_id": "1"}}\'')
        print(f'  python {sys.argv[0]} collections')
        print(f'  python {sys.argv[0]} marketplace \'{{"limit": 5}}\'')
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
