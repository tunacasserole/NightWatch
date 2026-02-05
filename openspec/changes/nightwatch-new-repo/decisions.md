# NightsWatch — Fundamental Decisions & Feature Port Analysis

## Part 1: Fundamental Project Decisions

### Decision 1: Execution Model
| Question | Answer |
|----------|--------|
| **How does it run?** | CLI batch job. `python -m nightwatch run` |
| **When does it run?** | Once per day via cron/launchd (e.g., 6 AM) |
| **How long does it run?** | ~5-20 minutes depending on error count |
| **What triggers it?** | Cron scheduler. Optionally manual `nightwatch run` |
| **What happens when it's done?** | Process exits with code 0 (success) or 1 (failure) |

### Decision 2: No Server
| Question | Answer |
|----------|--------|
| **Web framework?** | None. No FastAPI, no Flask, nothing. |
| **Endpoints?** | None. No HTTP listeners. |
| **CORS, middleware?** | N/A |
| **Health checks?** | Exit code + log file. No HTTP health endpoint. |
| **Background tasks?** | N/A — everything runs sequentially in foreground |

### Decision 3: No Database
| Question | Answer |
|----------|--------|
| **State storage?** | None persistent. GitHub issues ARE the state. |
| **Duplicate tracking?** | Search GitHub issues via API (label + title match) |
| **Known error patterns?** | `ignore.yml` config file (checked into repo) |
| **Processed alert log?** | Log file only. No database records. |
| **Migration system?** | N/A — no database, no Alembic |

### Decision 4: No Embeddings/Vector Memory
| Question | Answer |
|----------|--------|
| **Learning from past fixes?** | No. Explicit requirement to remove. |
| **Similar error matching?** | No vector similarity. GitHub issue search only. |
| **ChromaDB?** | Removed entirely. |
| **sentence-transformers?** | Removed entirely. |

### Decision 5: Synchronous Python
| Question | Answer |
|----------|--------|
| **Async?** | No. Sync `Anthropic()` client, sync `httpx`, sync everything. |
| **Why?** | Batch job processes errors sequentially. No concurrency needed. |
| **Event loop?** | None. No `asyncio.run()`, no `await`. |
| **Exception**: | `httpx` may still be used for NR queries (it has sync mode) |

### Decision 6: Pull, Don't Push
| Question | Answer |
|----------|--------|
| **New Relic integration model?** | We query NR on our schedule |
| **Webhook from NR?** | No. NR doesn't post to us. |
| **What do we query?** | `TransactionError` + `ErrorTrace` via NRQL, last 24h |
| **Error selection?** | Rank by frequency × severity, pick top N |

### Decision 7: Model Selection
| Question | Answer |
|----------|--------|
| **Default model?** | `claude-sonnet-4-5-20250929` (fast, capable, cost-effective) |
| **Configurable?** | Yes, via `NIGHTWATCH_MODEL` env var |
| **Why not Opus?** | Sonnet is sufficient for error analysis. Opus for when we want max quality. |
| **Extended thinking?** | Enabled by default for complex error analysis |

### Decision 8: Output Targets
| Question | Answer |
|----------|--------|
| **GitHub Issues?** | Yes — one per analyzed error |
| **GitHub PRs?** | Yes — draft PR for high-confidence fixes |
| **Slack?** | Yes — one daily summary message |
| **Log file?** | Yes — detailed run log |
| **Console output?** | Yes — progress during manual runs |

### Decision 9: CLI Interface
| Question | Answer |
|----------|--------|
| **Entry point?** | `python -m nightwatch run` |
| **Flags?** | `--max-errors N`, `--since 12h`, `--dry-run`, `--verbose` |
| **No subcommands?** | Just `run`. Maybe `nightwatch check` for config validation later. |
| **No interactive mode?** | Correct. Runs, does work, exits. |

### Decision 10: Structured Outputs
| Question | Answer |
|----------|--------|
| **How does Claude return analysis?** | Anthropic structured outputs (`output_config` with JSON schema) |
| **Pydantic integration?** | Yes — `client.messages.parse()` with Pydantic models |
| **No more regex JSON parsing?** | Correct. Guaranteed schema compliance. |
| **Fallback for malformed responses?** | Not needed — structured outputs guarantee the schema |

---

## Part 2: Complete TheFixer Feature Inventory — Port Decisions

### Legend
- **PORT** = Bring to NightsWatch (simplified where noted)
- **STRIP** = Do not port (infrastructure/overhead)
- **SIMPLIFY** = Port the concept but rewrite simpler
- **DEFER** = Nice to have, add later if needed

