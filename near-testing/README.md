# near-testing

Testing utilities for NEAR smart contracts. Mock RPC calls for unit tests, create funded test accounts, deploy contracts, and assert on transaction outcomes -- all from Python with zero external dependencies.

## Installation

```bash
pip install near-testing
```

### Requirements

- Python 3.8+
- No external dependencies (uses stdlib only)
- For sandbox integration tests: `near-cli` and `neard` / `near-sandbox` on PATH

## Quick Start

### Unit Testing with MockRPC

```python
from near_testing import MockRPC, assert_transaction_success

# Create a mock RPC layer
with MockRPC() as mock:
    # Register mock accounts
    mock.add_account("alice.near", balance_near=50.0)
    mock.add_account("bob.near", balance_near=10.0)

    # Register mock view method results
    mock.add_view_result("wrap.near", "ft_balance_of", "5000000000000000000000000")
    mock.add_view_result("wrap.near", "ft_metadata", {
        "name": "Wrapped NEAR",
        "symbol": "wNEAR",
        "decimals": 24,
    })

    # Query the mock
    result = mock.query("query", {
        "request_type": "view_account",
        "account_id": "alice.near",
        "finality": "final",
    })
    assert result["amount"] == "50000000000000000000000000"

    # Assert calls were made
    mock.assert_called("query", match={"account_id": "alice.near"})
```

### Integration Testing with Sandbox

```python
from near_testing import (
    sandbox_context,
    ContractDeployer,
    NearTestAccount,
    assert_transaction_success,
    assert_event_emitted,
)

with sandbox_context() as ctx:
    # Deploy a contract
    deployer = ContractDeployer(ctx)
    deployer.deploy(
        "target/wasm32-unknown-unknown/release/my_contract.wasm",
        account_id="contract.test.near",
        init_method="new",
        init_args={"owner_id": "contract.test.near"},
    )

    # Create a funded test account
    alice = NearTestAccount.create(ctx, "alice.test.near", initial_balance="50")

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
from near_testing import MockRPC, sandbox_context, ContractDeployer, NearTestAccount

# --- Unit test fixtures (no sandbox needed) ---

@pytest.fixture
def mock_rpc():
    with MockRPC() as mock:
        mock.add_account("alice.near", balance_near=100.0)
        mock.add_view_result("token.near", "ft_balance_of", "1000")
        yield mock

def test_account_lookup(mock_rpc):
    result = mock_rpc.query("query", {
        "request_type": "view_account",
        "account_id": "alice.near",
        "finality": "final",
    })
    assert int(result["amount"]) > 0

# --- Integration test fixtures (requires near-sandbox) ---

@pytest.fixture(scope="session")
def sandbox():
    with sandbox_context() as ctx:
        yield ctx

@pytest.fixture
def deployer(sandbox):
    return ContractDeployer(sandbox)

@pytest.fixture
def alice(sandbox):
    return NearTestAccount.create(sandbox, "alice.test.near")

def test_contract_call(sandbox, deployer, alice):
    deployer.deploy("contract.wasm", "contract.test.near")
    result = alice.call("contract.test.near", "hello", {"name": "world"})
    assert result.succeeded
```

## API Reference

### MockRPC

Mock NEAR RPC client for unit testing without a live node.

```python
mock = MockRPC(rpc_url="http://localhost:3030")
```

**Methods:**

| Method | Description |
|--------|-------------|
| `add_response(method, result, match=, error=)` | Register a generic mock RPC response |
| `add_account(account_id, balance_near=, ...)` | Convenience: register a mock account |
| `add_view_result(contract_id, method_name, result)` | Convenience: register a mock view method result |
| `query(method, params)` | Simulate an RPC call and return the matching response |
| `assert_called(method, match=)` | Assert that a specific RPC method was called |
| `assert_not_called(method)` | Assert that a specific RPC method was never called |
| `patch_urlopen()` | Patch `urllib.request.urlopen` to route through this mock |
| `reset()` | Clear recorded calls (keeps registered responses) |

**Properties:**

| Property | Description |
|----------|-------------|
| `calls` | List of all RPC calls made through this mock |
| `call_count` | Total number of RPC calls made |

Supports context manager usage (`with MockRPC() as mock:`).

### sandbox_context

Context manager that starts a local NEAR sandbox node.

```python
with sandbox_context(
    rpc_port=3030,
    near_cli="near",
    startup_timeout=30.0,
) as ctx:
    # ctx is a SandboxContext instance
    ...
```

**SandboxContext methods:**

| Method | Description |
|--------|-------------|
| `start()` | Initialize and start the sandbox node |
| `stop()` | Terminate the node and clean up |
| `is_running` | Property; True if the node process is alive |
| `run_near_cli(args)` | Run a near-cli command against this sandbox |
| `rpc_call(method, params)` | Make a raw JSON-RPC call to the sandbox |

### ContractDeployer

Deploys WASM contracts to a running sandbox.

```python
deployer = ContractDeployer(ctx)
result = deployer.deploy(
    wasm_path="contract.wasm",
    account_id="app.test.near",
    init_method="new",
    init_args={"owner": "..."},
    init_deposit="0",
    init_gas="300000000000000",
)
```

### NearTestAccount

Creates and manages funded test accounts.

```python
alice = NearTestAccount.create(ctx, "alice.test.near", initial_balance="100")

result = alice.call("contract.test.near", "transfer", {"to": "bob.test.near"}, deposit="1")
value = alice.view("contract.test.near", "get_balance", {"account_id": "alice.test.near"})
balance = alice.balance()
```

### TransactionResult

Returned by `call_contract()`, `ContractDeployer.deploy()`, and `NearTestAccount.call()`.

```python
result.transaction_hash  # str
result.status            # "success" or "failure"
result.succeeded         # bool
result.logs              # List[str]
result.events            # List[dict] -- parsed NEP-297 events
result.raw               # dict -- raw parsed output
```

### Assertion Helpers

```python
from near_testing import (
    assert_transaction_success,
    assert_transaction_failure,
    assert_event_emitted,
    assert_log_contains,
)

assert_transaction_success(result)
assert_transaction_failure(result)
assert_event_emitted(result, "nft_mint", standard="nep171", data={"owner_id": "alice.near"})
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
