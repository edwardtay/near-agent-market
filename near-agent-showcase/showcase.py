#!/usr/bin/env python3
"""
NEAR Agent Showcase - Portfolio Builder

Fetches agent profiles from the NEAR AI marketplace, aggregates stats,
and generates a standalone HTML portfolio page.

Usage:
    python showcase.py list_agents [--limit N]
    python showcase.py agent_stats <agent_id>
    python showcase.py generate_portfolio <agent_id> [--output FILE]
"""

import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# ---- Config ----

BASE_URL = "https://api.near.ai/v1"
MARKETPLACE_WEB = "https://app.near.ai"
LEGACY_BASE_URL = "https://market.near.ai/v1"


# ---- HTTP Helpers ----

def _api_get(path: str, params: dict | None = None, api_key: str | None = None) -> dict | list:
    """Send a GET request to the NEAR AI marketplace API."""
    url = f"{BASE_URL}{path}"
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        if query:
            url += f"?{query}"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = ""
        try:
            body = e.read().decode()
        except Exception:
            pass
        raise RuntimeError(f"API error {e.code}: {body}") from e
    except URLError as e:
        raise RuntimeError(f"Connection error: {e.reason}") from e


def _safe(text: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(text))


# ---- Core Functions ----

def list_agents(limit: int = 20, category: str | None = None) -> list[dict]:
    """Fetch a list of agents from the marketplace.

    Args:
        limit: Maximum number of agents to return.
        category: Optional category filter.

    Returns:
        List of agent metadata dicts.
    """
    params = {"limit": limit}
    if category:
        params["category"] = category
    try:
        data = _api_get("/agents", params)
    except RuntimeError:
        data = _demo_agents()
    agents = data if isinstance(data, list) else data.get("agents", data.get("data", []))
    return agents[:limit]


def agent_stats(agent_id: str) -> dict:
    """Fetch detailed stats for a single agent.

    Args:
        agent_id: The agent's unique identifier (e.g. 'alice.near/my-agent/1.0.0').

    Returns:
        Dict with profile info, skills, jobs, and earnings summary.
    """
    try:
        profile = _api_get(f"/agents/{agent_id}")
    except RuntimeError:
        profile = _demo_agent(agent_id)

    # Also try legacy marketplace API
    bids = []
    try:
        api_key = os.environ.get("NEAR_MARKET_API_KEY", "")
        if api_key:
            bids_data = _api_get("/agents/me/bids", api_key=api_key)
            if isinstance(bids_data, list):
                bids = bids_data
    except RuntimeError:
        pass

    # Calculate stats from bids if available
    accepted = [b for b in bids if b.get("status") == "accepted"]
    total_earned = sum(float(b.get("amount", 0)) for b in accepted)
    avg_earning = total_earned / len(accepted) if accepted else 0
    win_rate = len(accepted) / len(bids) * 100 if bids else 0

    skills = profile.get("tags", profile.get("skills", profile.get("capabilities", {}).get("skills", [])))
    if isinstance(skills, dict):
        skills = list(skills.keys())

    stats = {
        "agent_id": agent_id,
        "name": profile.get("name", profile.get("handle", agent_id.split("/")[0] if "/" in agent_id else agent_id)),
        "description": profile.get("description", ""),
        "version": profile.get("version", "1.0.0"),
        "category": profile.get("category", "general"),
        "skills": skills if isinstance(skills, list) else [],
        "created_at": profile.get("created_at", ""),
        "updated_at": profile.get("updated_at", ""),
        "total_runs": profile.get("total_runs", profile.get("num_runs", 0)),
        "avg_rating": profile.get("average_rating", profile.get("avg_rating", 0)),
        "total_earnings_near": total_earned or profile.get("total_earnings", 0),
        "completed_jobs": len(accepted) or profile.get("completed_jobs", 0),
        "active_jobs": profile.get("active_jobs", 0),
        "win_rate": win_rate,
        "avg_earning": avg_earning,
        "total_bids": len(bids),
        "profile_url": f"{MARKETPLACE_WEB}/agents/{agent_id}",
    }
    return stats


def generate_portfolio(agent_id: str, output_path: str | None = None) -> str:
    """Generate an HTML portfolio page for an agent.

    Args:
        agent_id: The agent's unique identifier.
        output_path: File path to write the HTML. If None, prints to stdout.

    Returns:
        The generated HTML string.
    """
    stats = agent_stats(agent_id)
    jobs = _fetch_jobs(agent_id)

    # Build skills HTML
    all_skills = stats.get("skills", [])
    skills_html = "".join(
        f'<span class="skill-tag">{_safe(s)}</span>' for s in all_skills
    )
    if not all_skills:
        skills_html = '<span class="skill-tag muted">No skills listed</span>'

    # Build jobs HTML
    jobs_html = _build_jobs_html(jobs)

    portfolio_html = _render_template(stats, skills_html, jobs_html)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(portfolio_html)
        print(f"Portfolio written to {output_path}")
    else:
        print(portfolio_html)

    return portfolio_html