---

### Category 1: Application Infrastructure (12 features → 0 ported)

| # | Feature | TheFixer | Decision | Rationale |
|---|---------|----------|----------|-----------|
| 1.1 | FastAPI App Setup | Server init, CORS, lifespan | **STRIP** | No server |
| 1.2 | Health Check Endpoint | `/health` HTTP | **STRIP** | Exit code instead |
| 1.3 | Legacy URL Redirect | `/webhook` → `/webhooks` | **STRIP** | No URLs |
| 1.4 | CORS Middleware | Cross-origin headers | **STRIP** | No HTTP |
| 2.1 | NR Alert Webhook | `POST /webhooks/newrelic` | **STRIP** | We pull, not push |
| 2.2 | NR Health Check | `GET /webhooks/newrelic` | **STRIP** | No endpoints |
| 2.3 | Debug Webhook | `POST /webhooks/newrelic/debug` | **STRIP** | `--dry-run` flag instead |
| 2.4 | SSE Streaming | Real-time progress events | **STRIP** | Console output instead |
| 2.5 | GitHub Webhook | `POST /webhooks/github` | **STRIP** | No event listeners |
| 3.3 | Sync Alert Processing | `process_alert_sync()` | **STRIP** | Everything is sync |
| 16.4 | Async DB Engine | SQLAlchemy async setup | **STRIP** | No database |
| 16.5 | FastAPI DB Dependency | `get_db()` generator | **STRIP** | No database |

---

### Category 2: Database & State Management (27 features → 0 ported)

| # | Feature | TheFixer | Decision | Rationale |
|---|---------|----------|----------|-----------|
| 3.5 | Duplicate Alert Detection | DB ProcessedAlert check | **STRIP** | GitHub issue search instead |
| 3.6 | Alert Logging | Insert ProcessedAlert | **STRIP** | Log file instead |
| 6.1 | Issue Triage Agent | Claude triage on new issues | **STRIP** | No event triggers |
| 6.3 | Comment Response Agent | Claude responds to comments | **STRIP** | No event triggers |
| 6.4 | PR Closed Handler | Records merge/close | **STRIP** | No event triggers |
| 6.5 | Ignore Error Label | Label → KnownError | **STRIP** | `ignore.yml` instead |
| 12.1 | PR Merged Recording | Success feedback | **STRIP** | No feedback loop |
| 12.2 | PR Closed Recording | Failure feedback | **STRIP** | No feedback loop |
| 12.3 | Issue Reopened Recording | Incomplete fix tracking | **STRIP** | No event triggers |
| 12.4 | Learning Statistics | Fix success rate | **STRIP** | No database |
| 13.1 | Issue Triage | Full triage system | **STRIP** | Not error analysis |
| 13.2 | Comment Response | Conversation handler | **STRIP** | Not error analysis |
| 13.3 | Triage System Prompt | Triage prompt | **STRIP** | Not needed |
| 13.4 | Conversation Prompt | Conversation prompt | **STRIP** | Not needed |
| 15.1-15.10 | Issue State Service | All 10 DB CRUD operations | **STRIP** | No database |
| 16.1 | ProcessedAlert Model | SQLAlchemy model | **STRIP** | No database |
| 16.2 | Issue Model | SQLAlchemy model | **STRIP** | No database |
| 16.3 | KnownError Model | SQLAlchemy model | **STRIP** | `ignore.yml` instead |

---

### Category 3: Vector Memory (7 features → 0 ported)

| # | Feature | TheFixer | Decision | Rationale |
|---|---------|----------|----------|-----------|
| 10.1 | Error Signature Generation | Regex normalization | **STRIP** | No vector DB |
| 10.2 | Analysis Storage | ChromaDB embeddings | **STRIP** | Explicitly removed |
| 10.3 | Similar Error Search | Cosine similarity | **STRIP** | Explicitly removed |
| 10.4 | Fix Outcome Recording | Success/failure tracking | **STRIP** | No feedback loop |
| 10.5 | Reuse Count Tracking | Counter metrics | **STRIP** | No vector DB |
| 10.6 | Memory Statistics | Collection stats | **STRIP** | No vector DB |
| 10.7 | Failed Analysis Pruning | ChromaDB cleanup | **STRIP** | No vector DB |

---

### Category 4: Claude AI Analysis (11 features → 8 ported)

