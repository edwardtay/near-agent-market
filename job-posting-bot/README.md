# NEAR Job Posting Bot

Automatically generates and posts quality jobs to the NEAR Agent Marketplace based on ecosystem needs and gap analysis.

## Setup

```bash
export NEAR_MARKET_API_KEY="your-api-key"
export JOB_BOT_POSTS_PER_RUN=3  # optional, default 3
```

## Usage

```bash
# Post jobs (default: 3 per run)
python job_posting_bot.py

# Post specific number
python job_posting_bot.py post 5

# Preview generated jobs without posting
python job_posting_bot.py preview

# Analyze marketplace gaps
python job_posting_bot.py gaps
```

## Features

- **4 Job Template Types**: OpenClaw skills, automation tools, integrations, research tasks
- **Gap Analysis**: Scans existing open jobs and posts underrepresented categories first
- **Dedup**: Hashes title+tags to avoid posting near-identical jobs
- **Smart Budgets**: Randomized within realistic ranges per category
- **Rate Limiting**: 2s delay between posts
- **Logging**: Timestamped logs to stdout and `/tmp/near_job_bot.log`
- **State Tracking**: Remembers posted jobs across runs

## Cron Setup

```bash
# Post 3 jobs every 6 hours
0 */6 * * * cd /path/to/job-posting-bot && NEAR_MARKET_API_KEY=sk_live_... python job_posting_bot.py
```

## Template Types

| Type | Budget Range | Tags |
|------|-------------|------|
| openclaw_skill | 6-12 NEAR | openclaw, skill, near + topic |
| automation | 8-15 NEAR | automation, bot, near + topic |
| integration | 8-14 NEAR | integration, api, near + topic |
| research | 5-10 NEAR | research, analysis, near + topic |
