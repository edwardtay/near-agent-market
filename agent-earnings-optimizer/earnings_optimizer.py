#!/usr/bin/env python3
"""
NEAR Agent Marketplace - Earnings Optimizer

Analyzes agent performance on the NEAR Agent Marketplace and provides
actionable recommendations to increase win rate and earnings.

Usage:
    python earnings_optimizer.py --api-key sk_live_... [--agent-id UUID]
    python earnings_optimizer.py --env          # reads from .env.local
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE_URL = "https://market.near.ai/v1"


def api_get(endpoint: str, api_key: str) -> dict | list:
    req = Request(f"{BASE_URL}{endpoint}", headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    })
    with urlopen(req) as resp:
        return json.loads(resp.read())


def api_post(endpoint: str, api_key: str, data: dict) -> dict:
    body = json.dumps(data).encode()
    req = Request(f"{BASE_URL}{endpoint}", data=body, method="POST", headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    })
    with urlopen(req) as resp:
        return json.loads(resp.read())


# ─── Data Collection ────────────────────────────────────────────────

def get_profile(api_key: str) -> dict:
    return api_get("/agents/me", api_key)


def get_wallet(api_key: str) -> dict:
    return api_get("/wallet/balance", api_key)


def get_my_bids(api_key: str) -> list:
    return api_get("/agents/me/bids", api_key)


def get_open_jobs(api_key: str, limit: int = 100) -> list:
    return api_get(f"/jobs?status=open&limit={limit}", api_key)


def get_bids_on_my_jobs(api_key: str) -> list:
    return api_get("/agents/me/jobs/bids", api_key)


# ─── Analysis Engine ────────────────────────────────────────────────

class AgentAnalyzer:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.profile = get_profile(api_key)
        self.bids = get_my_bids(api_key)
        self.wallet = get_wallet(api_key)
        self.open_jobs = get_open_jobs(api_key)

    @property
    def agent_id(self) -> str:
        return self.profile["agent_id"]

    @property
    def handle(self) -> str:
        return self.profile.get("handle", "unknown")

    @property
    def skills(self) -> list:
        caps = self.profile.get("capabilities", {})
        return caps.get("skills", [])

    @property
    def languages(self) -> list:
        caps = self.profile.get("capabilities", {})
        return caps.get("languages", [])

    def bid_stats(self) -> dict:
        total = len(self.bids)
        accepted = [b for b in self.bids if b["status"] == "accepted"]
        pending = [b for b in self.bids if b["status"] == "pending"]
        rejected = [b for b in self.bids if b["status"] == "rejected"]
        withdrawn = [b for b in self.bids if b["status"] == "withdrawn"]

        win_rate = len(accepted) / total * 100 if total > 0 else 0

        amounts = [float(b["amount"]) for b in self.bids]
        avg_bid = sum(amounts) / len(amounts) if amounts else 0

        accepted_amounts = [float(b["amount"]) for b in accepted]
        avg_earning = sum(accepted_amounts) / len(accepted_amounts) if accepted_amounts else 0
        total_earned = sum(accepted_amounts)

        return {
            "total_bids": total,
            "accepted": len(accepted),
            "pending": len(pending),
            "rejected": len(rejected),
            "withdrawn": len(withdrawn),
            "win_rate": win_rate,
            "avg_bid_amount": avg_bid,
            "avg_earning_per_job": avg_earning,
            "total_earned": total_earned,
        }

    def market_analysis(self) -> dict:
        budgets = [float(j["budget_amount"]) for j in self.open_jobs if j.get("budget_amount")]
        avg_budget = sum(budgets) / len(budgets) if budgets else 0
        median_budget = sorted(budgets)[len(budgets) // 2] if budgets else 0

        # Tag frequency
        tag_counts = {}
        for j in self.open_jobs:
            for tag in j.get("tags", []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        # Competition analysis
        bid_counts = [j.get("bid_count", 0) for j in self.open_jobs]
        avg_competition = sum(bid_counts) / len(bid_counts) if bid_counts else 0

        low_competition = [j for j in self.open_jobs if j.get("bid_count", 0) <= 2]
        high_value_low_comp = sorted(
            [j for j in low_competition if j.get("budget_amount")],
            key=lambda j: float(j["budget_amount"]),
            reverse=True,
        )[:10]

        return {
            "total_open_jobs": len(self.open_jobs),
            "avg_budget": avg_budget,
            "median_budget": median_budget,
            "avg_competition": avg_competition,
            "top_tags": top_tags,
            "best_opportunities": high_value_low_comp,
        }

    def skill_match_jobs(self) -> list:
        """Find open jobs matching agent's skills."""
        my_skills = set(s.lower() for s in self.skills + self.languages)
        matches = []
        for job in self.open_jobs:
            job_tags = set(t.lower() for t in job.get("tags", []))
            overlap = my_skills & job_tags
            if overlap:
                matches.append({
                    "job_id": job["job_id"],
                    "title": job["title"],
                    "budget": job.get("budget_amount", "?"),
                    "bids": job.get("bid_count", 0),
                    "matching_skills": list(overlap),
                    "score": len(overlap) * 10 + (1.0 / max(job.get("bid_count", 1), 1)),
                })
        return sorted(matches, key=lambda m: m["score"], reverse=True)

    def generate_recommendations(self) -> list:
        recs = []
        stats = self.bid_stats()
        market = self.market_analysis()

        # Win rate recommendations
        if stats["total_bids"] == 0:
            recs.append({
                "priority": "HIGH",
                "category": "Getting Started",
                "action": "Submit your first bids",
                "detail": f"There are {market['total_open_jobs']} open jobs. "
                          f"Start with low-competition jobs (<=2 bids) to build reputation.",
                "impact": "Essential - no earnings without bids",
            })
        elif stats["win_rate"] < 20:
            recs.append({
                "priority": "HIGH",
                "category": "Win Rate",
                "action": "Lower bid amounts to be more competitive",
                "detail": f"Your win rate is {stats['win_rate']:.0f}%. "
                          f"Average market budget is {market['avg_budget']:.1f} NEAR. "
                          f"Try bidding 10-20% below budget.",
                "impact": f"Could increase win rate by 2-3x",
            })

        # Bid timing
        if stats["total_bids"] > 0:
            bid_times = []
            for b in self.bids:
                created = datetime.fromisoformat(b["created_at"].replace("Z", "+00:00"))
                bid_times.append(created)
            if bid_times:
                recs.append({
                    "priority": "MEDIUM",
                    "category": "Speed",
                    "action": "Bid faster on new jobs",
                    "detail": "Early bids have higher win rates. Set up polling to catch new jobs quickly.",
                    "impact": "Jobs with <2hr response win 2-3x more often",
                })

        # Skill matching
        matched = self.skill_match_jobs()
        if matched:
            top = matched[0]
            recs.append({
                "priority": "HIGH",
                "category": "Targeting",
                "action": f"Bid on '{top['title']}' ({top['budget']} NEAR, {top['bids']} bids)",
                "detail": f"Matches your skills: {', '.join(top['matching_skills'])}. "
                          f"Low competition makes this a strong opportunity.",
                "impact": f"Potential {top['budget']} NEAR earnings",
            })

        # Diversification
        if stats["total_bids"] > 5:
            bid_job_ids = set(b["job_id"] for b in self.bids)
            bid_tags = set()
            for j in self.open_jobs:
                if j["job_id"] in bid_job_ids:
                    bid_tags.update(j.get("tags", []))

            top_market_tags = set(t[0] for t in market["top_tags"][:5])
            missing_tags = top_market_tags - bid_tags
            if missing_tags:
                recs.append({
                    "priority": "LOW",
                    "category": "Diversification",
                    "action": f"Explore trending categories: {', '.join(missing_tags)}",
                    "detail": "You haven't bid in popular categories. Expanding scope increases opportunities.",
                    "impact": "Access to more job pool",
                })

        # Wallet
        balance = float(self.wallet.get("available", self.wallet.get("balance", 0)))
        if balance < 1:
            recs.append({
                "priority": "LOW",
                "category": "Wallet",
                "action": "Consider depositing NEAR to post your own jobs",
                "detail": f"Balance: {balance} NEAR. Having funds lets you delegate work and earn margins.",
                "impact": "Enables job creation and delegation",
            })

        # Low competition opportunities
        if market["best_opportunities"]:
            opp = market["best_opportunities"][0]
            recs.append({
                "priority": "HIGH",
                "category": "Opportunity",
                "action": f"Low competition: '{opp['title']}' ({opp.get('budget_amount', '?')} NEAR, {opp.get('bid_count', 0)} bids)",
                "detail": "High budget with minimal competition. Strong chance of winning.",
                "impact": f"Potential {opp.get('budget_amount', '?')} NEAR",
            })

        return sorted(recs, key=lambda r: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[r["priority"]])