| # | Feature | TheFixer | Decision | Rationale |
|---|---------|----------|----------|-----------|
| 4.1 | System Prompt | Agent behavior definition | **PORT** | Core value. Rewrite simpler. |
| 4.2 | Tool Definitions | 4 tools with schemas | **PORT** | Core value. Add `strict: true`. |
| 4.3 | Quick Analysis (Phase 1) | 3-iteration fast pass | **STRIP** | No two-phase needed |
| 4.4 | Deep Research (Phase 2) | 7-iteration deep pass | **STRIP** | Replaced by single thorough pass |
| 4.5 | Full Analysis | 10-iteration complete | **PORT** | This becomes THE analysis. 15 iterations. |
| 4.6 | Agentic Tool Loop | Tool dispatch cycle | **PORT** | Core pattern. Identical logic. |
| 4.7 | Response Parsing | XML/JSON extraction | **SIMPLIFY** | Replace with structured outputs |
| 4.8 | Context Compression | Conversation summarization | **PORT** | Still needed for long tool chains |
| 4.9 | Trace Summarization | Error trace compression | **PORT** | Reduces token usage |
| 4.10 | Rate Limit Handling | Exponential backoff | **PORT** | Battle-tested. Keep as-is. |
| 4.11 | API Call Metrics | Usage tracking | **PORT** | Good for logs and cost tracking |

---

### Category 5: GitHub Integration (14 features → 11 ported)

| # | Feature | TheFixer | Decision | Rationale |
|---|---------|----------|----------|-----------|
| 5.1 | File Reading | `read_file()` from GitHub | **PORT** | Tool implementation |
| 5.2 | Directory Listing | `list_directory()` | **PORT** | Tool implementation |
| 5.3 | Code Search | `search_code()` | **PORT** | Tool implementation |
| 5.4 | Branch Creation | Create feature branches | **PORT** | Needed for PRs |
| 5.5 | File Creation/Update | Commit changes to branch | **PORT** | Needed for PRs |
| 5.6 | Issue Creation | Create labeled issues | **PORT** | Primary output |
| 5.7 | PR Creation | Create draft PRs | **PORT** | Primary output |
| 5.8 | Duplicate Issue Detection | Multi-level fuzzy match | **SIMPLIFY** | GitHub search API only, no DB |
| 5.9 | Occurrence Comment | Comment on existing issue | **PORT** | Useful for repeat errors |
| 5.10 | Open Issue/PR Limits | WIP limits | **PORT** | Prevents flooding |
| 5.11 | Error Pattern Extraction | Label → ignore list | **STRIP** | Manual `ignore.yml` instead |
| 5.12 | Issue Title Building | Title formatting | **PORT** | Reuse formatting |
| 5.13 | Issue Body Building | Markdown body | **PORT** | Reuse template |
| 5.14 | PR Body Building | PR markdown | **PORT** | Reuse template |

---

### Category 6: New Relic Integration (4 features → 4 ported + 2 new)

| # | Feature | TheFixer | Decision | Rationale |
|---|---------|----------|----------|-----------|
| 8.1 | Error Trace Fetching | GraphQL NRQL queries | **PORT** | Core data source |
| 8.2 | Error Details Search | Message-based search | **PORT** | Useful for context |
| 8.3 | Transaction Traces | APM entity data | **PORT** | Useful for context |
| 8.4 | Errors Inbox URL | Deep link generation | **PORT** | Great for issue links |
| NEW | Error Grouping & Ranking | Group by class+transaction, rank by impact | **NEW** | Core new capability |
| NEW | Batch Error Fetching | Query last 24h, all errors | **NEW** | Pull model requires this |

---

### Category 7: Slack Notifications (4 features → 2 ported)

| # | Feature | TheFixer | Decision | Rationale |
|---|---------|----------|----------|-----------|
| 9.1 | User Lookup | Find user by display name | **SIMPLIFY** | Use webhook URL instead of bot token |
| 9.2 | DM Channel Opening | Open DM conversation | **STRIP** | Webhook posts to channel instead |
| 9.3 | Rich Notification | Block Kit per-error message | **SIMPLIFY** | One daily summary message |
| 9.4 | SSL Context | macOS certifi fix | **PORT** | Still needed on macOS |

**Alternative Slack approach**: Use a simple webhook URL instead of bot token. Post one formatted message to a channel. No user lookup needed.

---

### Category 8: PR Correlation Service (5 features → 3 ported)

| # | Feature | TheFixer | Decision | Rationale |
|---|---------|----------|----------|-----------|
| 11.1 | Recent PR Retrieval | Merged PRs in last N hours | **PORT** | Helps identify cause |
| 11.2 | Error-PR Correlation | Link errors to changed files | **PORT** | High value signal |
| 11.3 | Search Term Extraction | Transaction → file paths | **PORT** | Needed for correlation |
| 11.4 | Correlation Formatting | Markdown output | **PORT** | Include in issue body |
| 11.5 | Confidence Calculation | File overlap scoring | **DEFER** | Nice to have, low priority |

