# Implementation Plan: NightsWatch New Repo

**Proposal Reference ID**: NW-001
**Status**: Approved
**Approved**: 2026-02-05
**Parent**: [proposal.md](./proposal.md)
**Date**: 2026-02-05
**Estimated Total Effort**: 3-4 days (with AI assistance)

---

## Prerequisites and Dependencies

### Required Before Starting
- Python 3.11+ installed
- `uv` package manager installed
- GitHub access token with repo, issues, and PR permissions
- New Relic API key (NRAK-...) with query access
- Anthropic API key (sk-ant-...)
- Slack webhook URL for notifications
- Access to the target repo (`g2crowd/ue`) for code reading and issue/PR creation

### External Dependencies
- `anthropic>=0.77.0` -- Claude API (sync client)
- `PyGithub>=2.1.0` -- GitHub API
- `httpx>=0.26.0` -- New Relic GraphQL queries
- `slack-sdk>=3.27.0` -- Slack notifications
- `pydantic>=2.0` -- Data models + structured outputs
- `pydantic-settings>=2.0` -- Config from env
- `python-dotenv>=1.0` -- .env file loading
- `pyyaml>=6.0` -- ignore.yml config
- `certifi` -- TLS certificates

### Internal Dependencies
- None (greenfield project, no dependencies on other specs)

---

## Phased Implementation Steps

### Phase 1: Project Skeleton and Configuration (4 hours)

**Goal**: Set up the project structure, configuration, and CLI entry point so `python -m nightwatch run --dry-run` starts and exits cleanly.

**Branch**: `feat/nw-skeleton`

#### Step 1.1 -- Initialize project
- Create `pyproject.toml` with all 9 dependencies
- Create `nightwatch/__init__.py` with version string
- Create `.env.example` with all required environment variables
- Run `uv init` and `uv sync` to verify dependency resolution

#### Step 1.2 -- Configuration module
- Create `nightwatch/config.py` with `Settings` class (pydantic-settings)
- Fields: anthropic_api_key, github_token, github_repo, new_relic_api_key, new_relic_account_id, new_relic_app_name, slack_webhook_url
- Optional: nightwatch_max_errors (5), nightwatch_since ("24h"), nightwatch_model, nightwatch_max_iterations (15), nightwatch_dry_run (false)

#### Step 1.3 -- Data models
- Create `nightwatch/models.py` with Pydantic models: ErrorGroup, Analysis, FileChange, ErrorAnalysisResult, IssueResult, RunReport

#### Step 1.4 -- CLI entry point
- Create `nightwatch/__main__.py` with argparse: run subcommand with --max-errors, --since, --dry-run, --verbose

#### Step 1.5 -- Write Phase 1 tests
- `tests/test_models.py` -- model construction, validation, serialization

---

### Phase 2: New Relic Integration (3 hours)

**Goal**: Fetch, group, rank, and filter production errors from New Relic.

**Branch**: `feat/nw-newrelic` | **Depends on**: Phase 1

#### Step 2.1 -- New Relic client (`nightwatch/newrelic.py`)
- GraphQL query for TransactionError events (NRQL)
- `fetch_errors(since)` and `fetch_traces(error_class, transaction)`

#### Step 2.2 -- Error ranking algorithm
- Scoring: occurrence_count * 0.4 + severity_weight * 0.3 + recency_weight * 0.2 + user_impact_weight * 0.1

#### Step 2.3 -- Error filtering and ignore.yml
- Create `nightwatch/ignore.yml` with example ignore rules
- `filter_errors()` and `has_existing_issue()` for GitHub dedup

#### Step 2.4 -- Tests (`tests/test_ranking.py`)

---

### Phase 3: Claude Agentic Loop (4 hours)

**Goal**: Core analysis engine -- Claude iterating with tools to explore a codebase.

**Branch**: `feat/nw-analyzer` | **Depends on**: Phase 1, Phase 2

#### Step 3.1 -- GitHub tools client (`nightwatch/github.py`)
- Methods: read_file(), search_code(), list_directory(), get_file_content()

#### Step 3.2 -- System prompt and tool definitions (`nightwatch/prompts.py`)
- SYSTEM_PROMPT, build_analysis_prompt(), TOOLS (4 tool definitions)
- Strict tool definitions with additionalProperties: false

#### Step 3.3 -- Agentic loop (`nightwatch/analyzer.py`)
- analyze_error() with agentic loop, structured output, prompt caching, extended thinking
- Retry logic: exponential backoff for 429/529/connection errors

#### Step 3.4 -- Tests (`tests/test_analyzer.py`, `tests/test_github.py`)

---

### Phase 4: GitHub Issues, PRs, and Slack (3 hours)

**Goal**: Create issues, draft PRs, send Slack summary.

**Branch**: `feat/nw-outputs` | **Depends on**: Phase 3

#### Step 4.1 -- Issue creation in `nightwatch/github.py`
#### Step 4.2 -- PR creation in `nightwatch/github.py`
#### Step 4.3 -- Slack notification (`nightwatch/slack.py`)
#### Step 4.4 -- Tests for outputs

---

### Phase 5: Pipeline Orchestration (2 hours)

**Goal**: Wire everything in `nightwatch/runner.py`.

**Branch**: `feat/nw-runner` | **Depends on**: Phases 1-4

#### Step 5.1 -- Runner: 8-step pipeline with dry-run and error isolation
- Steps: init, fetch, rank, select, analyze, issues, PRs, Slack

