"""
near_testing
~~~~~~~~~~~~

Testing utilities for NEAR smart contracts. Provides mock RPC, test accounts,
contract deployment helpers, assertion utilities, and a sandbox context manager
for integration testing -- all in a single file with zero external dependencies.

Usage::

    from near_testing import (
        NearTestAccount,
        ContractDeployer,
        MockRPC,
        assert_transaction_success,
        assert_transaction_failure,
        sandbox_context,
    )

    # Unit testing with MockRPC
    with MockRPC() as mock:
        mock.add_response("view_account", {"amount": "1000000000000000000000000"})
        result = mock.query("view_account", {"account_id": "alice.near"})
        assert result["amount"] == "1000000000000000000000000"

    # Integration testing with sandbox
    with sandbox_context() as ctx:
        deployer = ContractDeployer(ctx)
        deployer.deploy("contract.wasm", "app.test.near")
        alice = NearTestAccount.create(ctx, "alice.test.near")
        result = alice.call("app.test.near", "my_method", {"key": "value"})
        assert_transaction_success(result)
"""

import base64
import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from unittest.mock import patch, MagicMock

__version__ = "0.1.0"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class NearTestingError(Exception):
    """Base exception for near-testing errors."""


class SandboxStartupError(NearTestingError):
    """Raised when the sandbox node fails to start."""


class ContractDeployError(NearTestingError):
    """Raised when contract deployment fails."""


class TransactionError(NearTestingError):
    """Raised when a transaction fails unexpectedly."""


class AssertionError(NearTestingError):
    """Raised when a test assertion fails."""


# ---------------------------------------------------------------------------
# TransactionResult
# ---------------------------------------------------------------------------

@dataclass
class TransactionResult:
    """Parsed result of a NEAR transaction."""

    transaction_hash: str
    status: str
    logs: List[str] = field(default_factory=list)
    receipts: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status == "success"

    @property
    def events(self) -> List[Dict[str, Any]]:
        """Extract NEP-297 style events from transaction logs.

        NEP-297 events are JSON log lines with ``EVENT_JSON:`` prefix.
        """
        events: List[Dict[str, Any]] = []
        for log_line in self.logs:
            if log_line.startswith("EVENT_JSON:"):
                try:
                    events.append(json.loads(log_line[len("EVENT_JSON:"):]))
                except json.JSONDecodeError:
                    pass
        return events


# ---------------------------------------------------------------------------
# MockRPC -- for unit testing without a live node
# ---------------------------------------------------------------------------

