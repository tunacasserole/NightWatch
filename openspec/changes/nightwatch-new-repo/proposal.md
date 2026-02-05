# NightsWatch - New Repo Proposal

**Status**: Completed
**Approved**: 2025-02-05
**Completed**: 2025-02-05
**Reviewer**: Claude (OpenSpec review)
**Implementation Evidence**: The entire NightWatch codebase (`nightwatch/` package, `tests/`, `pyproject.toml`) IS this proposal's implementation. Commit: `dce5167` (Initial NightWatch implementation)

## The Problem with TheFixer

TheFixer was built around a **webhook-driven, always-on server** pattern:
- FastAPI web server running 24/7 waiting for New Relic webhooks
- PostgreSQL database for state tracking
- Alembic migrations for schema management
- Async everything (asyncpg, AsyncAnthropic, AsyncWebClient)
- Vector memory with ChromaDB + sentence-transformers
- GitHub slash commands (`/create-pr`) requiring webhook listeners
- Two-phase analysis (quick + background deep) to avoid blocking webhooks
- Streaming SSE endpoints for real-time progress
- Duplicate detection via database queries

**90% of this infrastructure exists to support the webhook pattern.** The actual value — Claude analyzing errors and creating fixes — is buried under layers of server plumbing.

## The NightsWatch Philosophy

**Run once. Analyze everything. Report. Done.**

NightsWatch is a **batch CLI tool** that runs once per day (cron/launchd), queries New Relic for the day's errors, has Claude analyze the most interesting ones, and creates GitHub issues + draft PRs.

No server. No database. No webhooks. No embeddings. No slash commands. No streaming. No background tasks.

Inspired by Ryan Carson's "compound engineering" approach: a nightly autonomous loop that does real work while you sleep, with draft PRs ready for human review in the morning.

---

## What We Keep from TheFixer

### 1. The Agentic Loop (Core Value)
The heart of TheFixer — Claude iterating with tools to explore a codebase — is the whole point. We keep this pattern exactly:

```python
while iteration < max_iterations:
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        messages=messages,
    )

    if response.stop_reason == "tool_use":
        tool_results = execute_tools(response.content)
        messages.append({"role": "assistant", "content": serialize_content(response.content)})
        messages.append({"role": "user", "content": tool_results})
    else:
        return parse_analysis(response.content)
```

### 2. The Four Tools
Same tools, same purpose — let Claude explore the target repo:
- `read_file` — Read file contents from GitHub
- `search_code` — Search for code patterns via GitHub API
- `list_directory` — Browse directory structure
- `get_error_traces` — Fetch detailed traces from New Relic

### 3. New Relic NRQL Queries
Same GraphQL queries to fetch error data, but we **pull on our schedule** instead of reacting to webhooks:
- `TransactionError` — errors with class, message, transaction, trace
- `ErrorTrace` — detailed stack traces
- Error grouping/ranking by frequency

### 4. GitHub Issue + PR Creation
Same PyGithub patterns:
- Create labeled issues with structured analysis
- Create feature branches with file changes
- Open draft PRs for human review

### 5. Slack Notification
Simplified — one summary message per run instead of per-alert notifications.

### 6. Retry Logic
The exponential backoff for Anthropic API (529/429/connection errors) is battle-tested. Keep it.

---

## What We Strip

| Component | TheFixer | NightsWatch | Why |
|-----------|----------|------------|-----|
| Web framework | FastAPI | **None** | No server needed |
| Database | PostgreSQL + SQLAlchemy | **None** | No state to persist |
| Migrations | Alembic | **None** | No database |
| Webhooks | New Relic → us | **We query NR** | Pull, don't push |
| Async | Everything async | **Sync Python** | Batch job, no concurrency needed |
| Vector memory | ChromaDB + embeddings | **None** | Explicitly removed |
| Slash commands | `/create-pr` listener | **None** | No triggers |
| Streaming | SSE endpoints | **None** | No real-time UI |
| Two-phase analysis | Quick + deep | **One thorough pass** | No webhook timeout pressure |
| Duplicate detection | DB-backed matching | **GitHub issue search** | Check existing issues via API |
| Error matching | DB-backed patterns | **Simple config file** | YAML/JSON ignore list |
| Background tasks | FastAPI BackgroundTasks | **None** | Sequential batch execution |
| Issue state service | CRUD operations | **None** | No database |

---

## What We Add (Modern Anthropic API Patterns)

### 1. Structured Outputs (replaces JSON parsing from text)
Instead of asking Claude to emit JSON in its text response and regex-parsing it:

