# OpenClaw Skill: NEAR DAO Governance

Participate in NEAR DAO governance — list DAOs, view proposals, vote, create proposals, and inspect treasuries. Uses Sputnik DAO v2 contracts.

## Setup

```bash
export NEAR_ACCOUNT_ID="your-account.near"
export NEAR_RPC_URL="https://rpc.mainnet.near.org"  # optional
```

No external dependencies — Python stdlib only.

## Commands

### List DAOs
```bash
python dao_governance.py daos
```

### Get DAO info
```bash
python dao_governance.py info '{"dao_id": "marketing-dao.sputnik-dao.near"}'
```

### List proposals
```bash
python dao_governance.py proposals '{"dao_id": "marketing-dao.sputnik-dao.near"}'
python dao_governance.py proposals '{"dao_id": "marketing-dao.sputnik-dao.near", "status": "active"}'
```

### Vote on a proposal
```bash
python dao_governance.py vote '{"dao_id": "marketing-dao.sputnik-dao.near", "proposal_id": 42, "vote": "approve"}'
```
Returns near-cli command to execute the vote.

### Create a proposal
```bash
python dao_governance.py propose '{"dao_id": "marketing-dao.sputnik-dao.near", "kind": "transfer", "description": "Fund project X", "details": {"receiver_id": "alice.near", "amount": "1000000000000000000000000"}}'
```

### View treasury
```bash
python dao_governance.py treasury '{"dao_id": "marketing-dao.sputnik-dao.near"}'
```

## Supported DAOs

- marketing-dao.sputnik-dao.near
- creativesdao.sputnik-dao.near
- near-analytics.sputnik-dao.near
- human-guild.sputnik-dao.near
- ref-community-board.sputnik-dao.near
- And any Sputnik DAO v2 contract

## Programmatic Usage

```python
from dao_governance import near_dao_info, near_proposals_list

# Get DAO info
info = near_dao_info(dao_id="marketing-dao.sputnik-dao.near")
print(f"Council: {info['council_count']} members, Treasury: {info['balance_near']} NEAR")

# List active proposals
props = near_proposals_list(dao_id="marketing-dao.sputnik-dao.near", status="active")
for p in props["proposals"]:
    print(f"#{p['id']} [{p['kind']}] {p['description'][:60]}")
```
