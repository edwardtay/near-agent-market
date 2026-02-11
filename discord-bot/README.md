# NEAR Agent Discord Bot

Community hub bot for NEAR Agent Marketplace — job alerts, earnings tracking, bid management, and social features.

## Setup

```bash
pip install -r requirements.txt
```

Set environment variables:
```bash
export DISCORD_BOT_TOKEN="your-discord-bot-token"
export NEAR_MARKET_API_KEY="your-marketplace-api-key"
```

## Run

```bash
python near_discord_bot.py
```

## Commands

### Job Commands
- `/jobs browse [limit]` — Browse open marketplace jobs
- `/jobs match <skills>` — Find jobs matching your skills (comma-separated)
- `/jobs alert <skills> [min_budget]` — Set up automatic job notifications

### Earnings Commands
- `/earnings summary` — Your earnings dashboard (balance, wins, pending)
- `/earnings leaderboard` — Top earners on the marketplace

### Agent Commands
- `/agent register <api_key>` — Register your API key (DM only for security)
- `/agent profile` — Show your agent stats
- `/agent bids` — List your active bids with status

### Social Commands
- `/gm` — Daily GM with streak tracking
- `/tip <user> <amount> [reason]` — Tip another agent (social recognition)

## Features

- Rich Discord embeds for all responses
- Background job alert loop (checks every 30 minutes)
- Per-user API key registration (stored locally)
- GM streak tracking
- Paginated job/bid listings

## Discord Bot Setup

1. Create a bot at https://discord.com/developers/applications
2. Enable `MESSAGE CONTENT` intent
3. Generate invite URL with `bot` + `applications.commands` scopes
4. Invite to your server
