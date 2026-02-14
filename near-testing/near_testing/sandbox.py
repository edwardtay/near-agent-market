"""
near_testing.sandbox
~~~~~~~~~~~~~~~~~~~~

Core module for NEAR smart contract testing. Provides a local sandbox
environment, contract deployment, account management, and assertion helpers.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


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
# Transaction / receipt helpers
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
# NearSandbox
# ---------------------------------------------------------------------------

class NearSandbox:
    """Manage a local NEAR sandbox node for integration testing.

    Usage::

        sandbox = NearSandbox()
        sandbox.start()
        # ... run tests ...
        sandbox.stop()

    Or as a context manager::

        with NearSandbox() as sandbox:
            deployer = ContractDeployer(sandbox)
            deployer.deploy("contract.wasm", "my-contract.test.near")
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

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> "NearSandbox":
        """Initialise and start the sandbox node.

        Raises :class:`SandboxStartupError` if the node does not become
        ready within *startup_timeout* seconds.
        """
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

    # -- context manager -----------------------------------------------------

    def __enter__(self) -> "NearSandbox":
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    # -- CLI wrappers --------------------------------------------------------

    def run_near_cli(
        self,
        args: List[str],
        *,
        capture_output: bool = True,
        timeout: float = 60.0,
        env_extra: Optional[Dict[str, str]] = None,
    ) -> subprocess.CompletedProcess:
        """Run a ``near`` CLI command against this sandbox.

        The ``NEAR_ENV`` and ``NEAR_CLI_LOCALNET_RPC_SERVER_URL`` environment
        variables are set automatically.
        """
        env = os.environ.copy()
        env["NEAR_ENV"] = "localnet"
        env["NEAR_CLI_LOCALNET_RPC_SERVER_URL"] = self.rpc_url
        env["NEAR_HOME"] = str(self.home_dir)
        if env_extra:
            env.update(env_extra)

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

    # -- internal ------------------------------------------------------------

    def _init_sandbox(self) -> None:
        """Run ``neard --home <dir> init`` to bootstrap the sandbox."""
        neard = shutil.which("neard") or shutil.which("near-sandbox")
        if neard is None:
            raise SandboxStartupError(
                "Neither 'neard' nor 'near-sandbox' binary found on PATH. "
                "Install nearcore or near-sandbox to use NearSandbox."
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

        # Patch config.json to use the requested RPC port
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


# ---------------------------------------------------------------------------
# ContractDeployer
# ---------------------------------------------------------------------------

class ContractDeployer:
    """Deploy WASM contracts to a :class:`NearSandbox`.

    Usage::

        deployer = ContractDeployer(sandbox)
        result = deployer.deploy(
            "target/wasm32-unknown-unknown/release/my_contract.wasm",
            account_id="contract.test.near",
        )
    """

    def __init__(self, sandbox: NearSandbox) -> None:
        self.sandbox = sandbox

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
            If provided, call this method immediately after deployment (e.g.
            ``"new"`` or ``"init"``).
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

        # Deploy
        result = self.sandbox.run_near_cli([
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

        # Optional init call
        if init_method:
            args_json = json.dumps(init_args or {})
            init_result = self.sandbox.run_near_cli([
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
# TestAccount
# ---------------------------------------------------------------------------

class TestAccount:
    """Create and manage funded test accounts on the sandbox.

    Usage::

        alice = TestAccount.create(sandbox, "alice.test.near", initial_balance="100")
        result = alice.call("contract.test.near", "my_method", {"key": "value"})
    """

    def __init__(
        self,
        sandbox: NearSandbox,
        account_id: str,
    ) -> None:
        self.sandbox = sandbox
        self.account_id = account_id

    @classmethod
    def create(
        cls,
        sandbox: NearSandbox,
        account_id: str,
        *,
        initial_balance: str = "100",
    ) -> "TestAccount":
        """Create a new account with the given initial balance (in NEAR).

        Parameters
        ----------
        sandbox:
            A running :class:`NearSandbox` instance.
        account_id:
            The account name to create (e.g. ``"alice.test.near"``).
        initial_balance:
            Starting balance in NEAR tokens.
        """
        result = sandbox.run_near_cli([
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
        return cls(sandbox, account_id)

    # -- convenience wrappers ------------------------------------------------

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
            self.sandbox,
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
            self.sandbox,
            contract_id=contract_id,
            method=method,
            args=args,
        )

    def balance(self) -> Optional[str]:
        """Return the account balance in NEAR (as a string), or None on error."""
        result = self.sandbox.run_near_cli([
            "state",
            self.account_id,
            "--networkId", "localnet",
        ])
        if result.returncode != 0:
            return None
        # Parse the amount from CLI output
        for line in (result.stdout + result.stderr).splitlines():
            stripped = line.strip()
            if "amount" in stripped.lower():
                # Try to extract a quoted numeric value
                for part in stripped.split("'"):
                    if part.isdigit():
                        return part
                for part in stripped.split('"'):
                    if part.isdigit():
                        return part
        return None

    def __repr__(self) -> str:
        return f"TestAccount({self.account_id!r})"


# ---------------------------------------------------------------------------
# Module-level helper functions
# ---------------------------------------------------------------------------

def call_contract(
    sandbox: NearSandbox,
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
    sandbox:
        A running :class:`NearSandbox` instance.
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

    Returns
    -------
    TransactionResult
        The parsed transaction outcome.
    """
    args_json = json.dumps(args or {})
    result = sandbox.run_near_cli([
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
    sandbox: NearSandbox,
    *,
    contract_id: str,
    method: str,
    args: Optional[Dict[str, Any]] = None,
) -> Any:
    """Call a view-only method on a contract (no gas, no signer required).

    Parameters
    ----------
    sandbox:
        A running :class:`NearSandbox` instance.
    contract_id:
        The account ID where the contract is deployed.
    method:
        The view method name.
    args:
        JSON-serialisable arguments.

    Returns
    -------
    Any
        The deserialised return value from the contract.
    """
    cmd = [
        "view",
        contract_id,
        method,
    ]
    if args:
        cmd.append(json.dumps(args))
    cmd += ["--networkId", "localnet"]

    result = sandbox.run_near_cli(cmd)
    if result.returncode != 0:
        raise TransactionError(
            f"View call {contract_id}.{method} failed: "
            f"{result.stderr or result.stdout}"
        )

    # Attempt to parse JSON from stdout
    output = (result.stdout or "").strip()
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        # near-cli sometimes wraps the value in extra text; return raw string
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

    Raises
    ------
    AssertionError
        If no matching event is found.
    """
    for evt in result.events:
        if evt.get("event") != event:
            continue
        if standard is not None and evt.get("standard") != standard:
            continue
        if data is not None:
            evt_data = evt.get("data", [{}])
            # NEP-297 data is typically a list; check each entry
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

    # Try to extract JSON from output
    for line in combined.splitlines():
        stripped = line.strip()

        # Detect transaction hash
        if "Transaction Id" in stripped or "transaction_hash" in stripped:
            parts = stripped.split()
            for part in parts:
                if len(part) == 44 and part.isalnum():
                    tx_hash = part
                    break

        # Collect log lines
        if stripped.startswith("Log [") or stripped.startswith("Receipt:"):
            logs.append(stripped)

        # Try JSON parse for structured output
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

    # Detect failures from text output
    failure_indicators = ["error", "failure", "failed", "panic"]
    lower_combined = combined.lower()
    if any(indicator in lower_combined for indicator in failure_indicators):
        # Only mark as failure if there is no explicit success indicator
        if "success" not in lower_combined:
            status = "failure"

    return TransactionResult(
        transaction_hash=tx_hash,
        status=status,
        logs=logs,
        raw=raw,
    )