# ─── Report Generator ───────────────────────────────────────────────

def print_report(analyzer: AgentAnalyzer):
    stats = analyzer.bid_stats()
    market = analyzer.market_analysis()
    recs = analyzer.generate_recommendations()
    matches = analyzer.skill_match_jobs()

    print()
    print("=" * 60)
    print("  NEAR Agent Earnings Optimizer Report")
    print("=" * 60)

    # Profile
    print(f"\n  Agent: @{analyzer.handle}")
    print(f"  ID: {analyzer.agent_id}")
    print(f"  Skills: {', '.join(analyzer.skills)}")
    print(f"  Languages: {', '.join(analyzer.languages)}")

    # Performance
    print(f"\n{'─' * 60}")
    print("  PERFORMANCE")
    print(f"{'─' * 60}")
    print(f"  Total Bids:      {stats['total_bids']}")
    print(f"  Won (Accepted):  {stats['accepted']}")
    print(f"  Pending:         {stats['pending']}")
    print(f"  Rejected:        {stats['rejected']}")
    print(f"  Win Rate:        {stats['win_rate']:.1f}%")
    print(f"  Avg Bid Amount:  {stats['avg_bid_amount']:.2f} NEAR")
    print(f"  Avg Earning/Job: {stats['avg_earning_per_job']:.2f} NEAR")
    print(f"  Total Earned:    {stats['total_earned']:.2f} NEAR")

    # Wallet
    balance = analyzer.wallet
    print(f"\n{'─' * 60}")
    print("  WALLET")
    print(f"{'─' * 60}")
    for k, v in balance.items():
        print(f"  {k}: {v}")

    # Market
    print(f"\n{'─' * 60}")
    print("  MARKET OVERVIEW")
    print(f"{'─' * 60}")
    print(f"  Open Jobs:         {market['total_open_jobs']}")
    print(f"  Avg Budget:        {market['avg_budget']:.2f} NEAR")
    print(f"  Median Budget:     {market['median_budget']:.2f} NEAR")
    print(f"  Avg Competition:   {market['avg_competition']:.1f} bids/job")
    print(f"\n  Top Tags:")
    for tag, count in market["top_tags"]:
        print(f"    {tag}: {count} jobs")

    # Skill matches
    if matches:
        print(f"\n{'─' * 60}")
        print("  JOBS MATCHING YOUR SKILLS")
        print(f"{'─' * 60}")
        for m in matches[:8]:
            print(f"  [{m['bids']} bids] {m['budget']} NEAR - {m['title']}")
            print(f"           Matches: {', '.join(m['matching_skills'])}")

    # Best opportunities
    if market["best_opportunities"]:
        print(f"\n{'─' * 60}")
        print("  BEST OPPORTUNITIES (High Budget, Low Competition)")
        print(f"{'─' * 60}")
        for opp in market["best_opportunities"][:5]:
            print(f"  [{opp.get('bid_count', 0)} bids] {opp.get('budget_amount', '?')} NEAR - {opp['title']}")

    # Recommendations
    print(f"\n{'─' * 60}")
    print("  RECOMMENDATIONS")
    print(f"{'─' * 60}")
    for i, rec in enumerate(recs, 1):
        icon = {"HIGH": "!!!", "MEDIUM": " ! ", "LOW": "   "}[rec["priority"]]
        print(f"\n  {icon} [{rec['priority']}] {rec['category']}: {rec['action']}")
        print(f"      {rec['detail']}")
        print(f"      Impact: {rec['impact']}")

    print(f"\n{'=' * 60}")
    print(f"  Report generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'=' * 60}\n")

    return {
        "stats": stats,
        "market": market,
        "recommendations": recs,
        "skill_matches": matches,
    }


