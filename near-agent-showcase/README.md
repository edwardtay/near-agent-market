# NEAR Agent Showcase - Portfolio Builder

Fetch agent profiles from the NEAR AI marketplace and generate standalone HTML portfolio pages.

## Features

- **list_agents** - Browse available agents with stats
- **agent_stats** - Detailed breakdown of an agent's performance
- **generate_portfolio** - Create a self-contained HTML portfolio page

## Requirements

- Python 3.10+
- No external dependencies (uses stdlib only)

## Usage

```bash
# List agents
python showcase.py list_agents --limit 10

# View agent stats
python showcase.py agent_stats alice.near/code-review/1.0.0

# Generate portfolio HTML
python showcase.py generate_portfolio alice.near/code-review/1.0.0 --output portfolio.html

# Generate to stdout (pipe or redirect)
python showcase.py generate_portfolio alice.near/code-review/1.0.0 > portfolio.html
```

## API

The module can also be imported and used programmatically:

```python
from showcase import list_agents, agent_stats, generate_portfolio

# List agents
agents = list_agents(limit=5)
for a in agents:
    print(a["name"], a.get("total_runs", 0))

# Get stats
stats = agent_stats("alice.near/code-review/1.0.0")
print(f"{stats['name']}: {stats['total_earnings_near']} NEAR earned")

# Generate HTML
html = generate_portfolio("alice.near/code-review/1.0.0", output_path="portfolio.html")
```

## Output

The generated portfolio includes:
- Agent name, description, and ID
- Stats grid (jobs completed, total runs, earnings, rating)
- Skills/tags list
- Completed jobs history with tags and earnings
- Link to the marketplace profile

## Data Source

Uses the NEAR AI marketplace API at `https://api.near.ai/v1`. Falls back to demo data when the API is unreachable, so the tool always produces output.

## License

MIT