class MockRPC:
    """Mock NEAR RPC client for unit testing.

    Provides a fake RPC layer that returns pre-configured responses,
    allowing you to test NEAR-interacting code without a real node.

    Usage::

        with MockRPC() as mock:
            mock.add_response("query", {
                "amount": "5000000000000000000000000",
                "code_hash": "11111111111111111111111111111111",
                "storage_usage": 182,
            }, match={"request_type": "view_account"})

            result = mock.query("query", {
                "request_type": "view_account",
                "account_id": "alice.near",
                "finality": "final",
            })
            assert result["amount"] == "5000000000000000000000000"

    You can also use it to mock ``urllib.request.urlopen`` globally::

        with MockRPC() as mock:
            mock.add_response("query", {"amount": "1000"})
            mock.patch_urlopen()

            # Now any code using urllib.request.urlopen to call NEAR RPC
            # will receive the mocked responses.
    """

    def __init__(self, rpc_url: str = "http://localhost:3030"):
        self.rpc_url = rpc_url
        self._responses: List[Dict[str, Any]] = []
        self._calls: List[Dict[str, Any]] = []
        self._patches: list = []

    def add_response(
        self,
        method: str,
        result: Any,
        *,
        match: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
    ) -> "MockRPC":
        """Register a mock response for an RPC method.

        Parameters
        ----------
        method:
            The RPC method name (e.g. ``"query"``, ``"tx"``, ``"status"``).
        result:
            The ``result`` field to return in the JSON-RPC response.
        match:
            If provided, only return this response when the request params
            contain all of these key-value pairs (subset match).
        error:
            If provided, return an error response instead of a result.
        """
        self._responses.append({
            "method": method,
            "result": result,
            "match": match,
            "error": error,
        })
        return self

    def add_account(
        self,
        account_id: str,
        balance_near: float = 100.0,
        storage_usage: int = 182,
        code_hash: str = "11111111111111111111111111111111",
        locked: str = "0",
    ) -> "MockRPC":
        """Convenience: register a mock account with the given balance.

        Parameters
        ----------
        account_id:
            The account ID to register.
        balance_near:
            Balance in NEAR (will be converted to yoctoNEAR).
        storage_usage:
            Storage used in bytes.
        code_hash:
            Code hash for the account.
        locked:
            Locked balance in yoctoNEAR.
        """
        amount = str(int(balance_near * 1e24))
        return self.add_response(
            "query",
            {
                "amount": amount,
                "locked": locked,
                "code_hash": code_hash,
                "storage_usage": storage_usage,
                "block_height": 100000000,
                "block_hash": "mock_block_hash",
            },
            match={"request_type": "view_account", "account_id": account_id},
        )

    def add_view_result(
        self,
        contract_id: str,
        method_name: str,
        result: Any,
    ) -> "MockRPC":
        """Convenience: register a mock view method result.

        Parameters
        ----------
        contract_id:
            The contract account ID.
        method_name:
            The view method name.
        result:
            The return value (will be JSON-encoded and converted to bytes).
        """
        encoded = list(json.dumps(result).encode("utf-8"))
        return self.add_response(
            "query",
            {"result": encoded, "logs": [], "block_height": 100000000},
            match={
                "request_type": "call_function",
                "account_id": contract_id,
                "method_name": method_name,
            },
        )

    def query(self, method: str, params: Any = None) -> Any:
        """Simulate an RPC call and return the matching response.

        Also records the call in ``self.calls`` for later assertion.
        """
        params = params or {}
        self._calls.append({"method": method, "params": params})

        for resp in self._responses:
            if resp["method"] != method:
                continue
            if resp["match"]:
                if not _is_subset(resp["match"], params if isinstance(params, dict) else {}):
                    continue
            if resp["error"]:
                raise NearTestingError(
                    f"Mock RPC error: {resp['error'].get('message', 'unknown')}"
                )
            return resp["result"]

        raise NearTestingError(
            f"No mock response registered for method={method!r} params={params!r}"
        )

    @property
    def calls(self) -> List[Dict[str, Any]]:
        """List of all RPC calls made through this mock."""
        return list(self._calls)

    @property
    def call_count(self) -> int:
        """Total number of RPC calls made."""
        return len(self._calls)

    def assert_called(self, method: str, *, match: Optional[Dict[str, Any]] = None) -> None:
        """Assert that a specific RPC method was called.

        Parameters
        ----------
        method:
            The RPC method to check for.
        match:
            If provided, verify that at least one call to this method
            had params containing these key-value pairs.
        """
        matching = [c for c in self._calls if c["method"] == method]
        if not matching:
            raise AssertionError(
                f"Expected RPC call to {method!r}, but it was never called.\n"
                f"All calls: {self._calls}"
            )
        if match:
            found = any(
                _is_subset(match, c["params"]) for c in matching
                if isinstance(c["params"], dict)
            )
            if not found:
                raise AssertionError(
                    f"RPC method {method!r} was called, but no call matched {match!r}.\n"
                    f"Calls to {method!r}: {matching}"
                )

    def assert_not_called(self, method: str) -> None:
        """Assert that a specific RPC method was never called."""
        matching = [c for c in self._calls if c["method"] == method]
        if matching:
            raise AssertionError(
                f"Expected no calls to {method!r}, but found {len(matching)}.\n"
                f"Calls: {matching}"
            )

    def reset(self) -> None:
        """Clear all recorded calls (keeps registered responses)."""
        self._calls.clear()

    def patch_urlopen(self) -> None:
        """Patch ``urllib.request.urlopen`` to route calls through this mock.

        Useful for testing code that uses the stdlib HTTP client to call
        NEAR RPC. The patch is active until the MockRPC context exits.
        """
        mock_rpc = self

        def fake_urlopen(req, **kwargs):
            data = req.data if hasattr(req, "data") else None
            if data:
                payload = json.loads(data.decode())
                method = payload.get("method", "")
                params = payload.get("params", {})
                try:
                    result = mock_rpc.query(method, params)
                    response_body = json.dumps({
                        "jsonrpc": "2.0",
                        "id": payload.get("id", "test"),
                        "result": result,
                    }).encode()
                except NearTestingError as e:
                    response_body = json.dumps({
                        "jsonrpc": "2.0",
                        "id": payload.get("id", "test"),
                        "error": {"message": str(e)},
                    }).encode()
            else:
                response_body = b'{"jsonrpc":"2.0","id":"test","result":{}}'

            mock_response = MagicMock()
            mock_response.read.return_value = response_body
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            return mock_response

        p = patch("urllib.request.urlopen", side_effect=fake_urlopen)
        self._patches.append(p)
        p.start()

    def __enter__(self) -> "MockRPC":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        for p in self._patches:
            p.stop()
        self._patches.clear()


