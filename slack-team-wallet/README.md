# NEAR Team Wallet — Slack Bot

Multi-sig style team treasury management for NEAR Protocol, built as a Slack app. Create transfer requests, require approvals from team members, check balances, and view transaction history — all from Slack.

## Features

- `/near-balance` — Live wallet balance from NEAR RPC
- `/near-send <recipient> <amount> [memo]` — Create a transfer request with approval flow
- `/near-approve [tx_id]` — Approve pending transfers (or list all pending)
- `/near-history` — Recent on-chain transactions
- `/near-stake` — Staking overview (locked vs available balance)
- Interactive approve/reject buttons on transfer requests
- App Home tab with wallet overview and pending requests
- Configurable multi-sig: set how many approvals are required
- Restrict approvals to specific Slack users

## Setup

### 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app
2. Under **OAuth & Permissions**, add these Bot Token Scopes:
   - `chat:write`
   - `commands`
   - `im:history`
   - `im:read`
3. Under **Slash Commands**, create:
   - `/near-balance`
   - `/near-send`
   - `/near-approve`
   - `/near-history`
   - `/near-stake`
4. Under **Interactivity & Shortcuts**, enable Interactivity and set the Request URL to your server (e.g. `https://your-domain.com/slack/events`)
5. Under **Event Subscriptions**, enable events and subscribe to:
   - `app_home_opened`
   - `message.im`
6. Install the app to your workspace

### 2. Socket Mode (Recommended for Development)

Instead of configuring a public URL, you can use Socket Mode:

1. Under **Settings > Socket Mode**, enable Socket Mode
2. Generate an App-Level Token with `connections:write` scope
3. Set `SLACK_APP_TOKEN` to this token (starts with `xapp-`)

### 3. Environment Variables

```bash
export SLACK_BOT_TOKEN="xoxb-..."           # Bot User OAuth Token
export SLACK_SIGNING_SECRET="..."            # App Signing Secret
export SLACK_APP_TOKEN="xapp-..."            # App-Level Token (socket mode only)
export NEAR_ACCOUNT_ID="team.near"           # Team treasury account
export NEAR_RPC_URL="https://rpc.mainnet.near.org"  # NEAR RPC endpoint
export REQUIRED_APPROVALS="2"                # Number of approvals needed (default: 2)
export APPROVER_SLACK_IDS="U12345,U67890"    # Comma-separated Slack user IDs (leave empty to allow all)
```

### 4. Install & Run

```bash
pip install slack_bolt requests
python team_wallet.py
```

## Approval Flow

1. A team member runs `/near-send alice.near 10.0 Payment for security audit`
2. The bot posts a transfer request card with Approve/Reject buttons
3. Other authorized team members click Approve or use `/near-approve <tx_id>`
4. Once the required number of approvals is reached, the transfer is marked as approved
5. Self-approval is blocked — the requester cannot approve their own transfer

### Rejection

Any approver (or the original requester) can reject a transfer at any time by clicking the Reject button.

## Architecture

```
team_wallet.py          Single-file Slack bot (slack_bolt)
data/
  pending_transfers.json  Active transfer requests and their approval state
  tx_history.json         Local record of approved/rejected transfers
```

The bot queries NEAR RPC directly for balance and account data. Transaction history is fetched from the NearBlocks public API with a fallback to local records.

## Production Notes

- For HTTP mode (no Socket Mode), deploy behind nginx/Caddy and point Slack's Request URL to `https://your-domain.com/slack/events`
- On-chain transaction signing is not included — approved transfers are recorded and ready for submission via a separate signing service or CLI
- The `APPROVER_SLACK_IDS` variable restricts who can approve. If left empty, any workspace member can approve (except the requester)
- Pending transfers are stored as JSON files. For high-volume teams, swap `_load_json`/`_save_json` for a database