---

### Category 9: Alert Filtering (2 features → 2 ported)

| # | Feature | TheFixer | Decision | Rationale |
|---|---------|----------|----------|-----------|
| 3.1 | Error vs Metric Filtering | Deny list for non-errors | **SIMPLIFY** | Filter by NRQL query instead |
| 3.4 | Known Error Detection | Pattern matching | **SIMPLIFY** | `ignore.yml` with patterns |

---

### Category 10: Label Management (2 features → 1 ported)

| # | Feature | TheFixer | Decision | Rationale |
|---|---------|----------|----------|-----------|
| 7.1 | Label Definitions | Config with colors/descriptions | **PORT** | Consistent labeling |
| 7.2 | Label Synchronization | Create missing labels | **SIMPLIFY** | One-time setup or first-run |

---

### Category 11: Cache Service (3 features → 0 ported)

| # | Feature | TheFixer | Decision | Rationale |
|---|---------|----------|----------|-----------|
| 14.1 | In-Memory Cache | TTL-based cache | **STRIP** | Single run, no caching needed |
| 14.2 | Cache Statistics | Hit/miss tracking | **STRIP** | No cache |
| 14.3 | Expired Entry Cleanup | TTL expiration | **STRIP** | No cache |

---

### Category 12: Schema Definitions (7 features → 3 ported)

| # | Feature | TheFixer | Decision | Rationale |
|---|---------|----------|----------|-----------|
| 17.1 | NewRelicAlert Schema | Webhook payload model | **STRIP** | Different data model for batch |
| 17.2 | Analysis Schema | Claude output model | **PORT** | Core model, use for structured output |
| 17.3 | FileChange Schema | Code change model | **PORT** | Core model |
| 17.4 | GitHubPREvent Schema | PR webhook model | **STRIP** | No webhooks |
| 17.5 | GitHubIssue Schema | Issue webhook model | **STRIP** | No webhooks |
| 17.6 | IssueTriageResult Schema | Triage output | **STRIP** | No triage agent |
| 17.7 | ConversationEntry Schema | Chat history | **STRIP** | No conversations |
| NEW | ErrorGroup Schema | Grouped error with count, ranking | **NEW** | Core new model |
| NEW | RunReport Schema | Summary of entire run | **NEW** | For Slack + logging |

---

### Category 13: Configuration (5 features → 3 ported)

| # | Feature | TheFixer | Decision | Rationale |
|---|---------|----------|----------|-----------|
| 18.1 | Settings Management | pydantic-settings from env | **PORT** | Same pattern, fewer fields |
| 18.2 | Settings Caching | lru_cache singleton | **PORT** | Same pattern |
| 18.3 | Vector Memory Config | ChromaDB settings | **STRIP** | No vector memory |
| 18.4 | PR Correlation Config | Correlation settings | **PORT** | Keep correlation feature |
| 18.5 | Claude Configuration | Model + token settings | **PORT** | Same pattern |

---

## Part 3: Port Summary

### By the Numbers

| Category | TheFixer Features | Ported | Stripped | Simplified | New |
|----------|------------------|--------|----------|------------|-----|
| Infrastructure | 12 | 0 | 12 | 0 | 0 |
| Database/State | 27 | 0 | 27 | 0 | 0 |
| Vector Memory | 7 | 0 | 7 | 0 | 0 |
| Claude Analysis | 11 | 8 | 3 | 1 | 0 |
| GitHub | 14 | 11 | 1 | 1 | 0 |
| New Relic | 4 | 4 | 0 | 0 | 2 |
| Slack | 4 | 1 | 2 | 1 | 0 |
| PR Correlation | 5 | 3 | 0 | 0 | 0 |
| Alert Filtering | 2 | 0 | 0 | 2 | 0 |
| Labels | 2 | 1 | 0 | 1 | 0 |
| Cache | 3 | 0 | 3 | 0 | 0 |
| Schemas | 7 | 2 | 5 | 0 | 2 |
| Configuration | 5 | 3 | 2 | 0 | 0 |
| **TOTALS** | **85** | **33** | **62** | **6** | **4** |

### Translation
- **33 features ported** from TheFixer (the actual value)
- **62 features stripped** (server, DB, vector, webhook overhead)
- **6 features simplified** (concept kept, implementation reduced)
- **4 new features** (error ranking, batch fetching, new schemas)
- **37 total features** in NightsWatch (33 + 4 new)

