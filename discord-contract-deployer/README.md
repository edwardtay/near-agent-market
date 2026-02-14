# NEAR Contract Deployer Discord Bot

Deploy, verify, and manage NEAR smart contracts directly from Discord.

## Setup

### 1. Create a Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application and add a Bot
3. Enable the **Message Content Intent** under Bot settings
4. Generate an invite URL with the `bot` and `applications.commands` scopes
5. Invite the bot to your server

### 2. Configure Environment

Create a `.env` file in this directory:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token
NEAR_ACCOUNT_ID=deployer.testnet
NEAR_PRIVATE_KEY=ed25519:your_private_key
NEAR_PUBLIC_KEY=ed25519:your_public_key
NEAR_NETWORK=testnet
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

The bot also requires `near-cli` for signing and broadcasting deploy transactions:

```bash
npm install -g near-cli
```

Log in with the deployer account:

```bash
near login --networkId testnet
```

### 4. Run

```bash
python contract_deployer_bot.py
```

## Commands

| Command | Description |
|---------|-------------|
| `/deploy <contract_account> <wasm_url>` | Deploy a compiled WASM contract to a NEAR account |
| `/status <contract_account> [tx_hash]` | Check contract state or transaction status |
| `/view <contract_account> <method> [args]` | Call a read-only view method and display the result |
| `/call <contract_account> <method> [args] [gas] [deposit]` | Generate a near-cli command for a state-changing call |
| `/contracts [show_all]` | List contracts deployed through this bot |
| `/verify <contract_account> <wasm_url>` | Verify on-chain code matches a reference WASM binary |
| `/deployer-help` | Show the help guide and deployment workflow |

## Deployment Workflow

1. **Compile** your Rust contract:
   ```bash
   cargo build --target wasm32-unknown-unknown --release
   ```

2. **Host** the `.wasm` file somewhere accessible (GitHub release, IPFS, any HTTPS URL).

3. **Deploy** via Discord:
   ```
   /deploy contract_account:myapp.testnet wasm_url:https://example.com/contract.wasm
   ```

4. **Check status**:
   ```
   /status contract_account:myapp.testnet
   ```

5. **Verify** the deployment matches your build:
   ```
   /verify contract_account:myapp.testnet wasm_url:https://example.com/contract.wasm
   ```

## Architecture

- **NEAR RPC** — `view_account` and `view_code` queries go directly through the JSON-RPC endpoint
- **Deployment** — uses `near-cli` subprocess for transaction signing and broadcasting
- **Verification** — downloads the on-chain code via RPC, hashes it with SHA-256, and compares against the reference WASM
- **Persistence** — deployment records are stored locally in `data/deployments.json`

## Networks

Set `NEAR_NETWORK` in your `.env`:

| Value | RPC Endpoint | Explorer |
|-------|-------------|----------|
| `testnet` | `https://rpc.testnet.near.org` | `https://testnet.nearblocks.io` |
| `mainnet` | `https://rpc.mainnet.near.org` | `https://nearblocks.io` |
