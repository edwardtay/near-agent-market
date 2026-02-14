# near-testing

Testing utilities for NEAR smart contracts. Spin up a local sandbox node, deploy contracts, create funded test accounts, and assert on transaction outcomes -- all from Python.

## Installation

```bash
pip install near-testing
```

### Prerequisites

- Python 3.8+
- `near-cli` installed and available on PATH (`npm i -g near-cli`)
- `near-sandbox` or `neard` binary for local node (install from [nearcore](https://github.com/near/nearcore))

## Quick Start

```python
from near_testing import (
    NearSandbox,
    ContractDeployer,
    TestAccount,
    assert_transaction_success,
    assert_event_emitted,
)

# Start a local sandbox node
with NearSandbox() as sandbox:
    # Deploy a contract
    deployer = ContractDeployer(sandbox)
    deployer.deploy(
        "target/wasm32-unknown-unknown/release/my_contract.wasm",
        account_id="contract.test.near",
        init_method="new",
        init_args={"owner_id": "contract.test.near"},
    )

    # Create a funded test account
    alice = TestAccount.create(sandbox, "alice.test.near", initial_balance="50")

    # Call a contract method
    result = alice.call(
        "contract.test.near",
        "transfer",
        {"receiver_id": "bob.test.near", "amount": "1000000"},
        deposit="1",
    )

    # Assert on the outcome
    assert_transaction_success(result)
    assert_event_emitted(result, "ft_transfer", standard="nep141")
```

## Usage with pytest

```python
import pytest
from near_testing import NearSandbox, ContractDeployer, TestAccount

@pytest.fixture(scope="session")
def sandbox():
    with NearSandbox() as sb:
        yield sb

@pytest.fixture
def deployer(sandbox):
    return ContractDeployer(sandbox)

@pytest.fixture
def alice(sandbox):
    return TestAccount.create(sandbox, "alice.test.near")

def test_contract_call(sandbox, deployer, alice):
    deployer.deploy("contract.wasm", "contract.test.near")
    result = alice.call("contract.test.near", "hello", {"name": "world"})
    assert result.succeeded
```

## API Reference

### NearSandbox

Manages a local NEAR sandbox node.

```python
sandbox = NearSandbox(
    home_dir=None,         # Path for node data (temp dir if None)
    rpc_port=3030,         # RPC port for the sandbox node
    near_cli="near",       # Path to near-cli binary
    startup_timeout=30.0,  # Seconds to wait for node startup
)
```

**Methods:**

| Method | Description |
|--------|-------------|
| `start()` | Initialize and start the sandbox node |
| `stop()` | Terminate the node and clean up |
| `is_running` | Property; True if the node process is alive |
| `run_near_cli(args)` | Run a near-cli command against this sandbox |
| `rpc_call(method, params)` | Make a raw JSON-RPC call to the sandbox |

Supports context manager usage (`with NearSandbox() as sandbox:`).

### ContractDeployer

Deploys WASM contracts to a running sandbox.

```python
deployer = ContractDeployer(sandbox)
result = deployer.deploy(
    wasm_path="contract.wasm",    # Path to .wasm file
    account_id="app.test.near",   # Account to deploy to
    init_method="new",            # Optional init method
    init_args={"owner": "..."},   # Optional init arguments
    init_deposit="0",             # Deposit for init call
    init_gas="300000000000000",   # Gas for init call
)
```

Returns a `TransactionResult`.

### TestAccount

Creates and manages funded test accounts.

```python
# Create an account
alice = TestAccount.create(
    sandbox,
    "alice.test.near",
    initial_balance="100",  # Balance in NEAR
)

# Call a contract method (change call)
result = alice.call(
    contract_id="contract.test.near",
    method="transfer",
    args={"to": "bob.test.near"},
    deposit="1",
    gas="300000000000000",
)

# View a contract method (free, no signer)
value = alice.view("contract.test.near", "get_balance", {"account_id": "alice.test.near"})

# Check balance
balance = alice.balance()
```

### TransactionResult

Returned by `call_contract()`, `ContractDeployer.deploy()`, and `TestAccount.call()`.

```python
result.transaction_hash  # str - the tx hash
result.status            # str - "success" or "failure"
result.succeeded         # bool - True if status == "success"
result.logs              # List[str] - log lines from the transaction
result.events            # List[dict] - parsed NEP-297 events
result.raw               # dict - raw parsed output
```

### Helper Functions

```python
from near_testing import call_contract, view_contract

# Change call (requires signer)
result = call_contract(
    sandbox,
    contract_id="contract.test.near",
    method="set_greeting",
    args={"greeting": "hello"},
    signer_id="alice.test.near",
    deposit="0",
    gas="300000000000000",
)

# View call (read-only, no signer needed)
value = view_contract(
    sandbox,
    contract_id="contract.test.near",
    method="get_greeting",
    args={},
)
```

### Assertion Helpers

```python
from near_testing import (
    assert_transaction_success,
    assert_transaction_failure,
    assert_event_emitted,
    assert_log_contains,
)

# Assert transaction succeeded
assert_transaction_success(result)

# Assert transaction failed (for negative tests)
assert_transaction_failure(result)

# Assert a NEP-297 event was emitted
assert_event_emitted(
    result,
    event="nft_mint",
    standard="nep171",                          # optional
    data={"owner_id": "alice.test.near"},        # optional subset match
)

# Assert a log line contains a substring
assert_log_contains(result, "Transfer successful")
```

### Exceptions

| Exception | When |
|-----------|------|
| `NearTestingError` | Base exception for all errors |
| `SandboxStartupError` | Sandbox node fails to start |
| `ContractDeployError` | Contract deployment fails |
| `TransactionError` | A transaction fails unexpectedly |

## License

MIT
