#!/usr/bin/env python3
"""
NEAR Job Posting Bot

Automatically generates and posts quality jobs to the NEAR Agent Marketplace
based on ecosystem needs, templates, and gap analysis.

Environment:
    NEAR_MARKET_API_KEY — Marketplace API key
    JOB_BOT_POSTS_PER_RUN — Jobs to post per run (default 3)
"""

import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ─── Config ────────────────────────────────────────────────────────

BASE_URL = "https://market.near.ai/v1"
API_KEY = os.environ.get("NEAR_MARKET_API_KEY", "")
POSTS_PER_RUN = int(os.environ.get("JOB_BOT_POSTS_PER_RUN", "3"))
STATE_FILE = Path("/tmp/near_job_bot_state.json")
LOG_FILE = Path("/tmp/near_job_bot.log")


# ─── Logging ───────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ─── API Helpers ───────────────────────────────────────────────────

def api_get(endpoint: str) -> list | dict:
    req = Request(f"{BASE_URL}{endpoint}", headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    })
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (HTTPError, URLError, json.JSONDecodeError) as e:
        log(f"API GET error {endpoint}: {e}")
        return []


def api_post(endpoint: str, data: dict) -> dict | None:
    body = json.dumps(data).encode()
    req = Request(f"{BASE_URL}{endpoint}", data=body, method="POST", headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    })
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (HTTPError, URLError) as e:
        log(f"API POST error {endpoint}: {e}")
        return None


# ─── State Management ──────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"posted_hashes": [], "total_posted": 0}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def job_hash(title: str, tags: list) -> str:
    """Dedup hash to avoid posting near-identical jobs."""
    raw = f"{title.lower().strip()}|{'|'.join(sorted(tags))}".encode()
    return hashlib.md5(raw).hexdigest()[:12]


# ─── Job Templates ─────────────────────────────────────────────────

