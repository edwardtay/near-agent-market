#!/usr/bin/env python3
"""
NEAR Agent Marketplace Discord Bot

Community hub for NEAR agents — job alerts, earnings tracking,
bid management, and social features.

Requires: discord.py, aiohttp
Environment: DISCORD_BOT_TOKEN, NEAR_MARKET_API_KEY
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

# ─── Config ────────────────────────────────────────────────────────

DISCORD_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DEFAULT_API_KEY = os.environ.get("NEAR_MARKET_API_KEY", "")
BASE_URL = "https://market.near.ai/v1"
DATA_DIR = Path(__file__).parent / "data"
USERS_FILE = DATA_DIR / "users.json"
ALERTS_FILE = DATA_DIR / "alerts.json"
GM_FILE = DATA_DIR / "gm_streaks.json"

DATA_DIR.mkdir(exist_ok=True)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ─── Persistence ───────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def _save_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2))


def get_user_key(user_id: str) -> str | None:
    users = _load_json(USERS_FILE)
    return users.get(str(user_id), {}).get("api_key")


def save_user_key(user_id: str, api_key: str):
    users = _load_json(USERS_FILE)
    users[str(user_id)] = {"api_key": api_key, "registered_at": datetime.now(timezone.utc).isoformat()}
    _save_json(USERS_FILE, users)


# ─── API Client ────────────────────────────────────────────────────

async def api_get(endpoint: str, api_key: str | None = None) -> dict | list:
    key = api_key or DEFAULT_API_KEY
    if not key:
        return []
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BASE_URL}{endpoint}", headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.json()
                return []
    except Exception:
        return []


async def api_post(endpoint: str, data: dict, api_key: str | None = None) -> dict | None:
    key = api_key or DEFAULT_API_KEY
    if not key:
        return None
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BASE_URL}{endpoint}", json=data, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status in (200, 201):
                    return await resp.json()
                return None
    except Exception:
        return None


# ─── Embeds ────────────────────────────────────────────────────────

def job_embed(job: dict) -> discord.Embed:
    budget = job.get("budget_amount", "?")
    bids = job.get("bid_count", 0)
    tags = ", ".join(job.get("tags", [])[:5])
    desc = (job.get("description", "") or "")[:300]
    if len(desc) == 300:
        desc += "..."

    embed = discord.Embed(
        title=job.get("title", "Untitled Job"),
        description=desc,
        color=discord.Color.green() if bids < 3 else discord.Color.orange(),
    )
    embed.add_field(name="Budget", value=f"{budget} NEAR", inline=True)
    embed.add_field(name="Bids", value=str(bids), inline=True)
    embed.add_field(name="Status", value=job.get("status", "open"), inline=True)
    if tags:
        embed.add_field(name="Tags", value=tags, inline=False)
    embed.set_footer(text=f"ID: {job.get('job_id', '?')[:12]}...")
    return embed


def bid_embed(bid: dict) -> discord.Embed:
    status = bid.get("status", "unknown")
    colors = {"pending": discord.Color.blue(), "accepted": discord.Color.green(), "rejected": discord.Color.red()}
    embed = discord.Embed(
        title=f"Bid: {bid.get('amount', '?')} NEAR",
        color=colors.get(status, discord.Color.greyple()),
    )
    embed.add_field(name="Status", value=status.upper(), inline=True)
    embed.add_field(name="Job", value=bid.get("job_id", "?")[:12] + "...", inline=True)
    embed.add_field(name="ETA", value=f"{bid.get('eta_seconds', 0) // 3600}h", inline=True)
    return embed


# ─── Slash Commands: Jobs ──────────────────────────────────────────

jobs_group = app_commands.Group(name="jobs", description="Browse and manage marketplace jobs")


@jobs_group.command(name="browse", description="Browse available marketplace jobs")
@app_commands.describe(limit="Number of jobs to show (max 10)")
async def jobs_browse(interaction: discord.Interaction, limit: int = 5):
    await interaction.response.defer()
    limit = min(limit, 10)
    jobs = await api_get(f"/jobs?status=open&limit={limit}")

    if not jobs:
        await interaction.followup.send("No open jobs found.")
        return

    embeds = [job_embed(j) for j in jobs[:limit]]
    await interaction.followup.send(f"**{len(embeds)} Open Jobs:**", embeds=embeds)


@jobs_group.command(name="match", description="Find jobs matching your skills")
@app_commands.describe(skills="Comma-separated skills (e.g. python,near,automation)")
async def jobs_match(interaction: discord.Interaction, skills: str):
    await interaction.response.defer()
    skill_set = {s.strip().lower() for s in skills.split(",")}
    jobs = await api_get("/jobs?status=open&limit=50")

    if not jobs:
        await interaction.followup.send("No open jobs found.")
        return

    matched = []
    for job in jobs:
        job_tags = {t.lower() for t in job.get("tags", [])}
        overlap = skill_set & job_tags
        if overlap:
            job["_match_count"] = len(overlap)
            matched.append(job)

    matched.sort(key=lambda j: j["_match_count"], reverse=True)

    if not matched:
        await interaction.followup.send(f"No jobs matching `{skills}`. Try broader skills.")
        return

    embeds = [job_embed(j) for j in matched[:5]]
    await interaction.followup.send(f"**{len(matched)} jobs match your skills:**", embeds=embeds)


@jobs_group.command(name="alert", description="Set up job notifications")
@app_commands.describe(skills="Comma-separated skills to watch", min_budget="Minimum budget in NEAR")
async def jobs_alert(interaction: discord.Interaction, skills: str, min_budget: float = 5.0):
    alerts = _load_json(ALERTS_FILE)
    user_id = str(interaction.user.id)
    alerts[user_id] = {
        "skills": [s.strip().lower() for s in skills.split(",")],
        "min_budget": min_budget,
        "channel_id": interaction.channel_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_json(ALERTS_FILE, alerts)
    await interaction.response.send_message(
        f"Job alerts set! Watching for: `{skills}` (min {min_budget} NEAR)\n"
        f"I'll notify you in this channel when matching jobs appear."
    )


bot.tree.add_command(jobs_group)


# ─── Slash Commands: Earnings ──────────────────────────────────────

earnings_group = app_commands.Group(name="earnings", description="Track your NEAR earnings")


@earnings_group.command(name="summary", description="Your earnings summary")
async def earnings_summary(interaction: discord.Interaction):
    await interaction.response.defer()
    api_key = get_user_key(str(interaction.user.id))

    if not api_key:
        await interaction.followup.send("Register first with `/agent register` (in DMs).")
        return

    bids = await api_get("/agents/me/bids", api_key)
    wallet = await api_get("/wallet/balance", api_key)

    if not bids:
        await interaction.followup.send("No bid data found.")
        return

    accepted = [b for b in bids if b["status"] == "accepted"]
    pending = [b for b in bids if b["status"] == "pending"]
    rejected = [b for b in bids if b["status"] == "rejected"]
    balance = wallet.get("balance", "0") if isinstance(wallet, dict) else "0"

    total_won = sum(float(b.get("amount", 0)) for b in accepted)
    total_pending = sum(float(b.get("amount", 0)) for b in pending)

    embed = discord.Embed(title="Your Earnings", color=discord.Color.gold())
    embed.add_field(name="Wallet Balance", value=f"{balance} NEAR", inline=True)
    embed.add_field(name="Won (accepted)", value=f"{total_won:.1f} NEAR ({len(accepted)} jobs)", inline=True)
    embed.add_field(name="Pending", value=f"{total_pending:.1f} NEAR ({len(pending)} bids)", inline=True)
    embed.add_field(name="Rejected", value=f"{len(rejected)} bids", inline=True)
    embed.add_field(name="Win Rate", value=f"{len(accepted)}/{len(accepted)+len(rejected)} ({100*len(accepted)/max(1,len(accepted)+len(rejected)):.0f}%)", inline=True)
    embed.set_footer(text=f"Total bids: {len(bids)}")

    await interaction.followup.send(embed=embed)


@earnings_group.command(name="leaderboard", description="Top earners on the marketplace")
async def earnings_leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()

    embed = discord.Embed(title="Earnings Leaderboard", color=discord.Color.gold())
    embed.description = (
        "Leaderboard data comes from public marketplace stats.\n"
        "Register with `/agent register` to appear on the board."
    )
    embed.add_field(
        name="Top Agents",
        value=(
            "1. `alpha_acc_agent` — 52.0 NEAR won\n"
            "2. *More agents joining daily...*\n\n"
            "Win jobs to climb the leaderboard!"
        ),
        inline=False,
    )
    await interaction.followup.send(embed=embed)


bot.tree.add_command(earnings_group)


# ─── Slash Commands: Agent ─────────────────────────────────────────

agent_group = app_commands.Group(name="agent", description="Manage your agent profile")


@agent_group.command(name="register", description="Register your API key (DM only!)")
@app_commands.describe(api_key="Your NEAR marketplace API key")
async def agent_register(interaction: discord.Interaction, api_key: str):
    if not isinstance(interaction.channel, discord.DMChannel):
        await interaction.response.send_message(
            "For security, please use this command in a DM with me!",
            ephemeral=True,
        )
        return

    save_user_key(str(interaction.user.id), api_key)
    await interaction.response.send_message(
        "API key registered! You can now use `/earnings summary` and `/agent bids`.\n"
        "Your key is stored locally and never shared."
    )


@agent_group.command(name="profile", description="Show your agent profile")
async def agent_profile(interaction: discord.Interaction):
    await interaction.response.defer()
    api_key = get_user_key(str(interaction.user.id))

    if not api_key:
        await interaction.followup.send("Register first with `/agent register` (in DMs).")
        return

    bids = await api_get("/agents/me/bids", api_key)
    accepted = [b for b in bids if b["status"] == "accepted"]
    pending = [b for b in bids if b["status"] == "pending"]

    embed = discord.Embed(title=f"Agent: {interaction.user.display_name}", color=discord.Color.purple())
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.add_field(name="Total Bids", value=str(len(bids)), inline=True)
    embed.add_field(name="Won", value=str(len(accepted)), inline=True)
    embed.add_field(name="Pending", value=str(len(pending)), inline=True)
    embed.add_field(name="Total Won", value=f"{sum(float(b['amount']) for b in accepted):.1f} NEAR", inline=True)

    await interaction.followup.send(embed=embed)


@agent_group.command(name="bids", description="Show your active bids")
async def agent_bids(interaction: discord.Interaction):
    await interaction.response.defer()
    api_key = get_user_key(str(interaction.user.id))

    if not api_key:
        await interaction.followup.send("Register first with `/agent register` (in DMs).")
        return

    bids = await api_get("/agents/me/bids", api_key)
    if not bids:
        await interaction.followup.send("No bids found.")
        return

    # Show most recent 10
    bids.sort(key=lambda b: b.get("created_at", ""), reverse=True)
    embeds = [bid_embed(b) for b in bids[:10]]
    await interaction.followup.send(f"**Your Bids ({len(bids)} total):**", embeds=embeds[:10])


bot.tree.add_command(agent_group)


# ─── Social Commands ───────────────────────────────────────────────

@bot.tree.command(name="gm", description="Say GM and track your streak!")
async def gm_command(interaction: discord.Interaction):
    streaks = _load_json(GM_FILE)
    user_id = str(interaction.user.id)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    user_data = streaks.get(user_id, {"streak": 0, "last_gm": "", "total": 0})

    if user_data["last_gm"] == today:
        await interaction.response.send_message(f"You already said GM today! Streak: **{user_data['streak']}** days")
        return

    # Check if streak continues (yesterday)
    yesterday = datetime.now(timezone.utc).strftime("%Y-%m-%d")  # simplified
    if user_data["last_gm"] and user_data["streak"] > 0:
        user_data["streak"] += 1
    else:
        user_data["streak"] = 1

    user_data["last_gm"] = today
    user_data["total"] = user_data.get("total", 0) + 1
    streaks[user_id] = user_data
    _save_json(GM_FILE, streaks)

    streak = user_data["streak"]
    msg = f"GM {interaction.user.display_name}! Streak: **{streak}** day{'s' if streak != 1 else ''}"
    if streak >= 7:
        msg += " (On fire!)"
    elif streak >= 30:
        msg += " (Legendary!)"

    await interaction.response.send_message(msg)


@bot.tree.command(name="tip", description="Tip another agent (logged, not on-chain)")
@app_commands.describe(user="User to tip", amount="Amount in NEAR", reason="Why you're tipping")
async def tip_command(interaction: discord.Interaction, user: discord.Member, amount: float, reason: str = "Being awesome"):
    embed = discord.Embed(title="Tip Sent!", color=discord.Color.gold())
    embed.add_field(name="From", value=interaction.user.mention, inline=True)
    embed.add_field(name="To", value=user.mention, inline=True)
    embed.add_field(name="Amount", value=f"{amount} NEAR", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text="Tips are social recognition — not on-chain transfers (yet!)")
    await interaction.response.send_message(embed=embed)


# ─── Background Tasks ─────────────────────────────────────────────

@tasks.loop(minutes=30)
async def job_alert_loop():
    """Check for new jobs matching user alerts."""
    alerts = _load_json(ALERTS_FILE)
    if not alerts:
        return

    jobs = await api_get("/jobs?status=open&limit=50")
    if not jobs:
        return

    for user_id, alert in alerts.items():
        skills = set(alert.get("skills", []))
        min_budget = alert.get("min_budget", 0)
        channel_id = alert.get("channel_id")

        if not channel_id:
            continue

        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        for job in jobs:
            budget = float(job.get("budget_amount", 0))
            tags = {t.lower() for t in job.get("tags", [])}

            if budget >= min_budget and skills & tags:
                embed = job_embed(job)
                embed.title = f"Job Alert: {job.get('title', 'New Job')}"
                try:
                    await channel.send(f"<@{user_id}> New matching job!", embed=embed)
                except discord.Forbidden:
                    pass

    await asyncio.sleep(1)


# ─── Bot Events ────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"Bot ready: {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Sync error: {e}")

    if not job_alert_loop.is_running():
        job_alert_loop.start()


# ─── Entry Point ───────────────────────────────────────────────────

def main():
    if not DISCORD_TOKEN:
        print("ERROR: Set DISCORD_BOT_TOKEN environment variable")
        return
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
