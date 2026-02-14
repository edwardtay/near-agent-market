# NEAR DAO Helper — Discord Bot

Discord bot for NEAR Sputnik DAO v2 governance. Browse proposals, vote, create proposals, inspect treasury, and list council members directly from Discord.

## Setup

### 1. Create a Discord Bot

1. Go to https://discord.com/developers/applications
2. Create a new application and add a bot
3. Enable the **Message Content** intent under Bot settings
4. Generate an invite URL with `bot` and `applications.commands` scopes
5. Invite the bot to your server

### 2. Environment Variables

Create a `.env` file:

```
DISCORD_BOT_TOKEN=your-discord-bot-token
NEAR_ACCOUNT_ID=your-account.near
NEAR_RPC_URL=https://rpc.mainnet.near.org
DEFAULT_DAO_ID=marketing-dao.sputnik-dao.near
```

| Variable | Required | Description |
|---|---|---|
| `DISCORD_BOT_TOKEN` | Yes | Discord bot token |
| `NEAR_ACCOUNT_ID` | No | Your NEAR account (used in generated CLI commands) |
| `NEAR_RPC_URL` | No | RPC endpoint, defaults to mainnet |
| `DEFAULT_DAO_ID` | No | Default DAO so users don't have to specify it every time |

### 3. Install and Run

```bash
pip install -r requirements.txt
python dao_helper_bot.py
```

## Commands

### `/dao-info`
Show DAO statistics: treasury balance, council members, proposal count, bond requirements, voting period.

| Parameter | Required | Description |
|---|---|---|
| `dao` | No | DAO contract address |

### `/dao-proposals`
List proposals from a DAO. Filters by status (active, approved, rejected, expired).

| Parameter | Default | Description |
|---|---|---|
| `dao` | DEFAULT_DAO_ID | DAO contract address |
| `status` | active | Filter: all, active, approved, rejected, expired |
| `limit` | 5 | Number of proposals (max 10) |

### `/dao-vote`
Generate a near-cli command to vote on a proposal. Shows current vote tally and proposal status.

| Parameter | Required | Description |
|---|---|---|
| `proposal_id` | Yes | Proposal ID number |
| `action` | No | approve, reject, or remove (default: approve) |
| `dao` | No | DAO contract address |

### `/dao-create-proposal`
Generate a near-cli command to create a new proposal.

| Parameter | Required | Description |
|---|---|---|
| `kind` | Yes | transfer, function_call, vote, add_member, remove_member |
| `description` | Yes | Proposal description |
| `receiver` | For transfers/calls | Receiver account ID |
| `amount` | For transfers | Amount in NEAR |
| `member` | For member changes | Account ID to add or remove |
| `dao` | No | DAO contract address |

### `/dao-members`
List all DAO roles and their members.

| Parameter | Required | Description |
|---|---|---|
| `dao` | No | DAO contract address |

### `/proposal-detail`
View a single proposal with full vote breakdown.

| Parameter | Required | Description |
|---|---|---|
| `proposal_id` | Yes | Proposal ID number |
| `dao` | No | DAO contract address |

### `/treasury`
View DAO treasury: NEAR balance, staked NEAR, and fungible token holdings (wNEAR, REF, stNEAR, AURORA, USN).

| Parameter | Required | Description |
|---|---|---|
| `dao` | No | DAO contract address |

## How It Works

The bot reads on-chain data directly from NEAR RPC using Sputnik DAO v2 contract view methods:

- `get_policy` — DAO policy, roles, bonds, voting period
- `get_proposals` — List proposals with pagination
- `get_proposal` — Single proposal with full details
- `get_last_proposal_id` — Total proposal count
- `view_account` — Account balance and storage

For vote and propose commands, the bot generates ready-to-run `near-cli` commands. Actual transaction signing happens outside Discord through your wallet or CLI.

## Supported DAOs

The bot includes autocomplete for well-known Sputnik DAOs:

- `sputnik-dao.near`
- `nearweek-news.sputnik-dao.near`
- `marketing-dao.sputnik-dao.near`
- `creativesdao.sputnik-dao.near`
- `near-analytics.sputnik-dao.near`
- `human-guild.sputnik-dao.near`
- `move-dao.sputnik-dao.near`
- `ref-community-board.sputnik-dao.near`

Any Sputnik DAO v2 contract address works — type it manually if your DAO is not in the autocomplete list.
