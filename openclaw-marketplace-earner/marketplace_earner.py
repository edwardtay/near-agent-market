#!/usr/bin/env python3
"""
OpenClaw Skill: NEAR Marketplace Earner

Enables agents to browse, bid on, and complete jobs from the NEAR Agent
Marketplace. The bridge that lets every OpenClaw agent earn NEAR.

Commands:
    near_jobs_browse  — Browse available marketplace jobs
    near_jobs_match   — Match jobs to agent skills
    near_bid_place    — Place a bid on a job
    near_bid_status   — Check status of placed bids
    near_submit_work  — Submit deliverable for completed work
    near_earnings     — Earnings dashboard

Environment:
    NEAR_MARKET_API_KEY — Your marketplace API key
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# ─── Config ────────────────────────────────────────────────────────

BASE_URL = "https://market.near.ai/v1"
API_KEY = os.environ.get("NEAR_MARKET_API_KEY", "")
DEFAULT_SKILLS = ["python", "near", "automation", "ai_agents", "web_dev"]


# ─── Exceptions ────────────────────────────────────────────────────

class MarketplaceError(Exception):
    """Raised when a marketplace API call fails."""


class ConfigurationError(Exception):
    """Raised when required config is missing."""


# ─── HTTP Helpers ──────────────────────────────────────────────────

def _api_request(method: str, endpoint: str, data: dict | None = None,
                 api_key: str | None = None) -> Any:
    """Make an authenticated request to the NEAR marketplace API."""
    key = api_key or API_KEY
    if not key:
        raise ConfigurationError(
            "NEAR_MARKET_API_KEY not set. "
            "Export it or pass api_key to the skill."
        )

    url = f"{BASE_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    body = json.dumps(data).encode() if data else None
    req = Request(url, data=body, method=method, headers=headers)

    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode()
        except Exception:
            pass
        raise MarketplaceError(
            f"API {method} {endpoint} returned {e.code}: {error_body}"
        ) from e
    except URLError as e:
        raise MarketplaceError(f"Network error: {e}") from e
    except json.JSONDecodeError as e:
        raise MarketplaceError(f"Invalid JSON response: {e}") from e


def api_get(endpoint: str, **kwargs) -> Any:
    return _api_request("GET", endpoint, **kwargs)


def api_post(endpoint: str, data: dict, **kwargs) -> Any:
    return _api_request("POST", endpoint, data=data, **kwargs)


# ─── Skill Class ───────────────────────────────────────────────────

class MarketplaceEarnerSkill:
    """OpenClaw skill for earning NEAR through the agent marketplace."""

    name = "near_marketplace_earner"
    version = "1.0.0"
    description = "Browse, bid on, and complete NEAR marketplace jobs"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or API_KEY
        self._commands = {}
        self._register_commands()

    def _register_commands(self):
        """Register all skill commands."""
        self._commands = {
            "near_jobs_browse": self.near_jobs_browse,
            "near_jobs_match": self.near_jobs_match,
            "near_bid_place": self.near_bid_place,
            "near_bid_status": self.near_bid_status,
            "near_submit_work": self.near_submit_work,
            "near_earnings": self.near_earnings,
        }

    def execute(self, command: str, **kwargs) -> dict:
        """Execute a skill command by name."""
        if command not in self._commands:
            return {"error": f"Unknown command: {command}", "available": list(self._commands.keys())}
        try:
            return self._commands[command](**kwargs)
        except (MarketplaceError, ConfigurationError) as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Unexpected error: {e}"}

    # ─── Commands ──────────────────────────────────────────────────

    def near_jobs_browse(self, status: str = "open", limit: int = 20,
                         min_budget: float = 0, tags: list | None = None) -> dict:
        """Browse available marketplace jobs.

        Args:
            status: Job status filter (open, in_progress, completed)
            limit: Max number of jobs to return
            min_budget: Minimum budget in NEAR
            tags: Optional list of tags to filter by

        Returns:
            Dict with jobs list and summary stats
        """
        jobs = api_get(f"/jobs?status={status}&limit={limit}", api_key=self.api_key)

        if not isinstance(jobs, list):
            return {"jobs": [], "total": 0}

        # Apply local filters
        filtered = []
        for job in jobs:
            budget = float(job.get("budget_amount") or 0)
            if budget < min_budget:
                continue
            if tags:
                job_tags = {t.lower() for t in job.get("tags", [])}
                if not any(t.lower() in job_tags for t in tags):
                    continue
            filtered.append({
                "job_id": job["job_id"],
                "title": job.get("title", ""),
                "budget": budget,
                "bid_count": job.get("bid_count", 0),
                "tags": job.get("tags", []),
                "status": job.get("status", ""),
                "description": (job.get("description") or "")[:200],
            })

        # Sort by budget descending
        filtered.sort(key=lambda j: j["budget"], reverse=True)

        return {
            "jobs": filtered,
            "total": len(filtered),
            "total_budget": sum(j["budget"] for j in filtered),
        }

    def near_jobs_match(self, skills: list | None = None,
                        min_budget: float = 0, max_bids: int = 10) -> dict:
        """Match available jobs to agent's registered skills.

        Args:
            skills: List of skills to match against job tags
            min_budget: Minimum budget in NEAR
            max_bids: Skip jobs with more than this many competing bids

        Returns:
            Dict with matched jobs sorted by relevance score
        """
        skill_set = {s.lower() for s in (skills or DEFAULT_SKILLS)}
        jobs = api_get("/jobs?status=open&limit=100", api_key=self.api_key)

        if not isinstance(jobs, list):
            return {"matches": [], "total": 0}

        matches = []
        for job in jobs:
            budget = float(job.get("budget_amount") or 0)
            bid_count = job.get("bid_count", 0)

            if budget < min_budget or bid_count > max_bids:
                continue

            job_tags = {t.lower() for t in job.get("tags", [])}
            overlap = skill_set & job_tags

            if overlap:
                # Score: more skill matches + higher budget + fewer bids = better
                score = len(overlap) * 10 + budget - bid_count * 2
                matches.append({
                    "job_id": job["job_id"],
                    "title": job.get("title", ""),
                    "budget": budget,
                    "bid_count": bid_count,
                    "tags": job.get("tags", []),
                    "matched_skills": list(overlap),
                    "match_score": round(score, 1),
                })

        matches.sort(key=lambda m: m["match_score"], reverse=True)

        return {
            "matches": matches,
            "total": len(matches),
            "skills_used": list(skill_set),
        }

    def near_bid_place(self, job_id: str, amount: float,
                       proposal: str | None = None,
                       eta_hours: int = 24) -> dict:
        """Place a bid on a marketplace job.

        Args:
            job_id: The job ID to bid on
            amount: Bid amount in NEAR
            proposal: Your proposal text (auto-generated if not provided)
            eta_hours: Delivery estimate in hours

        Returns:
            Dict with bid confirmation or error
        """
        if amount <= 0:
            return {"error": "Bid amount must be positive"}

        if not proposal:
            proposal = (
                "Will deliver a production-quality implementation with clean code, "
                "error handling, testing, and full documentation. "
                "Already have NEAR marketplace API integration working "
                f"and can deliver within {eta_hours} hours."
            )

        result = api_post(f"/jobs/{job_id}/bids", {
            "amount": str(amount),
            "eta_seconds": eta_hours * 3600,
            "proposal": proposal,
        }, api_key=self.api_key)

        if result and "bid_id" in result:
            return {
                "success": True,
                "bid_id": result["bid_id"],
                "job_id": job_id,
                "amount": amount,
                "eta_hours": eta_hours,
            }

        return {"success": False, "error": "Failed to place bid", "response": result}

    def near_bid_status(self, bid_id: str | None = None) -> dict:
        """Check status of placed bids.

        Args:
            bid_id: Specific bid ID to check, or None for all bids

        Returns:
            Dict with bid statuses grouped by status
        """
        bids = api_get("/agents/me/bids", api_key=self.api_key)

        if not isinstance(bids, list):
            return {"bids": [], "total": 0}

        if bid_id:
            bids = [b for b in bids if b.get("bid_id") == bid_id]

        grouped = {"accepted": [], "pending": [], "rejected": []}
        for bid in bids:
            status = bid.get("status", "unknown")
            entry = {
                "bid_id": bid["bid_id"],
                "job_id": bid.get("job_id", ""),
                "amount": float(bid.get("amount", 0)),
                "status": status,
                "created_at": bid.get("created_at", ""),
            }
            if status in grouped:
                grouped[status].append(entry)

        return {
            "bids": grouped,
            "summary": {k: len(v) for k, v in grouped.items()},
            "total": len(bids),
        }

    def near_submit_work(self, job_id: str, deliverable_url: str,
                         description: str = "") -> dict:
        """Submit deliverable URL and hash for completed work.

        Args:
            job_id: The job to submit work for
            deliverable_url: URL to the deliverable (GitHub repo, file, etc.)
            description: Optional description of what was delivered

        Returns:
            Dict with submission confirmation
        """
        # Generate SHA-256 hash of the URL for verification
        deliverable_hash = "sha256:" + hashlib.sha256(
            deliverable_url.encode()
        ).hexdigest()

        result = api_post(f"/jobs/{job_id}/submit", {
            "deliverable_url": deliverable_url,
            "deliverable_hash": deliverable_hash,
        }, api_key=self.api_key)

        if result:
            return {
                "success": True,
                "job_id": job_id,
                "deliverable_url": deliverable_url,
                "deliverable_hash": deliverable_hash,
                "description": description,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            }

        return {"success": False, "error": f"Failed to submit work for job {job_id}"}

    def near_earnings(self) -> dict:
        """Show earnings dashboard — balance, completed jobs, pending income.

        Returns:
            Dict with comprehensive earnings breakdown
        """
        bids = api_get("/agents/me/bids", api_key=self.api_key)
        wallet = {}
        try:
            wallet = api_get("/wallet/balance", api_key=self.api_key)
        except MarketplaceError:
            pass

        if not isinstance(bids, list):
            bids = []

        accepted = [b for b in bids if b["status"] == "accepted"]
        pending = [b for b in bids if b["status"] == "pending"]
        rejected = [b for b in bids if b["status"] == "rejected"]

        total_won = sum(float(b.get("amount", 0)) for b in accepted)
        total_pending = sum(float(b.get("amount", 0)) for b in pending)
        total_rejected = sum(float(b.get("amount", 0)) for b in rejected)
        balance = wallet.get("balance", "0") if isinstance(wallet, dict) else "0"

        win_count = len(accepted)
        loss_count = len(rejected)
        win_rate = win_count / max(1, win_count + loss_count) * 100

        return {
            "wallet_balance": balance,
            "total_won": total_won,
            "total_pending": total_pending,
            "total_bids": len(bids),
            "accepted": win_count,
            "pending": len(pending),
            "rejected": loss_count,
            "win_rate": f"{win_rate:.1f}%",
            "avg_bid_size": round(total_won / max(1, win_count), 1),
            "accepted_jobs": [
                {"job_id": b["job_id"], "amount": float(b["amount"])}
                for b in accepted
            ],
        }


# ─── CLI Interface ─────────────────────────────────────────────────

def main():
    """CLI entry point for testing skill commands."""
    skill = MarketplaceEarnerSkill()

    if len(sys.argv) < 2:
        print("NEAR Marketplace Earner Skill")
        print(f"Version: {skill.version}")
        print(f"\nCommands: {', '.join(skill._commands.keys())}")
        print(f"\nUsage: python {sys.argv[0]} <command> [json_kwargs]")
        print(f"\nExamples:")
        print(f'  python {sys.argv[0]} near_jobs_browse')
        print(f'  python {sys.argv[0]} near_jobs_match \'{{"skills": ["python", "near"]}}\'')
        print(f'  python {sys.argv[0]} near_bid_place \'{{"job_id": "abc", "amount": 8.0}}\'')
        print(f'  python {sys.argv[0]} near_earnings')
        return

    command = sys.argv[1]
    kwargs = {}
    if len(sys.argv) > 2:
        try:
            kwargs = json.loads(sys.argv[2])
        except json.JSONDecodeError:
            print(f"Invalid JSON kwargs: {sys.argv[2]}")
            return

    result = skill.execute(command, **kwargs)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
