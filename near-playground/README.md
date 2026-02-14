# NEAR Playground

An interactive browser-based playground for NEAR Protocol development. Connect to testnet or mainnet RPC, run code snippets, look up accounts, and build transactions.

## Features

- **Live RPC connection** to NEAR testnet and mainnet
- **Code editor** with line numbers, tab support, and keyboard shortcuts (Ctrl+Enter to run)
- **5 built-in snippets** -- Account lookup, view methods, FT balance, validators, block info
- **Account lookup** tab with balance, storage, and access key inspection
- **Transaction builder** tab for constructing view and call method invocations
- **NEAR API wrapper** (`near.*`) for quick RPC interactions
- **Dark theme** UI optimized for developer workflows
- **Responsive layout** that works on desktop and mobile
- **near-api-js** loaded from CDN -- no build step required

## Project Structure

```
near-playground/
  index.html       # HTML layout, CSS, code examples, reference docs
  playground.js    # JavaScript logic: RPC, editor, account lookup, TX builder
  README.md        # This file
```

## Setup

No installation required. Serve the directory with any HTTP server:

```bash
# Option 1: Python HTTP server
python3 -m http.server 8080

# Option 2: npx serve
npx serve .

# Option 3: VS Code Live Server extension
# Right-click index.html -> Open with Live Server
```

Then open `http://localhost:8080` in your browser.

## Tabs

### Code Editor

Write and run JavaScript against live NEAR RPC. Built-in snippets:

| Snippet | Description |
|---------|-------------|
| View Account | Look up balance, storage, and code hash |
| View Method | Call any read-only contract method |
| FT Balance | Check fungible token balance with metadata |
| Validators | List current validators sorted by stake |
| Block Info | Get latest block height, hash, and gas price |

### Account Lookup

Enter any NEAR account ID to view:

- Balance (in NEAR)
- Locked amount
- Storage usage
- Code hash
- Access keys and their permissions

### Transaction Builder

Construct contract calls visually:

- Set contract ID, method name, and JSON arguments
- Choose between view (read-only) and call (state-changing)
- Configure gas and deposit amounts
- Generate code or execute view calls directly

## NEAR API (`near.*`)

The playground exposes a `near` object with these methods:

| Method | Description |
|--------|-------------|
| `near.viewAccount(accountId)` | Query account state and balance |
| `near.viewMethod(contractId, method, args)` | Call a read-only contract method |
| `near.getAccessKeys(accountId)` | List all access keys for an account |
| `near.getBlock(blockRef)` | Get block details (default: latest) |
| `near.txStatus(txHash, senderId)` | Check transaction status |
| `near.validators()` | List current epoch validators |
| `near.getGasPrice()` | Get current gas price |
| `near.rpc(method, params)` | Raw JSON-RPC call |
| `near.formatNear(yocto)` | Convert yoctoNEAR to NEAR string |
| `near.parseNear(near)` | Convert NEAR string to yoctoNEAR |
| `near.network` | Current network name (testnet/mainnet) |

## Code Examples (Static Templates)

The `index.html` file also includes 10 static code templates that can be browsed, copied, and used in your own projects:

| Example | Description |
|---------|-------------|
| Account Lookup | Query account state, balance, and storage |
| View Contract State | Call read-only contract methods via RPC |
| Fungible Token Balance | Check FT balances with metadata and formatting |
| Token Transfer | Send NEAR and fungible tokens (ft_transfer) |
| NFT Token Query | Query NFT metadata, supply, and owned tokens |
| Deploy Contract | Deploy and initialize a WASM smart contract |
| Cross-Contract Call | Call another contract from within your contract (Rust) |
| Batch Transaction | Execute multiple actions in a single transaction |
| Storage Deposit | NEP-145 storage registration for token contracts |
| Access Key Management | List, add, and manage FullAccess and FunctionCall keys |

## Dependencies

- [near-api-js](https://github.com/near/near-api-js) v4.0.4 (loaded from CDN)

## License

MIT