#### Step 5.2 -- Integration testing with mocked APIs

---

### Phase 6: Scheduling and Documentation (1 hour)

**Branch**: `feat/nw-scheduling` | **Depends on**: Phase 5

#### Step 6.1 -- launchd configuration (6 AM daily)
#### Step 6.2 -- README

---

## Files to Create/Modify

### New Files

| File | Phase | Lines (est) | Purpose |
|------|-------|-------------|---------|
| `nightwatch/__init__.py` | 1 | ~5 | Package init |
| `nightwatch/__main__.py` | 1 | ~60 | CLI entry point |
| `nightwatch/config.py` | 1 | ~50 | Settings |
| `nightwatch/models.py` | 1 | ~120 | Data models |
| `nightwatch/newrelic.py` | 2 | ~200 | New Relic queries |
| `nightwatch/github.py` | 3,4 | ~250 | GitHub API |
| `nightwatch/prompts.py` | 3 | ~80 | System prompt + tools |
| `nightwatch/analyzer.py` | 3 | ~300 | Claude agentic loop |
| `nightwatch/slack.py` | 4 | ~100 | Slack notifications |
| `nightwatch/runner.py` | 5 | ~200 | Pipeline orchestration |
| `nightwatch/ignore.yml` | 2 | ~20 | Ignore rules |
| `.env.example` | 1 | ~20 | Env var template |
| `tests/test_models.py` | 1 | ~80 | Model tests |
| `tests/test_ranking.py` | 2 | ~60 | Ranking tests |
| `tests/test_analyzer.py` | 3 | ~120 | Analyzer tests |
| `tests/test_github.py` | 3 | ~80 | GitHub tests |

**Total**: ~1500 lines across ~19 files

---

## Testing Strategy

### Unit Tests (Phases 1-4)
- All external API calls mocked (Anthropic, GitHub, New Relic, Slack)
- Model construction, ranking, tool dispatch, structured output parsing
- Issue/PR formatting, Slack message structure

### Integration Tests (Phase 5)
- End-to-end dry-run with mocked APIs
- Error isolation (one failure does not stop others)

### Manual Validation (Phase 6)
- Real dry-run against production New Relic data
- One live run with real issue/PR creation

### Test Commands
```bash
uv run pytest tests/ -v
uv run ruff check nightwatch/ tests/
uv run ruff format --check nightwatch/ tests/
python -m nightwatch run --dry-run --verbose
```

### Coverage Target: >=80% for all modules

---

## Rollback Plan

### Per-Phase Rollback
Each phase on its own branch. Revert merge commit if problems arise.

### Full Rollback
1. `launchctl unload ~/Library/LaunchAgents/com.nightwatch.daily.plist`
2. TheFixer continues independently -- no changes made to it
3. Remove NightWatch repo entirely

### Feature-Level Rollback
- **All outputs**: `NIGHTWATCH_DRY_RUN=true`
- **Slack**: Remove `SLACK_WEBHOOK_URL`
- **Extended thinking**: Use model without thinking support
- **Scope**: `NIGHTWATCH_MAX_ERRORS=1`

### Rollback Triggers
- >30% nonsensical analyses
- API costs >$5/day average
- GitHub rate limiting
- False positive PRs confusing team

---

## Success Criteria / Acceptance Tests

### Functional
| Criteria | Target |
|----------|--------|
| End-to-end run completes | 100% exit 0 |
| Errors fetched from New Relic | >0 per production run |
| Ranking selects meaningful errors | >80% actionable |
| Structured analysis output | 100% valid Analysis |
| Issues created with labels | Every non-dry-run |
| PRs only for high-confidence | 100% accuracy |
| Slack summary per run | Every non-dry-run |
| Dry-run zero side effects | 100% |

### Quality
| Criteria | Target |
|----------|--------|
| Root cause accuracy | >60% over 10 runs |
| Fix quality | >40% mergeable |
| False positive rate | <20% |
| Duplicate issues | <10% |

### Performance
| Criteria | Target |
|----------|--------|
| Run duration (5 errors) | <5 minutes |
| API cost per run | <$0.25 |
| Tokens per error | <15,000 |

### Operational
| Criteria | Target |
|----------|--------|
| Unattended daily runs | 7 consecutive days |
| New Relic downtime handling | Clean exit |
| GitHub rate limit handling | Retries with backoff |
| Anthropic 429/529 handling | Exponential backoff |

---

## Risk Assessment

| Risk | Likelihood | Severity | Mitigation |
|------|-----------|----------|------------|
| NR returns too many errors | Medium | Low | Top N; --max-errors |
| Agentic loop stuck | Low | Medium | Hard cap max_iterations (15) |
| Structured output parsing fails | Low | Medium | Fallback regex; skip |
| GitHub rate limiting | Low | Medium | Backoff; rate limit headers |
| API costs exceed budget | Low | Medium | Token budget; cost tracking |
| Broken draft PRs | Medium | High | --dry-run first week; human review |
| Duplicate issues | Medium | Medium | GitHub search; NightWatch label |
| TheFixer/NightWatch conflict | Low | Low | Disable TheFixer overlap |
| Extended thinking cost | Low | Low | Monitor; disable if poor ROI |

---

*Sequential execution: Phase 1 foundation, Phases 2-4 capabilities, Phase 5 integration, Phase 6 operations.*