```python
from pydantic import BaseModel

class Analysis(BaseModel):
    title: str
    reasoning: str
    has_fix: bool
    confidence: Literal["high", "medium", "low"]
    file_changes: list[FileChange]

response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=8192,
    system=SYSTEM_PROMPT,
    tools=TOOLS,
    messages=messages,
    output_config={
        "format": {
            "type": "json_schema",
            "schema": Analysis.model_json_schema()
        }
    }
)
```

No more `_parse_analysis()` with regex fallbacks. Guaranteed schema compliance.

### 2. Prompt Caching
The system prompt + tool definitions are identical across every analysis. Cache them:

```python
system=[
    {
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"}
    }
]
```

When analyzing multiple errors in one run, this saves significant tokens and latency.

### 3. Extended Thinking (for complex errors)
For errors that need deep reasoning before tool use:

```python
response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=16000,
    thinking={"type": "enabled", "budget_tokens": 8000},
    system=SYSTEM_PROMPT,
    tools=TOOLS,
    messages=messages,
)
```

### 4. Strict Tool Definitions
Guarantee Claude's tool inputs match the schema:

```python
tools=[{
    "name": "read_file",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
        "additionalProperties": False
    }
}]
```

### 5. Synchronous Client
No reason for async in a batch job:

```python
from anthropic import Anthropic  # not AsyncAnthropic
client = Anthropic()
```

---

## Architecture

### File Structure

```
nightwatch/
├── nightwatch.py          # CLI entry point
├── config.py              # Settings from env vars
├── analyzer.py            # Claude agentic loop + tools
├── newrelic.py            # NRQL queries, error fetching + ranking
├── github.py              # Issues, PRs, code reading
├── slack.py               # Summary notification
├── models.py              # Pydantic models (Analysis, FileChange, Error)
├── prompts.py             # System prompt + tool definitions
├── ignore.yml             # Known errors to skip
├── .env.example           # Required environment variables
├── pyproject.toml         # Dependencies
└── README.md
```

**~10 files. ~1500 lines total.** Compare to TheFixer's ~30+ files and ~5000+ lines.

### Data Flow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  New Relic   │────▶│  NightsWatch  │────▶│   GitHub    │
│  (query)     │     │  (analyze)   │     │  (issues+PRs)│
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │    Slack    │
                    │  (summary)  │
                    └─────────────┘
```

**Step by step:**

1. **Query New Relic** — NRQL for TransactionErrors in last 24h
2. **Group & Rank** — Deduplicate, count occurrences, rank by frequency × severity
3. **Filter** — Skip known/ignored errors (from `ignore.yml`), skip errors with existing open GitHub issues
4. **Select Top N** — Pick the most impactful errors (configurable, default 5)
5. **Analyze Each** — Run Claude agentic loop with tools for each error
6. **Create Issues** — GitHub issue with structured analysis for each
7. **Create PRs** — Draft PR for any analysis with `has_fix=true` and `confidence != "low"`
8. **Notify** — Single Slack message summarizing the run

### Entry Point

```bash
# Daily cron / launchd
python -m nightwatch run

# Or with options
python -m nightwatch run --max-errors 3 --dry-run --since 12h
```

### Configuration

```env
# .env
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
GITHUB_REPO=g2crowd/ue
NEW_RELIC_API_KEY=NRAK-...
NEW_RELIC_ACCOUNT_ID=12345
NEW_RELIC_APP_NAME=ue-production
SLACK_WEBHOOK_URL=https://hooks.slack.com/...

# Optional
NIGHTWATCH_MAX_ERRORS=5        # Max errors to analyze per run
NIGHTWATCH_SINCE=24h           # How far back to look
NIGHTWATCH_MODEL=claude-sonnet-4-5-20250929
NIGHTWATCH_MAX_ITERATIONS=15   # Max tool-use iterations per error
NIGHTWATCH_DRY_RUN=false       # Analyze but don't create issues/PRs
```

---

## Dependency List

```toml
[project]
dependencies = [
    "anthropic>=0.77.0",    # Claude API (sync client)
    "PyGithub>=2.1.0",      # GitHub API
    "httpx>=0.26.0",        # New Relic GraphQL queries
    "pydantic>=2.0",        # Data models + structured outputs
    "pydantic-settings",    # Config from env
    "python-dotenv",        # .env file loading
    "pyyaml",               # ignore.yml config
]
```

**7 dependencies.** TheFixer has 15+ including FastAPI, SQLAlchemy, asyncpg, Alembic, chromadb, sentence-transformers, uvicorn, etc.

No database drivers. No web framework. No vector store. No ML libraries.

---

## Scheduling (macOS launchd)

Following Ryan Carson's pattern:

```xml
<!-- ~/Library/LaunchAgents/com.nightwatch.daily.plist -->
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nightwatch.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/nightwatch/venv/bin/python</string>
        <string>-m</string>
        <string>nightwatch</string>
        <string>run</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/nightwatch</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>6</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/path/to/nightwatch/logs/nightwatch.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/nightwatch/logs/nightwatch.log</string>
