#!/usr/bin/env python3
"""
OpenClaw Skill: NEAR Scheduled Tasks

Schedule recurring NEAR operations — staking rewards claims,
DeFi rebalancing, recurring payments, and balance checks.

Commands:
    near_schedule_task    — Schedule a recurring task
    near_schedule_list    — List all scheduled tasks
    near_schedule_remove  — Remove a scheduled task
    near_schedule_history — View execution history
    near_schedule_run     — Run the scheduler (execute due tasks)

Environment:
    NEAR_ACCOUNT_ID  — Your NEAR account
    NEAR_RPC_URL     — RPC endpoint (default: mainnet)
"""

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ─── Config ────────────────────────────────────────────────────────

NEAR_ACCOUNT = os.environ.get("NEAR_ACCOUNT_ID", "")
NEAR_RPC = os.environ.get("NEAR_RPC_URL", "https://rpc.mainnet.near.org")
SCHEDULE_FILE = Path.home() / ".near_schedules.json"
HISTORY_FILE = Path.home() / ".near_schedule_history.json"


# ─── Cron Parser ───────────────────────────────────────────────────

class CronExpression:
    """Simple cron expression parser (minute hour day month weekday)."""

    def __init__(self, expr: str):
        parts = expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Cron needs 5 fields (min hr day mon wday), got {len(parts)}: {expr}")
        self.minute = self._parse_field(parts[0], 0, 59)
        self.hour = self._parse_field(parts[1], 0, 23)
        self.day = self._parse_field(parts[2], 1, 31)
        self.month = self._parse_field(parts[3], 1, 12)
        self.weekday = self._parse_field(parts[4], 0, 6)  # 0=Mon
        self.raw = expr

    @staticmethod
    def _parse_field(field: str, min_val: int, max_val: int) -> set[int]:
        """Parse a single cron field into a set of valid values."""
        if field == "*":
            return set(range(min_val, max_val + 1))

        values = set()
        for part in field.split(","):
            if "/" in part:
                base, step = part.split("/", 1)
                start = min_val if base == "*" else int(base)
                values.update(range(start, max_val + 1, int(step)))
            elif "-" in part:
                lo, hi = part.split("-", 1)
                values.update(range(int(lo), int(hi) + 1))
            else:
                values.add(int(part))

        return values

    def matches(self, dt: datetime) -> bool:
        """Check if a datetime matches this cron expression."""
        return (
            dt.minute in self.minute
            and dt.hour in self.hour
            and dt.day in self.day
            and dt.month in self.month
            and dt.weekday() in self.weekday
        )

    def next_run(self, after: datetime | None = None) -> str:
        """Estimate next run time (approximate, for display)."""
        now = after or datetime.now(timezone.utc)
        # Simple brute force: check next 48 hours minute by minute
        from datetime import timedelta
        check = now.replace(second=0, microsecond=0)
        for _ in range(48 * 60):
            check += timedelta(minutes=1)
            if self.matches(check):
                return check.strftime("%Y-%m-%d %H:%M UTC")
        return "unknown"


# ─── NEAR RPC Client ──────────────────────────────────────────────