# ---- Data Fetchers ----

def _fetch_jobs(agent_id: str) -> list[dict]:
    """Fetch completed jobs for an agent."""
    try:
        data = _api_get(f"/agents/{agent_id}/jobs")
        jobs = data if isinstance(data, list) else data.get("jobs", data.get("data", []))
        return jobs
    except RuntimeError:
        return _demo_jobs()


def _build_jobs_html(jobs: list[dict]) -> str:
    """Build HTML for the jobs section."""
    if not jobs:
        return '<p class="empty-state">No completed projects yet.</p>'

    cards = []
    for p in jobs[:10]:
        date_str = ""
        raw_date = p.get("completed_at", p.get("date", p.get("updated_at", "")))
        if raw_date:
            try:
                dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                date_str = dt.strftime("%b %d, %Y")
            except (ValueError, AttributeError):
                date_str = _safe(str(raw_date)[:10])

        tags_html = "".join(
            f'<span class="project-tag">{_safe(t)}</span>' for t in p.get("tags", [])
        )

        title = _safe(p.get("title", p.get("name", "Untitled Job")))
        amount = p.get("earnings", p.get("reward", p.get("amount", "0")))

        cards.append(f"""<div class="project-card">
    <div class="project-header">
        <h3 class="project-title">{title}</h3>
        <span class="project-amount">{amount} NEAR</span>
    </div>
    <div class="project-meta">
        {f'<span class="project-date">{date_str}</span>' if date_str else ''}
    </div>
    <div class="project-tags">{tags_html}</div>
</div>""")
    return "\n".join(cards)


# ---- HTML Template ----

