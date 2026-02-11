# OpenClaw Skill: NEAR NFT Manager

Manage NEAR NFTs — view collections, get metadata, transfer, mint, and browse marketplace listings. Uses NEP-171 standard.

## Setup

```bash
export NEAR_ACCOUNT_ID="your-account.near"
export NEAR_RPC_URL="https://rpc.mainnet.near.org"  # optional
```

No external dependencies — Python stdlib only.

## Commands

### List owned NFTs
```bash
python nft_manager.py owned '{"account_id": "alice.near"}'
```

### Get NFT details
```bash
python nft_manager.py details '{"contract": "x.paras.near", "token_id": "123"}'
```

### Transfer an NFT
```bash
python nft_manager.py transfer '{"contract": "x.paras.near", "token_id": "123", "receiver_id": "bob.near"}'
```
Returns near-cli command to execute the transfer.

### Mint an NFT
```bash
python nft_manager.py mint '{"contract": "your-nft.near", "title": "My NFT", "media": "https://..."}'
```

### List collections
```bash
python nft_manager.py collections
```

### Browse marketplace
```bash
python nft_manager.py marketplace '{"limit": 5}'
python nft_manager.py marketplace '{"contract": "x.paras.near", "limit": 10}'
```

## Supported Collections

- Paras (`x.paras.near`)
- Mintbase (`mintbase1.near`)
- Few and Far (`fewandfar.near`)
- Antisocial Ape Club (`asac.near`)
- NEARNauts (`nearnauts.near`)
- Tenk DAO (`tenk.near`)
- And more...

## Programmatic Usage

```python
from nft_manager import near_nft_owned, near_nft_details

# List NFTs
result = near_nft_owned(account_id="alice.near")
for nft in result["nfts"]:
    print(f"{nft['title']} ({nft['contract']}:{nft['token_id']})")

# Get details
details = near_nft_details(contract="x.paras.near", token_id="123")
print(details["title"], details["media"])
```
