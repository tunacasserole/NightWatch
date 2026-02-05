# NightWatch

AI-powered production error analysis. Run once. Analyze everything. Report. Done.

NightWatch is a batch CLI tool that queries New Relic for production errors, analyzes them with Claude (Anthropic), and creates GitHub issues + draft PRs with proposed fixes. A daily Slack DM keeps you informed.

## How It Works

```
New Relic errors → Rank & filter → Claude agentic analysis → GitHub issues + draft PR → Slack report
```

1. **Fetch** — NRQL query groups errors by `error.class` + `transactionName`
2. **Rank** — Weighted scoring: frequency (40%) + severity (30%) + recency (20%) + user impact (10%)
3. **Filter** — `ignore.yml` patterns remove known transient errors
4. **Analyze** — Claude reads your actual codebase via GitHub, identifies root causes, proposes fixes
5. **Report** — Slack DM with a summary of all analyzed errors
6. **Issues** — Top actionable errors become GitHub issues (with duplicate detection)
7. **PR** — Highest-confidence fix gets a draft PR
8. **Notify** — Follow-up Slack message with issue/PR links

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager

### Install

```bash
git clone https://github.com/g2crowd/NightWatch.git
cd NightWatch
uv sync
```

### Configure

Copy the example env and fill in your values:

```bash
cp .env.example .env
```

Required environment variables:

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key |
| `GITHUB_TOKEN` | GitHub personal access token |
| `GITHUB_REPO` | Target repo (e.g. `g2crowd/ue`) |
| `NEW_RELIC_API_KEY` | New Relic user API key |
| `NEW_RELIC_ACCOUNT_ID` | New Relic account ID |
| `NEW_RELIC_APP_NAME` | New Relic application name |
| `SLACK_BOT_TOKEN` | Slack bot token (`xoxb-...`) |
| `SLACK_NOTIFY_USER` | Slack display name to DM |

Optional (with defaults):

| Variable | Default | Description |
|----------|---------|-------------|
| `NIGHTWATCH_MAX_ERRORS` | `5` | Max errors to analyze per run |
| `NIGHTWATCH_MAX_ISSUES` | `3` | Max GitHub issues to create |
| `NIGHTWATCH_SINCE` | `24h` | Lookback period |
| `NIGHTWATCH_MODEL` | `claude-sonnet-4-5-20250929` | Claude model |
| `NIGHTWATCH_MAX_ITERATIONS` | `15` | Max tool-use iterations per error |
| `NIGHTWATCH_DRY_RUN` | `false` | Analyze only, no side effects |
| `NIGHTWATCH_MAX_OPEN_ISSUES` | `10` | WIP limit for open issues |
| `GITHUB_BASE_BRANCH` | `main` | Target branch for PRs |

### Validate

```bash
python -m nightwatch check
```

This checks connectivity to all four APIs (New Relic, GitHub, Slack, Claude).

### Run

```bash
# Default: top 5 errors from last 24h
python -m nightwatch run

# Customize
python -m nightwatch run --max-errors 3 --since 12h
python -m nightwatch run --dry-run --verbose
python -m nightwatch run --model claude-opus-4-20250514
```

## CLI Reference

```
python -m nightwatch run [options]
```

| Flag | Description |
|------|-------------|
| `--since` | Lookback period (e.g. `24h`, `12h`, `7d`) |
| `--max-errors` | Max errors to analyze |
| `--max-issues` | Max GitHub issues to create |
| `--dry-run` | Analyze only — no issues, PRs, or Slack |
| `--verbose` | Show Claude iteration details |
| `--model` | Override Claude model |

```
python -m nightwatch check
```

Validates all config and API connectivity.

## Architecture

```
nightwatch/
├── __main__.py      # CLI entry point (argparse)
├── config.py        # Settings from env vars (pydantic-settings)
├── models.py        # Data models (ErrorGroup, Analysis, RunReport, etc.)
├── newrelic.py      # NRQL queries, error ranking, ignore filtering
├── prompts.py       # Claude system prompt + tool definitions
├── analyzer.py      # Claude agentic loop with tool execution
├── github.py        # Issues, PRs, duplicate detection, code tools
├── slack.py         # Bot DM reports (Block Kit)
├── correlation.py   # Link errors to recently merged PRs
└── runner.py        # Pipeline orchestration (11 steps)
```

### Claude's Tools

During analysis, Claude has access to four tools backed by the GitHub API:

| Tool | Purpose |
|------|---------|
| `read_file` | Read source files from the repo |
| `search_code` | Search for code patterns |
| `list_directory` | Browse directory structure |
| `get_error_traces` | Fetch additional New Relic traces |

### GitHub Output

- **Issues**: Labeled `nightwatch`, `has-fix` or `needs-investigation`, `confidence:{level}`
- **Duplicate detection**: Multi-level matching (error class + transaction → class only → transaction only)
- **Occurrence comments**: Existing issues get updated instead of duplicated
- **WIP limit**: Configurable cap on open nightwatch issues (default 10)
- **Draft PR**: One per run, highest-confidence fix only

### Ignore Patterns

Edit `ignore.yml` to skip known transient errors:

```yaml
ignore:
  - pattern: "Net::ReadTimeout"
    match: contains
    reason: "Transient external service timeout"
```

## Development

```bash
# Install with dev deps
uv sync --dev

# Run tests
uv run pytest tests/

# Lint
uv run ruff check nightwatch/ tests/

# Format
uv run ruff format nightwatch/ tests/
```

## License

Internal tool — G2.