TEMPLATES = {
    "openclaw_skill": {
        "titles": [
            "OpenClaw Skill: {topic}",
            "Build OpenClaw Skill for {topic}",
            "Create {topic} Skill for OpenClaw Agents",
        ],
        "topics": [
            "NEAR Token Analytics", "DEX Price Alerts", "Wallet Portfolio Tracker",
            "Cross-Chain Bridge Monitor", "Staking Rewards Calculator",
            "Smart Contract Deployer", "Transaction History Parser",
            "Gas Fee Optimizer", "Validator Monitoring", "DeFi Yield Tracker",
            "Token Swap Executor", "Account Security Scanner",
            "Multi-Sig Wallet Manager", "Airdrop Checker", "Liquidity Pool Monitor",
        ],
        "description_template": """## Overview
Create an OpenClaw skill that enables agents to {action}.

## Requirements
- Python implementation using NEAR RPC
- Clean command interface with clear docstrings
- Proper error handling and input validation
- No external dependencies (stdlib only)
- Ready for MoltHub publishing

## Deliverables
1. Main Python skill file with all commands
2. README with setup and usage instructions
3. Example output demonstrating each command

## Acceptance Criteria
- All commands work against NEAR mainnet
- Code is clean, documented, and production-ready
- README covers installation and all commands
""",
        "actions": [
            "track and analyze NEAR token metrics",
            "monitor DEX prices and send alerts",
            "view and manage wallet portfolios",
            "monitor cross-chain bridge transactions",
            "calculate and optimize staking rewards",
            "deploy and manage smart contracts",
            "parse and display transaction history",
            "optimize gas fees for NEAR transactions",
            "monitor NEAR validator performance",
            "track DeFi yields across protocols",
            "execute token swaps on NEAR DEXes",
            "scan accounts for security issues",
            "manage multi-sig wallets on NEAR",
            "check eligibility for token airdrops",
            "monitor liquidity pool positions",
        ],
        "tags_base": ["openclaw", "skill", "near"],
        "tags_extra": [
            ["analytics", "tokens"], ["defi", "alerts"], ["wallet", "portfolio"],
            ["bridge", "crosschain"], ["staking", "rewards"], ["contracts", "deploy"],
            ["transactions", "history"], ["gas", "optimization"], ["validator", "monitoring"],
            ["defi", "yield"], ["swap", "dex"], ["security", "audit"],
            ["multisig", "wallet"], ["airdrop", "tokens"], ["liquidity", "defi"],
        ],
        "budget_range": (6, 12),
    },
    "automation": {
        "titles": [
            "Build: {topic} Automation Tool",
            "Automate {topic} for NEAR Agents",
            "{topic} Bot for NEAR Marketplace",
        ],
        "topics": [
            "Job Matching", "Bid Optimization", "Earnings Report",
            "Skill Gap Analysis", "Agent Performance Tracker",
            "Marketplace Analytics Dashboard", "Agent Reputation System",
            "Automated Testing Pipeline", "Deployment Automation",
            "Community Engagement Tracker",
        ],
        "description_template": """## Overview
Build an automation tool that {action}.

## Features Required
- Automated execution (cron-compatible)
- Configurable via environment variables
- Logging with timestamps
- Error recovery and retry logic
- Telegram/Discord notification support

## Technical Requirements
- Python 3.10+
- No heavy external dependencies
- Clean, well-documented code
- Works with NEAR Agent Marketplace API

## Deliverables
1. Main Python script
2. Configuration template
3. README with setup, cron examples, and usage guide
""",
        "actions": [
            "matches agents to optimal jobs based on skills and history",
            "optimizes bid amounts based on competition and win rate",
            "generates comprehensive earnings and performance reports",
            "identifies skill gaps and recommends upskilling paths",
            "tracks agent performance metrics over time",
            "provides real-time marketplace analytics and trends",
            "builds and maintains agent reputation scores",
            "runs automated tests on agent deliverables",
            "automates deployment of agent skills and tools",
            "tracks community engagement and contribution metrics",
        ],
        "tags_base": ["automation", "bot", "near"],
        "tags_extra": [
            ["jobs", "matching"], ["bidding", "optimization"], ["earnings", "analytics"],
            ["skills", "analysis"], ["performance", "tracking"], ["analytics", "dashboard"],
            ["reputation", "scoring"], ["testing", "qa"], ["deployment", "ci"],
            ["community", "engagement"],
        ],
        "budget_range": (8, 15),
    },
    "integration": {
        "titles": [
            "Build: NEAR {topic} Integration",
            "{topic} API Integration for NEAR Agents",
            "Connect NEAR Agents to {topic}",
        ],
        "topics": [
            "GitHub", "Telegram", "Discord", "Twitter/X",
            "Chainlink Oracle", "The Graph", "IPFS Storage",
            "Ceramic Network", "LivePeer", "Arweave",
        ],
        "description_template": """## Overview
Build an integration that connects NEAR agents with {topic}.

## Integration Points
- Authentication and API key management
- Data fetching and caching
- Event-driven updates
- Error handling with retries

## Requirements
- Clean Python implementation
- Environment-based configuration
- Rate limiting compliance
- Comprehensive documentation

## Deliverables
1. Integration module
2. Example usage scripts
3. README with API setup guide
""",
        "actions": [
            "GitHub for code collaboration and issue tracking",
            "Telegram for real-time notifications and commands",
            "Discord for community management and alerts",
            "Twitter/X for social engagement and announcements",
            "Chainlink for oracle data feeds",
            "The Graph for indexed blockchain data",
            "IPFS for decentralized file storage",
            "Ceramic for decentralized identity and data",
            "LivePeer for video transcoding services",
            "Arweave for permanent data storage",
        ],
        "tags_base": ["integration", "api", "near"],
        "tags_extra": [
            ["github", "code"], ["telegram", "messaging"], ["discord", "community"],
            ["twitter", "social"], ["oracle", "chainlink"], ["graph", "indexing"],
            ["ipfs", "storage"], ["ceramic", "identity"], ["livepeer", "video"],
            ["arweave", "storage"],
        ],
        "budget_range": (8, 14),
    },
    "research": {
        "titles": [
            "Research: {topic}",
            "Analysis: {topic} for NEAR Ecosystem",
            "Deep Dive: {topic}",
        ],
        "topics": [
            "Agent Marketplace Economics", "Optimal Bidding Strategies",
            "NEAR DeFi Landscape", "Cross-Chain Agent Interop",
            "AI Agent Security Best Practices", "MoltHub Skill Taxonomy",
            "Agent Collaboration Patterns", "Marketplace Fee Optimization",
            "NEAR Ecosystem Growth Metrics", "Agent Skill Demand Forecast",
        ],
        "description_template": """## Overview
Research and analyze {topic}.

## Scope
- Current state analysis
- Competitive landscape
- Opportunities and gaps
- Data-backed recommendations

## Deliverables
1. Research report (markdown, 2000+ words)
2. Data tables and charts (if applicable)
3. Actionable recommendations
4. Executive summary

## Acceptance Criteria
- Well-researched with cited sources
- Clear, structured presentation
- Actionable insights
""",
        "actions": [
            "agent marketplace economics and pricing dynamics",
            "optimal bidding strategies based on historical data",
            "the NEAR DeFi landscape and opportunities for agents",
            "cross-chain agent interoperability patterns",
            "AI agent security best practices and threat models",
            "MoltHub skill taxonomy and publishing standards",
            "agent collaboration and task delegation patterns",
            "marketplace fee structures and optimization strategies",
            "NEAR ecosystem growth metrics and projections",
            "agent skill demand forecasting and trend analysis",
        ],
        "tags_base": ["research", "analysis", "near"],
        "tags_extra": [
            ["economics", "marketplace"], ["bidding", "strategy"], ["defi", "landscape"],
            ["crosschain", "interop"], ["security", "ai"], ["molthub", "skills"],
            ["collaboration", "agents"], ["fees", "optimization"], ["growth", "metrics"],
            ["demand", "forecast"],
        ],
        "budget_range": (5, 10),
    },
}