def rpc_call(method: str, params: dict) -> dict:
    """Make a NEAR JSON-RPC call."""
    payload = {
        "jsonrpc": "2.0",
        "id": "scheduler",
        "method": method,
        "params": params,
    }
    req = Request(
        NEAR_RPC,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if "error" in result:
                return {"error": result["error"]}
            return result.get("result", {})
    except (HTTPError, URLError, json.JSONDecodeError) as e:
        return {"error": str(e)}


def view_account(account_id: str) -> dict:
    """Get NEAR account balance and info."""
    return rpc_call("query", {
        "request_type": "view_account",
        "finality": "final",
        "account_id": account_id,
    })


def view_call(contract: str, method: str, args: dict | None = None) -> dict:
    """Call a view method on a NEAR contract."""
    import base64
    args_b64 = base64.b64encode(json.dumps(args or {}).encode()).decode()
    return rpc_call("query", {
        "request_type": "call_function",
        "finality": "final",
        "account_id": contract,
        "method_name": method,
        "args_base64": args_b64,
    })


def yocto_to_near(yocto: str | int) -> float:
    """Convert yoctoNEAR to NEAR."""
    return int(yocto) / 1e24


# ─── Storage ───────────────────────────────────────────────────────

def load_schedules() -> list[dict]:
    if SCHEDULE_FILE.exists():
        try:
            return json.loads(SCHEDULE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return []


def save_schedules(schedules: list[dict]):
    SCHEDULE_FILE.write_text(json.dumps(schedules, indent=2))


def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return []


def save_history(history: list[dict]):
    # Keep last 500 entries
    HISTORY_FILE.write_text(json.dumps(history[-500:], indent=2))


# ─── Task Executors ────────────────────────────────────────────────

def execute_check_balance(params: dict) -> dict:
    """Check and log account balance."""
    account = params.get("account_id", NEAR_ACCOUNT)
    if not account:
        return {"error": "No account_id specified"}

    result = view_account(account)
    if "error" in result:
        return result

    balance = yocto_to_near(result.get("amount", 0))
    staked = yocto_to_near(result.get("locked", 0))

    return {
        "account": account,
        "balance_near": round(balance, 4),
        "staked_near": round(staked, 4),
        "storage_used": result.get("storage_usage", 0),
    }


def execute_claim_rewards(params: dict) -> dict:
    """Check staking rewards (view-only — actual claim requires signing)."""
    account = params.get("account_id", NEAR_ACCOUNT)
    validator = params.get("validator", "")

    if not account:
        return {"error": "No account_id specified"}

    result = view_account(account)
    if "error" in result:
        return result

    balance = yocto_to_near(result.get("amount", 0))
    staked = yocto_to_near(result.get("locked", 0))

    return {
        "account": account,
        "balance_near": round(balance, 4),
        "staked_near": round(staked, 4),
        "validator": validator or "check manually",
        "note": "View-only check. To claim, sign a transaction via near-cli or wallet.",
    }


def execute_transfer(params: dict) -> dict:
    """Log a transfer intent (actual transfer requires signing)."""
    receiver = params.get("receiver_id", "")
    amount = params.get("amount_near", 0)

    if not receiver or not amount:
        return {"error": "Need receiver_id and amount_near"}

    return {
        "action": "transfer",
        "from": NEAR_ACCOUNT,
        "to": receiver,
        "amount_near": amount,
        "note": "Transfer logged. Execute via near-cli: near send {from} {to} {amount}",
    }


def execute_rebalance(params: dict) -> dict:
    """Check balances and suggest rebalancing."""
    account = params.get("account_id", NEAR_ACCOUNT)
    if not account:
        return {"error": "No account_id specified"}

    result = view_account(account)
    if "error" in result:
        return result

    balance = yocto_to_near(result.get("amount", 0))
    staked = yocto_to_near(result.get("locked", 0))
    total = balance + staked

    target_stake_pct = params.get("target_stake_pct", 70)
    current_stake_pct = (staked / total * 100) if total > 0 else 0

    suggestion = "balanced"
    if current_stake_pct < target_stake_pct - 5:
        diff = (target_stake_pct / 100 * total) - staked
        suggestion = f"stake {diff:.2f} more NEAR"
    elif current_stake_pct > target_stake_pct + 5:
        diff = staked - (target_stake_pct / 100 * total)
        suggestion = f"unstake {diff:.2f} NEAR"

    return {
        "account": account,
        "balance_near": round(balance, 4),
        "staked_near": round(staked, 4),
        "total_near": round(total, 4),
        "current_stake_pct": round(current_stake_pct, 1),
        "target_stake_pct": target_stake_pct,
        "suggestion": suggestion,
    }


EXECUTORS = {
    "check_balance": execute_check_balance,
    "claim_rewards": execute_claim_rewards,
    "transfer": execute_transfer,
    "rebalance": execute_rebalance,
}


# ─── Skill Commands ───────────────────────────────────────────────

def near_schedule_task(task_type: str, cron: str, params: dict | None = None) -> dict:
    """Schedule a recurring NEAR task.

    Args:
        task_type: One of check_balance, claim_rewards, transfer, rebalance
        cron: Cron expression (min hr day mon wday)
        params: Task-specific parameters

    Returns:
        Dict with schedule confirmation
    """
    if task_type not in EXECUTORS:
        return {"error": f"Unknown task type: {task_type}", "available": list(EXECUTORS.keys())}

    try:
        cron_expr = CronExpression(cron)
    except ValueError as e:
        return {"error": str(e)}

    task_id = str(uuid.uuid4())[:8]
    schedules = load_schedules()

    entry = {
        "task_id": task_id,
        "task_type": task_type,
        "cron": cron,
        "params": params or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "enabled": True,
    }

    schedules.append(entry)
    save_schedules(schedules)

    return {
        "success": True,
        "task_id": task_id,
        "task_type": task_type,
        "cron": cron,
        "next_run": cron_expr.next_run(),
    }


def near_schedule_list() -> dict:
    """List all scheduled tasks with next run times."""
    schedules = load_schedules()
    tasks = []

    for s in schedules:
        if not s.get("enabled", True):
            continue
        try:
            cron_expr = CronExpression(s["cron"])
            next_run = cron_expr.next_run()
        except ValueError:
            next_run = "invalid cron"

        tasks.append({
            "task_id": s["task_id"],
            "task_type": s["task_type"],
            "cron": s["cron"],
            "next_run": next_run,
            "params": s.get("params", {}),
        })

    return {"tasks": tasks, "total": len(tasks)}


def near_schedule_remove(task_id: str) -> dict:
    """Remove a scheduled task by ID."""
    schedules = load_schedules()
    original_count = len(schedules)
    schedules = [s for s in schedules if s["task_id"] != task_id]

    if len(schedules) == original_count:
        return {"error": f"Task {task_id} not found"}

    save_schedules(schedules)
    return {"success": True, "removed": task_id}


def near_schedule_history(limit: int = 20) -> dict:
    """View execution history of scheduled tasks."""
    history = load_history()
    return {
        "history": history[-limit:],
        "total": len(history),
    }


def near_schedule_run() -> dict:
    """Run the scheduler — execute all due tasks."""
    schedules = load_schedules()
    history = load_history()
    now = datetime.now(timezone.utc)
    executed = []

    for schedule in schedules:
        if not schedule.get("enabled", True):
            continue

        try:
            cron_expr = CronExpression(schedule["cron"])
        except ValueError:
            continue

        if not cron_expr.matches(now):
            continue

        task_type = schedule["task_type"]
        executor = EXECUTORS.get(task_type)
        if not executor:
            continue

        print(f"Executing: {task_type} (task {schedule['task_id']})")

        try:
            result = executor(schedule.get("params", {}))
            status = "error" if "error" in result else "success"
        except Exception as e:
            result = {"error": str(e)}
            status = "error"

        entry = {
            "task_id": schedule["task_id"],
            "task_type": task_type,
            "executed_at": now.isoformat(),
            "status": status,
            "result": result,
        }
        history.append(entry)
        executed.append(entry)

    save_history(history)

    return {
        "executed": len(executed),
        "results": executed,
        "timestamp": now.isoformat(),
    }


# ─── CLI ───────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("NEAR Scheduled Tasks Skill")
        print(f"\nCommands:")
        print(f"  schedule <type> <cron> [params_json]  — Schedule a task")
        print(f"  list                                   — List scheduled tasks")
        print(f"  remove <task_id>                       — Remove a task")
        print(f"  history [limit]                        — View execution history")
        print(f"  run                                    — Execute due tasks now")
        print(f"\nTask types: {', '.join(EXECUTORS.keys())}")
        print(f"\nExamples:")
        print(f'  python {sys.argv[0]} schedule check_balance "0 */6 * * *"')
        print(f'  python {sys.argv[0]} schedule rebalance "0 9 * * 1" \'{{"target_stake_pct": 70}}\'')
        print(f'  python {sys.argv[0]} list')
        print(f'  python {sys.argv[0]} run')
        return

    cmd = sys.argv[1]

    if cmd == "schedule":
        if len(sys.argv) < 4:
            print("Usage: schedule <task_type> <cron> [params_json]")
            return
        task_type = sys.argv[2]
        cron = sys.argv[3]
        params = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
        print(json.dumps(near_schedule_task(task_type, cron, params), indent=2))

    elif cmd == "list":
        print(json.dumps(near_schedule_list(), indent=2))

    elif cmd == "remove":
        if len(sys.argv) < 3:
            print("Usage: remove <task_id>")
            return
        print(json.dumps(near_schedule_remove(sys.argv[2]), indent=2))

    elif cmd == "history":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        print(json.dumps(near_schedule_history(limit), indent=2))

    elif cmd == "run":
        print(json.dumps(near_schedule_run(), indent=2))

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
