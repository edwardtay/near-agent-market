# NEAR ABI Generator - GitHub Action

Generates a JSON ABI from NEAR smart contracts written in Rust. Extracts method signatures, parameter types, return types, and annotations (`#[init]`, `#[payable]`, `#[private]`) from your contract source code.

## How it works

1. Attempts to use `cargo-near abi` for full-fidelity ABI generation.
2. If `cargo-near` is unavailable or fails, falls back to parsing Rust source files directly for `#[near]` / `#[near_bindgen]` annotated impl blocks.
3. Outputs a JSON ABI file and uploads it as a workflow artifact.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `contract_path` | No | `.` | Path to the contract crate (directory with `Cargo.toml`) |
| `output_path` | No | `abi.json` | Where to write the generated ABI |
| `near_sdk_version` | No | auto-detected | Override the `near-sdk` version in metadata |

## Outputs

| Output | Description |
|---|---|
| `abi_file` | Path to the generated ABI file |
| `method_count` | Number of contract methods found |

## Usage

### Basic

```yaml
name: Generate NEAR ABI
on:
  push:
    branches: [main]
  pull_request:

jobs:
  abi:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Generate ABI
        uses: your-org/near-agent-market/github-action-abi-generator@main

      - name: Show ABI
        run: cat abi.json
```

### Custom contract path and output

```yaml
      - name: Generate ABI
        uses: your-org/near-agent-market/github-action-abi-generator@main
        with:
          contract_path: contracts/my-contract
          output_path: artifacts/contract-abi.json
```

### Use the ABI in a later step

```yaml
      - name: Generate ABI
        id: abi
        uses: your-org/near-agent-market/github-action-abi-generator@main

      - name: Report
        run: |
          echo "Found ${{ steps.abi.outputs.method_count }} methods"
          echo "ABI file: ${{ steps.abi.outputs.abi_file }}"
```

### Multi-contract workspace

```yaml
jobs:
  abi:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        contract: [token, marketplace, staking]
    steps:
      - uses: actions/checkout@v4
      - name: Generate ABI
        uses: your-org/near-agent-market/github-action-abi-generator@main
        with:
          contract_path: contracts/${{ matrix.contract }}
          output_path: abi/${{ matrix.contract }}.json
```

## ABI Output Format

```json
{
  "schema_version": "0.4.0",
  "metadata": {
    "name": "Contract",
    "build": {
      "compiler": "rustc",
      "builder": "near-abi-generator-action",
      "near_sdk_version": "5.6.0"
    }
  },
  "body": {
    "functions": [
      {
        "name": "new",
        "kind": "init",
        "params": [
          { "name": "owner_id", "type_schema": "AccountId" }
        ],
        "annotations": ["init"]
      },
      {
        "name": "get_balance",
        "kind": "view",
        "params": [
          { "name": "account_id", "type_schema": "AccountId" }
        ],
        "return_type": "U128"
      },
      {
        "name": "transfer",
        "kind": "call",
        "params": [
          { "name": "receiver_id", "type_schema": "AccountId" },
          { "name": "amount", "type_schema": "U128" }
        ],
        "is_payable": true,
        "annotations": ["payable"]
      }
    ]
  }
}
```

## Supported Annotations

- `#[near(contract_state)]` / `#[near_bindgen]` - Contract struct detection
- `#[near]` / `#[near_bindgen]` on impl blocks - Method extraction
- `#[init]` - Constructor / initialization methods
- `#[payable]` - Methods that accept attached NEAR
- `#[private]` - Cross-contract callback methods
- `#[near(event_standard(...))]` - NEP-297 event detection

## Requirements

- The contract must use `near-sdk` as a dependency in `Cargo.toml`.
- Rust source files must be in `src/` relative to the contract path.
- Python 3 is required (available by default on GitHub-hosted runners).
- Rust toolchain is installed automatically if not present.
