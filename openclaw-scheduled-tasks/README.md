# OpenClaw Skill: NEAR Scheduled Tasks

Schedule recurring NEAR operations — staking rewards checks, balance monitoring, rebalancing suggestions, and recurring payment tracking.

## Setup

```bash
export NEAR_ACCOUNT_ID="your-account.near"
export NEAR_RPC_URL="https://rpc.mainnet.near.org"  # optional
```

No external dependencies — Python stdlib only.

## Commands

### Schedule a task
```bash
python scheduled_tasks.py schedule check_balance "0 */6 * * *"
python scheduled_tasks.py schedule rebalance "0 9 * * 1" '{"target_stake_pct": 70}'
python scheduled_tasks.py schedule claim_rewards "0 9 * * *" '{"validator": "pool.near"}'
```

### List scheduled tasks
```bash
python scheduled_tasks.py list
```

### Run due tasks
```bash
python scheduled_tasks.py run
```

### View history
```bash
python scheduled_tasks.py history 10
```

### Remove a task
```bash
python scheduled_tasks.py remove <task_id>
```

## Task Types

| Type | Description | Params |
|------|-------------|--------|
| check_balance | Check account balance | account_id |
| claim_rewards | Check staking rewards | account_id, validator |
| transfer | Log transfer intent | receiver_id, amount_near |
| rebalance | Suggest stake rebalancing | account_id, target_stake_pct |

## Cron Format

Standard 5-field cron: `minute hour day month weekday`

- `0 9 * * *` — Daily at 9 AM
- `0 */6 * * *` — Every 6 hours
- `0 9 * * 1` — Every Monday at 9 AM
- `*/30 * * * *` — Every 30 minutes

## Cron Setup

```bash
# Run scheduler every minute to check for due tasks
* * * * * cd /path/to/scheduled-tasks && python scheduled_tasks.py run
```

## Storage

- Schedules: `~/.near_schedules.json`
- History: `~/.near_schedule_history.json`