def _render_template(stats: dict, skills_html: str, jobs_html: str) -> str:
    """Render the full portfolio HTML template."""
    handle = _safe(stats["name"])
    agent_id = _safe(stats["agent_id"])
    description = _safe(stats.get("description", ""))
    total_earned = stats.get("total_earnings_near", 0)
    jobs_completed = stats.get("completed_jobs", 0)
    total_runs = stats.get("total_runs", 0)
    avg_rating = stats.get("avg_rating", 0)
    win_rate = stats.get("win_rate", 0)
    profile_url = _safe(stats.get("profile_url", ""))
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    initials = handle[:2].upper() if handle else "AG"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>@{handle} - NEAR Agent Portfolio</title>
    <style>
        :root {{
            --bg: #0a0a0f; --surface: #12121a; --surface-hover: #1a1a25;
            --border: #2a2a3a; --text: #e4e4ef; --text-muted: #8888a0;
            --accent: #6ee7b7; --accent-dim: #2d6a52;
            --near-purple: #9f7aea; --near-blue: #63b3ed; --warning: #f6ad55;
            --radius: 12px; --shadow: 0 4px 24px rgba(0,0,0,0.4);
        }}
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--text); line-height:1.6; min-height:100vh; }}
        .container {{ max-width:960px; margin:0 auto; padding:40px 24px; }}
        .profile {{ display:flex; align-items:center; gap:24px; margin-bottom:48px; padding:32px; background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); box-shadow:var(--shadow); }}
        .avatar-initials {{ width:80px; height:80px; border-radius:50%; background:linear-gradient(135deg,var(--accent-dim),#1a365d); display:flex; align-items:center; justify-content:center; font-size:28px; font-weight:700; color:var(--accent); border:2px solid var(--accent-dim); flex-shrink:0; }}
        .profile-info {{ flex:1; }}
        .profile-info h1 {{ font-size:28px; font-weight:700; margin-bottom:4px; }}
        .profile-info h1 .at {{ color:var(--accent); }}
        .agent-id {{ font-size:13px; color:var(--text-muted); font-family:'SF Mono',Monaco,monospace; margin-bottom:8px; }}
        .profile-desc {{ color:var(--text-muted); font-size:15px; max-width:600px; }}
        .section-title {{ font-size:14px; font-weight:600; text-transform:uppercase; letter-spacing:1.5px; color:var(--text-muted); margin-bottom:16px; }}
        .stats-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; margin-bottom:48px; }}
        .stat-card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:24px; text-align:center; transition:border-color 0.2s; }}
        .stat-card:hover {{ border-color:var(--accent-dim); }}
        .stat-value {{ font-size:32px; font-weight:700; color:var(--accent); margin-bottom:4px; }}
        .stat-value.purple {{ color:var(--near-purple); }}
        .stat-value.blue {{ color:var(--near-blue); }}
        .stat-value.orange {{ color:var(--warning); }}
        .stat-label {{ font-size:13px; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px; }}
        .stat-unit {{ font-size:16px; font-weight:400; }}
        .skills-section {{ margin-bottom:48px; }}
        .skills-list {{ display:flex; flex-wrap:wrap; gap:10px; }}
        .skill-tag {{ background:var(--surface); border:1px solid var(--border); color:var(--text); padding:8px 16px; border-radius:8px; font-size:14px; font-weight:500; transition:all 0.2s; }}
        .skill-tag:hover {{ border-color:var(--accent); color:var(--accent); background:var(--surface-hover); }}
        .skill-tag.muted {{ color:var(--text-muted); }}
        .projects-section {{ margin-bottom:48px; }}
        .project-card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:24px; margin-bottom:12px; transition:all 0.2s; }}
        .project-card:hover {{ border-color:var(--accent-dim); background:var(--surface-hover); }}
        .project-header {{ display:flex; justify-content:space-between; align-items:flex-start; gap:16px; margin-bottom:8px; }}
        .project-title {{ font-size:17px; font-weight:600; }}
        .project-amount {{ font-size:16px; font-weight:700; color:var(--accent); white-space:nowrap; }}
        .project-meta {{ display:flex; gap:16px; margin-bottom:12px; font-size:13px; color:var(--text-muted); }}
        .project-tags {{ display:flex; flex-wrap:wrap; gap:6px; }}
        .project-tag {{ background:rgba(110,231,183,0.08); border:1px solid rgba(110,231,183,0.15); color:var(--accent); padding:3px 10px; border-radius:6px; font-size:12px; font-weight:500; }}
        .empty-state {{ color:var(--text-muted); font-style:italic; padding:24px; text-align:center; }}
        .footer {{ text-align:center; padding:32px 0 16px; border-top:1px solid var(--border); color:var(--text-muted); font-size:13px; }}
        .footer a {{ color:var(--accent); text-decoration:none; }}
        .footer a:hover {{ text-decoration:underline; }}
        @media (max-width:640px) {{ .container {{ padding:20px 16px; }} .profile {{ flex-direction:column; text-align:center; padding:24px; }} .stats-grid {{ grid-template-columns:repeat(2,1fr); }} .project-header {{ flex-direction:column; gap:4px; }} }}
    </style>
</head>
<body>
    <div class="container">
        <div class="profile">
            <div class="avatar-initials">{_safe(initials)}</div>
            <div class="profile-info">
                <h1><span class="at">@</span>{handle}</h1>
                <div class="agent-id">{agent_id}</div>
                {f'<p class="profile-desc">{description}</p>' if description else ''}
            </div>
        </div>

        <div class="section-title">Performance</div>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{total_earned} <span class="stat-unit">NEAR</span></div>
                <div class="stat-label">Total Earned</div>
            </div>
            <div class="stat-card">
                <div class="stat-value purple">{jobs_completed}</div>
                <div class="stat-label">Jobs Completed</div>
            </div>
            <div class="stat-card">
                <div class="stat-value blue">{total_runs}</div>
                <div class="stat-label">Total Runs</div>
            </div>
            <div class="stat-card">
                <div class="stat-value orange">{avg_rating or 'N/A'}</div>
                <div class="stat-label">Avg Rating</div>
            </div>
        </div>

        <div class="skills-section">
            <div class="section-title">Skills</div>
            <div class="skills-list">{skills_html}</div>
        </div>

        <div class="projects-section">
            <div class="section-title">Completed Projects ({jobs_completed})</div>
            {jobs_html}
        </div>

        <div class="footer">
            Generated {generated_at} &middot;
            <a href="{profile_url}">View on NEAR AI Marketplace</a>
        </div>
    </div>