</dict>
</plist>
```

Runs at 6 AM. You wake up to GitHub issues + draft PRs ready for review.

---

## System Prompt (Simplified)

```python
SYSTEM_PROMPT = """You are NightsWatch, an AI agent that analyzes Ruby on Rails
production errors and proposes fixes.

For each error you receive:

1. Extract the controller/action from the transactionName
2. Use search_code to find the relevant controller file
3. Use read_file to examine the actual source code
4. Search for related models, services, and concerns
5. Identify the root cause
6. Propose a concrete fix if possible

RULES:
- ALWAYS search and read the actual source code. Never guess.
- If you find the root cause but aren't sure about the fix, say so.
- If the error is in a gem or third-party code, note that.
- Be specific about file paths and line numbers.
"""
```

~150 words vs TheFixer's ~800+ word system prompt. Same core instructions, no fluff.

---

## Error Ranking Algorithm

Instead of reacting to every alert as it fires, NightsWatch ranks the day's errors intelligently:

```python
def rank_errors(errors: list[ErrorGroup]) -> list[ErrorGroup]:
    """Rank errors by impact score."""
    for error in errors:
        error.score = (
            error.occurrence_count * 0.4 +      # Frequency matters most
            severity_weight(error.error_class) * 0.3 +  # NoMethodError > warning
            recency_weight(error.last_seen) * 0.2 +     # Recent = more relevant
            user_impact_weight(error.transaction) * 0.1  # User-facing > background
        )
    return sorted(errors, key=lambda e: e.score, reverse=True)
```

This means NightsWatch naturally focuses on the errors that matter most — high-frequency, user-facing, recent errors get analyzed first.

---

## Duplicate Avoidance (Without a Database)

Instead of PostgreSQL for duplicate detection, just search GitHub issues:

```python
def has_existing_issue(github: Github, repo_name: str, error_class: str, transaction: str) -> bool:
    """Check if an open issue already exists for this error."""
    query = f"repo:{repo_name} is:issue is:open label:nightwatch {error_class}"
    results = github.search_issues(query)
    for issue in results:
        if transaction in issue.title or error_class in issue.title:
            return True
    return False
```

Simple. Stateless. No database migrations.

---

## Slack Summary (One Message Per Run)

Instead of per-error notifications, send one morning summary:

```
NightsWatch Daily Report — Feb 5, 2026

Analyzed 5 errors from the last 24h:

1. ✅ NoMethodError in ProductsController#show — Draft PR #427 opened
2. ✅ ActiveRecord::RecordNotFound in OrdersController#update — Issue #1203 created
3. ⚠️ Redis::TimeoutError in CacheService — Needs investigation (issue #1204)
4. ❌ ActionView::Template::Error — Third-party gem issue, skipped
5. ❌ Net::ReadTimeout — Transient network error, skipped

PRs ready for review: 1
Issues created: 2
Errors skipped: 2
```

---

## Migration Path

1. Create new repo `nightwatch` (or `night-watch`)
2. Copy over the core patterns from TheFixer:
   - Agentic loop logic from `claude_service.py`
   - NRQL queries from `newrelic_service.py`
   - GitHub operations from `github_service.py`
   - Slack basics from `slack_service.py`
3. Strip all async, replace with sync equivalents
4. Strip all database/web/webhook code
5. Add new patterns: structured outputs, prompt caching, extended thinking
6. Add error ranking and batch processing
7. Add CLI entry point and launchd config
8. TheFixer continues running until NightsWatch proves itself, then sunset it

---

## Summary: TheFixer vs NightsWatch

| Aspect | TheFixer | NightsWatch |
|--------|----------|------------|
| Pattern | Webhook-driven server | Batch CLI (cron) |
| Runtime | Always on | Runs once, exits |
| Trigger | New Relic pushes to us | We pull from New Relic |
| Database | PostgreSQL | None |
| Web framework | FastAPI | None |
| Async | Everything | Nothing (sync) |
| Vector memory | ChromaDB | None |
| Dependencies | 15+ | 7 |
| Files | 30+ | ~10 |
| Lines of code | ~5000+ | ~1500 |
| Error selection | React to every alert | Rank and pick top N |
| Output format | JSON text parsing | Structured outputs (guaranteed) |
| Caching | None | Prompt caching |
| Thinking | Standard | Extended thinking |
| Notifications | Per-error Slack DM | Daily summary |
| PR creation | On-demand via `/create-pr` | Automatic for high-confidence fixes |
| Human review | React to notifications | Morning review of draft PRs |

**NightsWatch is TheFixer's brain in a 10x simpler body.**
