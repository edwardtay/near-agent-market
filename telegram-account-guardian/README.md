# NEAR Account Guardian — Telegram Bot

Monitors NEAR accounts and sends Telegram alerts for balance changes, new transactions, and staking activity. Works with both mainnet and testnet accounts.

## Setup

```bash
pip install -r requirements.txt
```

Set environment variables:
```bash
export TG_BOT_TOKEN="your-telegram-bot-token"
export NEAR_ACCOUNT_ID="alice.near"        # optional default account
export POLL_INTERVAL="60"                  # seconds between checks (default: 60)
```

## Run

```bash
python account_guardian.py
```

## Commands

- `/start` — Welcome message and usage guide
- `/watch <account_id>` — Start monitoring a NEAR account (auto-detects mainnet/testnet)
- `/balance [account_id]` — Current balance, storage, access keys, and contract status
- `/alerts` — Show active monitoring configuration
- `/history [account_id]` — Recent transaction history with direction and timestamps

## Monitored Events

The bot polls the watched account and sends alerts when it detects:

- **Balance changes** greater than 0.01 NEAR (incoming or outgoing)
- **Access key changes** — keys added or removed (potential security event)
- **Staking changes** — locked balance increases or decreases

## Architecture

Single-file Python bot using `python-telegram-bot` with an async background monitor loop. State is persisted to a local `data/watchers.json` file — each Telegram chat can watch one account.

NEAR data is fetched via:
- **NEAR JSON-RPC** (`rpc.mainnet.near.org` / `rpc.testnet.near.org`) for account info, access keys, and validators
- **NearBlocks API** for transaction history

## Telegram Bot Setup

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the bot token and set it as `TG_BOT_TOKEN`
4. Start a chat with your bot and send `/start`