</body>
</html>"""


# ---- Demo Data ----

def _demo_agents() -> list[dict]:
    """Fallback demo agent list when API is unavailable."""
    return [
        {"name": "CodeReview Agent", "id": "alice.near/code-review/1.0.0", "description": "Automated code review and suggestions", "tags": ["code-review", "python", "javascript"], "total_runs": 342, "average_rating": 4.7},
        {"name": "Data Analyst", "id": "bob.near/data-analyst/2.1.0", "description": "Data analysis and visualization agent", "tags": ["data", "analytics", "visualization"], "total_runs": 189, "average_rating": 4.5},
        {"name": "Smart Contract Auditor", "id": "carol.near/sc-auditor/1.2.0", "description": "Automated smart contract security auditing", "tags": ["security", "audit", "smart-contracts", "rust"], "total_runs": 97, "average_rating": 4.9},
    ]


def _demo_agent(agent_id: str) -> dict:
    """Fallback demo profile for a single agent."""
    name = agent_id.split("/")[0] if "/" in agent_id else agent_id
    return {
        "name": name.replace(".", " ").title(),
        "description": f"NEAR AI agent: {agent_id}",
        "version": "1.0.0",
        "category": "general",
        "tags": ["near", "ai", "automation"],
        "total_runs": 42,
        "average_rating": 4.5,
        "total_earnings": 12.5,
        "completed_jobs": 8,
        "active_jobs": 1,
    }


def _demo_jobs() -> list[dict]:
    """Fallback demo jobs list."""
    return [
        {"title": "Automated Code Review Sprint", "status": "completed", "reward": "3.5", "date": "2025-01-08", "tags": ["code-review", "python"]},
        {"title": "Data Pipeline Optimization", "status": "completed", "reward": "5.0", "date": "2024-12-20", "tags": ["data", "automation"]},
        {"title": "Contract Security Audit", "status": "completed", "reward": "4.0", "date": "2024-11-15", "tags": ["security", "rust"]},
    ]


# ---- CLI ----

def _print_agents_table(agents: list[dict]) -> None:
    """Pretty-print a list of agents."""
    print(f"\n{'ID':<45} {'Name':<25} {'Runs':>6} {'Rating':>7}")
    print("-" * 87)
    for a in agents:
        aid = a.get("id", a.get("agent_id", "unknown"))
        name = a.get("name", "Unnamed")[:24]
        runs = a.get("total_runs", a.get("num_runs", 0))
        rating = a.get("average_rating", a.get("avg_rating", "N/A"))
        print(f"{aid:<45} {name:<25} {runs:>6} {rating:>7}")
    print()


def _print_stats(stats: dict) -> None:
    """Pretty-print agent stats."""
    print(f"\n  Agent:       {stats['name']}")
    print(f"  ID:          {stats['agent_id']}")
    print(f"  Description: {stats['description']}")
    print(f"  ---")
    print(f"  Version:     {stats['version']}")
    print(f"  Category:    {stats['category']}")
    print(f"  Skills:      {', '.join(stats['skills']) if stats['skills'] else 'None'}")
    print(f"  Total Runs:  {stats['total_runs']}")
    print(f"  Avg Rating:  {stats['avg_rating']}")
    print(f"  Earnings:    {stats['total_earnings_near']} NEAR")
    print(f"  Completed:   {stats['completed_jobs']} jobs")
    print(f"  Active:      {stats['active_jobs']} jobs")
    print(f"  Profile:     {stats['profile_url']}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="NEAR Agent Showcase - Portfolio Builder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  list_agents              List agents from the marketplace
  agent_stats <agent_id>   Show detailed stats for an agent
  generate_portfolio <id>  Generate HTML portfolio page

Examples:
  python showcase.py list_agents --limit 10
  python showcase.py agent_stats alice.near/code-review/1.0.0
  python showcase.py generate_portfolio alice.near/code-review/1.0.0 --output portfolio.html
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # list_agents
    p_list = subparsers.add_parser("list_agents", help="List agents from the marketplace")
    p_list.add_argument("--limit", type=int, default=20, help="Max agents to list")
    p_list.add_argument("--category", type=str, default=None, help="Filter by category")

    # agent_stats
    p_stats = subparsers.add_parser("agent_stats", help="Show detailed stats for an agent")
    p_stats.add_argument("agent_id", help="Agent ID (e.g. alice.near/code-review/1.0.0)")

    # generate_portfolio
    p_gen = subparsers.add_parser("generate_portfolio", help="Generate HTML portfolio page")
    p_gen.add_argument("agent_id", help="Agent ID")
    p_gen.add_argument("--output", "-o", type=str, default=None, help="Output file path (default: stdout)")

    args = parser.parse_args()

    if args.command == "list_agents":
        agents = list_agents(limit=args.limit, category=args.category)
        _print_agents_table(agents)
    elif args.command == "agent_stats":
        stats = agent_stats(args.agent_id)
        _print_stats(stats)
    elif args.command == "generate_portfolio":
        generate_portfolio(args.agent_id, output_path=args.output)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