# ─── Job Generation ───────────────────────────────────────────────

def generate_job(template_type: str, topic_index: int) -> dict | None:
    """Generate a job from template type and topic index."""
    template = TEMPLATES.get(template_type)
    if not template:
        return None

    topics = template["topics"]
    if topic_index >= len(topics):
        return None

    topic = topics[topic_index]
    action = template["actions"][topic_index]
    title = random.choice(template["titles"]).format(topic=topic)
    description = template["description_template"].format(topic=topic, action=action)
    tags = template["tags_base"] + template["tags_extra"][topic_index]
    budget_min, budget_max = template["budget_range"]
    budget = round(random.uniform(budget_min, budget_max), 0)

    return {
        "title": title,
        "description": description,
        "tags": tags,
        "budget_amount": str(int(budget)),
        "budget_token": "NEAR",
    }


# ─── Gap Analysis ──────────────────────────────────────────────────

def analyze_gaps() -> list[tuple[str, int]]:
    """Analyze existing jobs to find underrepresented categories."""
    log("Analyzing marketplace gaps...")
    jobs = api_get("/jobs?status=open&limit=100")

    if not isinstance(jobs, list):
        # No data — suggest all types equally
        return [(t, 0) for t in TEMPLATES.keys()]

    # Count tags across open jobs
    tag_counts: dict[str, int] = {}
    for job in jobs:
        for tag in job.get("tags", []):
            tag_counts[tag.lower()] = tag_counts.get(tag.lower(), 0) + 1

    # Score each template type by how underrepresented it is
    type_scores = []
    for ttype, template in TEMPLATES.items():
        base_tags = template["tags_base"]
        representation = sum(tag_counts.get(t, 0) for t in base_tags)
        type_scores.append((ttype, representation))

    # Sort by least represented first
    type_scores.sort(key=lambda x: x[1])

    log(f"Gap analysis: {', '.join(f'{t}({s})' for t, s in type_scores)}")
    return type_scores


# ─── Post Jobs ─────────────────────────────────────────────────────

def post_jobs(count: int = POSTS_PER_RUN):
    """Generate and post jobs to the marketplace."""
    state = load_state()
    posted_hashes = set(state.get("posted_hashes", []))

    # Find gaps
    gaps = analyze_gaps()

    posted = 0
    for template_type, _ in gaps:
        if posted >= count:
            break

        template = TEMPLATES[template_type]
        topic_indices = list(range(len(template["topics"])))
        random.shuffle(topic_indices)

        for idx in topic_indices:
            if posted >= count:
                break

            job = generate_job(template_type, idx)
            if not job:
                continue

            # Dedup check
            h = job_hash(job["title"], job["tags"])
            if h in posted_hashes:
                continue

            # Post it
            result = api_post("/jobs", job)
            if result and "job_id" in result:
                log(f"POSTED: {job['title']} ({job['budget_amount']} NEAR) -> {result['job_id'][:12]}")
                posted_hashes.add(h)
                posted += 1
                time.sleep(2)  # Rate limit
            else:
                log(f"Failed to post: {job['title']}")

    # Save state
    state["posted_hashes"] = list(posted_hashes)[-500:]  # Keep last 500
    state["total_posted"] = state.get("total_posted", 0) + posted
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    log(f"Posted {posted}/{count} jobs. Total lifetime: {state['total_posted']}")
    return posted


# ─── CLI ───────────────────────────────────────────────────────────

def main():
    if not API_KEY:
        print("ERROR: Set NEAR_MARKET_API_KEY environment variable")
        sys.exit(1)

    log("=" * 50)
    log("NEAR Job Posting Bot starting")
    log("=" * 50)

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "gaps":
            gaps = analyze_gaps()
            for ttype, score in gaps:
                print(f"  {ttype:20} representation={score}")
            return
        elif cmd == "preview":
            # Preview jobs without posting
            for ttype in TEMPLATES:
                job = generate_job(ttype, 0)
                if job:
                    print(f"\n--- {ttype} ---")
                    print(f"Title: {job['title']}")
                    print(f"Budget: {job['budget_amount']} NEAR")
                    print(f"Tags: {', '.join(job['tags'])}")
            return
        elif cmd == "post":
            count = int(sys.argv[2]) if len(sys.argv) > 2 else POSTS_PER_RUN
            post_jobs(count)
            return

    # Default: post jobs
    post_jobs()


if __name__ == "__main__":
    main()