# ---------------------------------------------------------------------------
# SandboxContext -- manages a local NEAR sandbox node
# ---------------------------------------------------------------------------

class SandboxContext:
    """Manages a local NEAR sandbox node for integration testing.

    Prefer using the :func:`sandbox_context` context manager instead
    of instantiating this class directly.
    """

    DEFAULT_RPC_PORT = 3030

    def __init__(
        self,
        *,
        home_dir: Optional[str] = None,
        rpc_port: int = DEFAULT_RPC_PORT,
        near_cli: str = "near",
        startup_timeout: float = 30.0,
    ) -> None:
        self.rpc_port = rpc_port
        self.rpc_url = f"http://localhost:{rpc_port}"
        self.near_cli = near_cli
        self.startup_timeout = startup_timeout

        self._process: Optional[subprocess.Popen] = None
        self._tmp_dir: Optional[tempfile.TemporaryDirectory] = None

        if home_dir:
            self.home_dir = Path(home_dir)
            self._owns_home = False
        else:
            self._tmp_dir = tempfile.TemporaryDirectory(prefix="near-sandbox-")
            self.home_dir = Path(self._tmp_dir.name)
            self._owns_home = True

    def start(self) -> "SandboxContext":
        """Initialise and start the sandbox node."""
        if self._process is not None:
            return self

        self._init_sandbox()
        self._start_node()
        self._wait_for_ready()
        return self

    def stop(self) -> None:
        """Terminate the sandbox node and clean up temporary files."""
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
            self._process = None

        if self._tmp_dir is not None:
            self._tmp_dir.cleanup()
            self._tmp_dir = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def run_near_cli(
        self,
        args: List[str],
        *,
        capture_output: bool = True,
        timeout: float = 60.0,
    ) -> subprocess.CompletedProcess:
        """Run a ``near`` CLI command against this sandbox."""
        env = os.environ.copy()
        env["NEAR_ENV"] = "localnet"
        env["NEAR_CLI_LOCALNET_RPC_SERVER_URL"] = self.rpc_url
        env["NEAR_HOME"] = str(self.home_dir)

        cmd = [self.near_cli] + args
        return subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            timeout=timeout,
            env=env,
        )

    def rpc_call(self, method: str, params: Any = None) -> Dict[str, Any]:
        """Make a raw JSON-RPC call to the sandbox node."""
        import urllib.request

        payload = {
            "jsonrpc": "2.0",
            "id": "near-testing",
            "method": method,
            "params": params or {},
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.rpc_url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    def _init_sandbox(self) -> None:
        neard = shutil.which("neard") or shutil.which("near-sandbox")
        if neard is None:
            raise SandboxStartupError(
                "Neither 'neard' nor 'near-sandbox' binary found on PATH. "
                "Install nearcore or near-sandbox to use sandbox_context."
            )

        result = subprocess.run(
            [neard, "--home", str(self.home_dir), "init", "--chain-id", "localnet"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise SandboxStartupError(
                f"Sandbox init failed (exit {result.returncode}): {result.stderr}"
            )

        config_path = self.home_dir / "config.json"
        if config_path.exists():
            config = json.loads(config_path.read_text())
            addr = config.get("rpc", {}).get("addr", f"0.0.0.0:{self.rpc_port}")
            host = addr.rsplit(":", 1)[0] if ":" in addr else "0.0.0.0"
            config.setdefault("rpc", {})["addr"] = f"{host}:{self.rpc_port}"
            config_path.write_text(json.dumps(config, indent=2))

    def _start_node(self) -> None:
        neard = shutil.which("neard") or shutil.which("near-sandbox")
        self._process = subprocess.Popen(
            [neard, "--home", str(self.home_dir), "run"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _wait_for_ready(self) -> None:
        import urllib.request
        import urllib.error

        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise SandboxStartupError(
                    f"Sandbox process exited prematurely with code {self._process.returncode}"
                )
            try:
                payload = json.dumps({
                    "jsonrpc": "2.0",
                    "id": "health",
                    "method": "status",
                    "params": [],
                }).encode()
                req = urllib.request.Request(
                    self.rpc_url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=2) as resp:
                    body = json.loads(resp.read().decode())
                    if "result" in body:
                        return
            except (urllib.error.URLError, ConnectionRefusedError, OSError):
                pass
            time.sleep(0.5)

        raise SandboxStartupError(
            f"Sandbox did not become ready within {self.startup_timeout}s"
        )

    def __enter__(self) -> "SandboxContext":
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()


@contextlib.contextmanager
def sandbox_context(
    *,
    rpc_port: int = 3030,
    near_cli: str = "near",
    startup_timeout: float = 30.0,
):
    """Context manager that starts a local NEAR sandbox, yields the context,
    and cleans up on exit.

    Usage::

        with sandbox_context() as ctx:
            deployer = ContractDeployer(ctx)
            deployer.deploy("contract.wasm", "app.test.near")
            alice = NearTestAccount.create(ctx, "alice.test.near")
            result = alice.call("app.test.near", "greet", {"name": "world"})
            assert_transaction_success(result)

    Parameters
    ----------
    rpc_port:
        Port for the sandbox RPC server (default 3030).
    near_cli:
        Path to the ``near`` CLI binary.
    startup_timeout:
        Maximum seconds to wait for the sandbox to become ready.
    """
    ctx = SandboxContext(
        rpc_port=rpc_port,
        near_cli=near_cli,
        startup_timeout=startup_timeout,
    )
    try:
        ctx.start()
        yield ctx
    finally:
        ctx.stop()


# ---------------------------------------------------------------------------
# ContractDeployer
# ---------------------------------------------------------------------------

class ContractDeployer:
    """Deploy WASM contracts to a sandbox.

    Usage::

        deployer = ContractDeployer(ctx)
        result = deployer.deploy(
            "target/wasm32-unknown-unknown/release/my_contract.wasm",
            account_id="contract.test.near",
            init_method="new",
            init_args={"owner_id": "contract.test.near"},
        )
    """

    def __init__(self, ctx: SandboxContext) -> None:
        self.ctx = ctx

    def deploy(
        self,
        wasm_path: Union[str, Path],
        account_id: str,
        *,
        init_method: Optional[str] = None,
        init_args: Optional[Dict[str, Any]] = None,
        init_deposit: str = "0",
        init_gas: str = "300000000000000",
    ) -> TransactionResult:
        """Deploy a contract and optionally call an init method.

        Parameters
        ----------
        wasm_path:
            Path to the compiled ``.wasm`` file.
        account_id:
            The account that will hold the contract.
        init_method:
            If provided, call this method immediately after deployment.
        init_args:
            JSON-serialisable arguments for the init method.
        init_deposit:
            Attached deposit for the init call (in NEAR).
        init_gas:
            Gas allowance for the init call.
        """
        wasm_path = Path(wasm_path).resolve()
        if not wasm_path.exists():
            raise ContractDeployError(f"WASM file not found: {wasm_path}")

        result = self.ctx.run_near_cli([
            "deploy",
            account_id,
            str(wasm_path),
            "--networkId", "localnet",
        ])

        if result.returncode != 0:
            raise ContractDeployError(
                f"Contract deployment failed: {result.stderr or result.stdout}"
            )

        deploy_result = _parse_cli_output(result.stdout, result.stderr)

        if init_method:
            args_json = json.dumps(init_args or {})
            init_result = self.ctx.run_near_cli([
                "call",
                account_id,
                init_method,
                args_json,
                "--accountId", account_id,
                "--deposit", init_deposit,
                "--gas", init_gas,
                "--networkId", "localnet",
            ])
            if init_result.returncode != 0:
                raise ContractDeployError(
                    f"Contract init ({init_method}) failed: "
                    f"{init_result.stderr or init_result.stdout}"
                )
            return _parse_cli_output(init_result.stdout, init_result.stderr)

        return deploy_result


# ---------------------------------------------------------------------------
# NearTestAccount
# ---------------------------------------------------------------------------

class NearTestAccount:
    """Create and manage funded test accounts on a sandbox.

    Usage::

        alice = NearTestAccount.create(ctx, "alice.test.near", initial_balance="100")
        result = alice.call("contract.test.near", "my_method", {"key": "value"})
    """

    def __init__(self, ctx: SandboxContext, account_id: str) -> None:
        self.ctx = ctx
        self.account_id = account_id

    @classmethod
    def create(
        cls,
        ctx: SandboxContext,
        account_id: str,
        *,
        initial_balance: str = "100",
    ) -> "NearTestAccount":
        """Create a new account with the given initial balance (in NEAR).

        Parameters
        ----------
        ctx:
            A running :class:`SandboxContext` instance.
        account_id:
            The account name to create (e.g. ``"alice.test.near"``).
        initial_balance:
            Starting balance in NEAR tokens.
        """
        result = ctx.run_near_cli([
            "create-account",
            account_id,
            "--masterAccount", "test.near",
            "--initialBalance", initial_balance,
            "--networkId", "localnet",
        ])
        if result.returncode != 0:
            raise NearTestingError(
                f"Failed to create account {account_id}: "
                f"{result.stderr or result.stdout}"
            )
        return cls(ctx, account_id)

    def call(
        self,
        contract_id: str,
        method: str,
        args: Optional[Dict[str, Any]] = None,
        *,
        deposit: str = "0",
        gas: str = "300000000000000",
    ) -> TransactionResult:
        """Send a function-call transaction signed by this account."""
        return call_contract(
            self.ctx,
            contract_id=contract_id,
            method=method,
            args=args,
            signer_id=self.account_id,
            deposit=deposit,
            gas=gas,
        )

    def view(
        self,
        contract_id: str,
        method: str,
        args: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Call a view method (no transaction needed)."""
        return view_contract(
            self.ctx,
            contract_id=contract_id,
            method=method,
            args=args,
        )

    def balance(self) -> Optional[str]:
        """Return the account balance in yoctoNEAR, or None on error."""
        result = self.ctx.run_near_cli([
            "state",
            self.account_id,
            "--networkId", "localnet",
        ])
        if result.returncode != 0:
            return None
        for line in (result.stdout + result.stderr).splitlines():
            stripped = line.strip()
            if "amount" in stripped.lower():
                for part in stripped.split("'"):
                    if part.isdigit():
                        return part
                for part in stripped.split('"'):
                    if part.isdigit():
                        return part
        return None

    def __repr__(self) -> str:
        return f"NearTestAccount({self.account_id!r})"


# ---------------------------------------------------------------------------
# Module-level helper functions
# ---------------------------------------------------------------------------

def call_contract(
    ctx: SandboxContext,
    *,
    contract_id: str,
    method: str,
    args: Optional[Dict[str, Any]] = None,
    signer_id: str,
    deposit: str = "0",
    gas: str = "300000000000000",
) -> TransactionResult:
    """Execute a change method on a contract deployed to the sandbox.

    Parameters
    ----------
    ctx:
        A running :class:`SandboxContext` instance.
    contract_id:
        The account ID where the contract is deployed.
    method:
        The contract method to call.
    args:
        JSON-serialisable arguments.
    signer_id:
        The account signing the transaction.
    deposit:
        Attached deposit in NEAR.
    gas:
        Gas allowance in yoctoNEAR units.
    """
    args_json = json.dumps(args or {})
    result = ctx.run_near_cli([
        "call",
        contract_id,
        method,
        args_json,
        "--accountId", signer_id,
        "--deposit", deposit,
        "--gas", gas,
        "--networkId", "localnet",
    ])
    tx_result = _parse_cli_output(result.stdout, result.stderr)
    if result.returncode != 0:
        tx_result.status = "failure"
    return tx_result


def view_contract(
    ctx: SandboxContext,
    *,
    contract_id: str,
    method: str,
    args: Optional[Dict[str, Any]] = None,
) -> Any:
    """Call a view-only method on a contract (no gas, no signer required).

    Parameters
    ----------
    ctx:
        A running :class:`SandboxContext` instance.
    contract_id:
        The account ID where the contract is deployed.
    method:
        The view method name.
    args:
        JSON-serialisable arguments.
    """
    cmd = ["view", contract_id, method]
    if args:
        cmd.append(json.dumps(args))
    cmd += ["--networkId", "localnet"]

    result = ctx.run_near_cli(cmd)
    if result.returncode != 0:
        raise TransactionError(
            f"View call {contract_id}.{method} failed: "
            f"{result.stderr or result.stdout}"
        )

    output = (result.stdout or "").strip()
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return output


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def assert_transaction_success(result: TransactionResult) -> None:
    """Assert that a transaction completed successfully.

    Raises :class:`AssertionError` with details if the transaction failed.
    """
    if not result.succeeded:
        raise AssertionError(
            f"Expected transaction {result.transaction_hash} to succeed, "
            f"but status was '{result.status}'.\n"
            f"Logs: {result.logs}\n"
            f"Raw: {json.dumps(result.raw, indent=2)}"
        )


def assert_transaction_failure(result: TransactionResult) -> None:
    """Assert that a transaction failed.

    Useful for testing that invalid operations are correctly rejected.
    """
    if result.succeeded:
        raise AssertionError(
            f"Expected transaction {result.transaction_hash} to fail, "
            f"but it succeeded.\n"
            f"Logs: {result.logs}"
        )


def assert_event_emitted(
    result: TransactionResult,
    event: str,
    *,
    standard: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assert that a NEP-297 event was emitted in the transaction logs.

    Parameters
    ----------
    result:
        The transaction result to inspect.
    event:
        The expected ``event`` field value (e.g. ``"nft_mint"``).
    standard:
        If given, also match the ``standard`` field (e.g. ``"nep171"``).
    data:
        If given, verify that the event data contains at least these
        key-value pairs (subset match).

    Returns
    -------
    dict
        The first matching event object.
    """
    for evt in result.events:
        if evt.get("event") != event:
            continue
        if standard is not None and evt.get("standard") != standard:
            continue
        if data is not None:
            evt_data = evt.get("data", [{}])
            if isinstance(evt_data, list):
                if not any(_is_subset(data, entry) for entry in evt_data):
                    continue
            elif not _is_subset(data, evt_data):
                continue
        return evt

    raise AssertionError(
        f"Event '{event}' not found in transaction {result.transaction_hash}.\n"
        f"Emitted events: {result.events}\n"
        f"Raw logs: {result.logs}"
    )


def assert_log_contains(result: TransactionResult, substring: str) -> str:
    """Assert that at least one log line contains the given substring.

    Returns the first matching log line.
    """
    for log_line in result.logs:
        if substring in log_line:
            return log_line
    raise AssertionError(
        f"No log line contains '{substring}'.\n"
        f"Logs: {result.logs}"
    )


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------

def _is_subset(subset: Dict[str, Any], superset: Dict[str, Any]) -> bool:
    """Return True if every key in *subset* exists in *superset* with the same value."""
    for key, value in subset.items():
        if key not in superset or superset[key] != value:
            return False
    return True


def _parse_cli_output(stdout: str, stderr: str) -> TransactionResult:
    """Best-effort parser for near-cli text/JSON output."""
    combined = (stdout or "") + "\n" + (stderr or "")

    tx_hash = ""
    status = "success"
    logs: List[str] = []
    raw: Dict[str, Any] = {}

    for line in combined.splitlines():
        stripped = line.strip()

        if "Transaction Id" in stripped or "transaction_hash" in stripped:
            parts = stripped.split()
            for part in parts:
                if len(part) == 44 and part.isalnum():
                    tx_hash = part
                    break

        if stripped.startswith("Log [") or stripped.startswith("Receipt:"):
            logs.append(stripped)

        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
                raw = parsed
                if "transaction_outcome" in parsed:
                    outcome = parsed["transaction_outcome"].get("outcome", {})
                    tx_hash = tx_hash or parsed.get("transaction", {}).get("hash", "")
                    logs.extend(outcome.get("logs", []))
                if "status" in parsed:
                    s = parsed["status"]
                    if isinstance(s, dict) and "Failure" in s:
                        status = "failure"
            except json.JSONDecodeError:
                pass

    failure_indicators = ["error", "failure", "failed", "panic"]
    lower_combined = combined.lower()
    if any(indicator in lower_combined for indicator in failure_indicators):
        if "success" not in lower_combined:
            status = "failure"

    return TransactionResult(
        transaction_hash=tx_hash,
        status=status,
        logs=logs,
        raw=raw,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Core classes
    "NearTestAccount",
    "ContractDeployer",
    "MockRPC",
    "SandboxContext",
    "TransactionResult",
    # Context manager
    "sandbox_context",
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
