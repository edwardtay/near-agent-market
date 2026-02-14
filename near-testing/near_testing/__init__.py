"""
near-testing
~~~~~~~~~~~~

A testing utility library for NEAR smart contracts. Provides a local sandbox
environment, contract deployment helpers, test account management, and
assertion utilities for integration testing.

Usage::

    from near_testing import NearSandbox, ContractDeployer, TestAccount

    with NearSandbox() as sandbox:
        deployer = ContractDeployer(sandbox)
        deployer.deploy("contract.wasm", "contract.test.near")

        alice = TestAccount.create(sandbox, "alice.test.near")
        result = alice.call("contract.test.near", "my_method", {"key": "value"})

        assert_transaction_success(result)
"""

from near_testing.sandbox import (
    # Core classes
    NearSandbox,
    ContractDeployer,
    TestAccount,
    TransactionResult,
    # Helper functions
    call_contract,
    view_contract,
    # Assertion helpers
    assert_transaction_success,
    assert_transaction_failure,
    assert_event_emitted,
    assert_log_contains,
    # Exceptions
    NearTestingError,
    SandboxStartupError,
    ContractDeployError,
    TransactionError,
)

__version__ = "0.1.0"

__all__ = [
    # Core classes
    "NearSandbox",
    "ContractDeployer",
    "TestAccount",
    "TransactionResult",
    # Helper functions
    "call_contract",
    "view_contract",
    # Assertion helpers
    "assert_transaction_success",
    "assert_transaction_failure",
    "assert_event_emitted",
    "assert_log_contains",
    # Exceptions
    "NearTestingError",
    "SandboxStartupError",
    "ContractDeployError",
    "TransactionError",
    # Metadata
    "__version__",
]