**We're keeping 39% of features and dropping 61%.** But that 39% IS the product — the error analysis, code exploration, issue creation, and PR generation. The 61% we're dropping is infrastructure that existed only to support the webhook pattern.

---

## Part 4: New Capabilities (Not in TheFixer)

### 4.1 Error Ranking Engine
Rank the day's errors by impact score instead of processing every alert as it arrives.

```
score = frequency * 0.4 + severity * 0.3 + recency * 0.2 + user_impact * 0.1
```

This means NightsWatch naturally focuses on what matters most.

### 4.2 Structured Outputs
Use Anthropic's `output_config` with JSON schema instead of parsing JSON from text. Guaranteed schema compliance, no regex fallbacks.

### 4.3 Prompt Caching
Cache the system prompt + tool definitions across multiple error analyses in a single run. Saves tokens and latency when analyzing 5+ errors.

### 4.4 Extended Thinking
Enable Claude's extended thinking for deeper analysis before tool use. Better root cause identification.

### 4.5 Daily Summary Report
One Slack message summarizing the entire run: errors analyzed, issues created, PRs opened, errors skipped.

### 4.6 Dry Run Mode
`--dry-run` flag: analyze errors and print results without creating issues/PRs. Essential for testing.

### 4.7 Configurable Lookback
`--since 12h` or `--since 7d`: control how far back to look for errors. Default 24h for daily cron.

### 4.8 ignore.yml
Simple YAML file for known error patterns to skip:

```yaml
ignore:
  - pattern: "ActiveRecord::ConnectionTimeoutError"
    match: contains
    reason: "Transient connection pool issue, self-resolving"
  - pattern: "Net::ReadTimeout"
    match: contains
    reason: "External service timeout, not actionable"
  - pattern: "Rack::Timeout::RequestTimeoutException"
    match: exact
    reason: "Long-running requests, tracked separately"
```

No database. Just a file. Easy to review, edit, commit.

---

## Part 5: Supported Commands & Interfaces

### CLI Commands

```bash
# Primary command — analyze today's errors
nightwatch run

# With options
nightwatch run --max-errors 5       # Analyze top 5 errors (default)
nightwatch run --since 12h          # Look back 12 hours instead of 24
nightwatch run --dry-run            # Analyze but don't create issues/PRs
nightwatch run --verbose            # Detailed console output
nightwatch run --model claude-opus-4-20250514  # Override model

# Config validation
nightwatch check                    # Validate env vars and API access
```

### No HTTP Endpoints
Zero. None. Not a single one.

### No GitHub Commands
No `/create-pr`. No comment handlers. No label triggers.

### No Webhook Receivers
Nothing listens. Nothing waits. Run → work → exit.

---

## Part 6: Dependency Comparison

### TheFixer (15+ packages)
```
anthropic, PyGithub, slack-sdk, httpx, fastapi, uvicorn,
sqlalchemy, asyncpg, alembic, chromadb, sentence-transformers,
pydantic, pydantic-settings, python-dotenv, certifi
```

### NightsWatch (7 packages)
```
anthropic          # Claude API (sync client)
PyGithub           # GitHub API
httpx              # New Relic GraphQL (sync mode)
pydantic           # Data models + structured outputs
pydantic-settings  # Config from env
python-dotenv      # .env loading
pyyaml             # ignore.yml parsing
```

**Removed**: fastapi, uvicorn, sqlalchemy, asyncpg, alembic, chromadb, sentence-transformers, slack-sdk

**Slack**: Use simple `httpx.post()` to webhook URL instead of full slack-sdk. One less dependency.

---

## Part 7: File Structure

```
nightwatch/
├── __main__.py        # CLI entry point (argparse)
├── config.py          # Settings from env (pydantic-settings)
├── models.py          # Pydantic models (Analysis, FileChange, ErrorGroup, RunReport)
├── prompts.py         # System prompt + tool definitions
├── analyzer.py        # Claude agentic loop + tool execution
├── newrelic.py        # NRQL queries + error ranking
├── github.py          # Issues, PRs, code reading, duplicate check
├── slack.py           # Daily summary webhook post
├── runner.py          # Main orchestration: fetch → rank → analyze → output
├── ignore.yml         # Known error patterns to skip
├── .env.example       # Required env vars
├── pyproject.toml     # Project config + dependencies
└── README.md          # Setup + usage
```

**12 files. ~1500 lines estimated.**