def generate_json_report(analyzer: AgentAnalyzer) -> dict:
    """Generate machine-readable JSON report."""
    stats = analyzer.bid_stats()
    market = analyzer.market_analysis()
    recs = analyzer.generate_recommendations()
    matches = analyzer.skill_match_jobs()

    # Serialize opportunities
    opps = []
    for opp in market["best_opportunities"][:10]:
        opps.append({
            "job_id": opp["job_id"],
            "title": opp["title"],
            "budget": opp.get("budget_amount"),
            "bids": opp.get("bid_count", 0),
            "tags": opp.get("tags", []),
        })

    return {
        "agent": {
            "handle": analyzer.handle,
            "agent_id": analyzer.agent_id,
            "skills": analyzer.skills,
            "languages": analyzer.languages,
        },
        "performance": stats,
        "wallet": analyzer.wallet,
        "market": {
            "total_open_jobs": market["total_open_jobs"],
            "avg_budget": round(market["avg_budget"], 2),
            "median_budget": round(market["median_budget"], 2),
            "avg_competition": round(market["avg_competition"], 1),
            "top_tags": market["top_tags"],
            "best_opportunities": opps,
        },
        "skill_matches": matches[:10],
        "recommendations": recs,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── CLI ────────────────────────────────────────────────────────────

def load_api_key_from_env() -> Optional[str]:
    """Try loading from .env.local in current or parent directories."""
    for path in [".env.local", "../.env.local"]:
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("NEAR_MARKET_API_KEY="):
                        return line.split("=", 1)[1].split("#")[0].strip()
    return os.environ.get("NEAR_MARKET_API_KEY")


def main():
    parser = argparse.ArgumentParser(description="NEAR Agent Earnings Optimizer")
    parser.add_argument("--api-key", help="Marketplace API key (sk_live_...)")
    parser.add_argument("--env", action="store_true", help="Load API key from .env.local")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--output", help="Save report to file")
    args = parser.parse_args()

    api_key = args.api_key
    if not api_key or args.env:
        api_key = load_api_key_from_env()

    if not api_key:
        print("Error: No API key. Use --api-key or --env flag.", file=sys.stderr)
        sys.exit(1)

    try:
        analyzer = AgentAnalyzer(api_key)
    except HTTPError as e:
        print(f"API error: {e.code} {e.reason}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        report = generate_json_report(analyzer)
        output = json.dumps(report, indent=2)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"Report saved to {args.output}")
        else:
            print(output)
    else:
        report = print_report(analyzer)
        if args.output:
            json_report = generate_json_report(analyzer)
            with open(args.output, "w") as f:
                json.dump(json_report, f, indent=2)
            print(f"JSON report also saved to {args.output}")


if __name__ == "__main__":
    main()
