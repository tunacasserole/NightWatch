# OpenSpec Proposal: Comprehensive Test Suite

**ID**: TEST-001
**Status**: Draft
**Author**: Claude (AI Assistant)
**Date**: 2026-02-05
**Scope**: All 19 NightWatch modules — unit, integration, and end-to-end test coverage
**Depends On**: None (tests existing code)
**See Also**: [RALPH-001](../../changes/ralph-pattern-adoption/proposal.md), [COMPOUND-002](../../changes/compound-engineering-implementation/proposal.md)

---

## 1. Executive Summary

NightWatch has 19 Python modules (5,059 lines) but only ~50-60% test coverage across 12 test files (2,681 lines). Six modules have **zero tests**, and several critical modules (github.py, newrelic.py, slack.py) have only minimal coverage.

This proposal adds comprehensive testing across all modules with a 4-phase approach: fill critical gaps first, then harden integration paths, add end-to-end pipeline tests, and finally establish CI quality gates.

**What we build:**
1. **13 new test files** covering all untested modules + deepening existing coverage
2. **Shared test fixtures** (conftest.py) with reusable mock clients, factory functions, and sample data
3. **Integration tests** for the full 12-step pipeline with mock external services
4. **CI-ready configuration** with coverage thresholds and quality gates

**Target**: >90% line coverage across all modules, with 100% coverage on critical paths (runner.py orchestration, analyzer.py agentic loop, all API clients).

**Estimated effort**: 3-5 days

---

## 2. Current State Assessment

### Coverage by Module

| Module | Lines | Existing Tests | Coverage Est. | Gap Severity |
|--------|-------|---------------|---------------|-------------|
| `runner.py` | 739 | **None** | 0% | **CRITICAL** — orchestrates everything |
| `slack.py` | 299 | **None** | 0% | **CRITICAL** — user-facing output |
| `correlation.py` | 160 | **None** | 0% | **HIGH** — PR correlation logic |
| `config.py` | 71 | **None** | 0% | **HIGH** — all settings validation |
| `observability.py` | 89 | **None** | 0% | MEDIUM — Opik tracing |
| `__main__.py` | 162 | **None** | 0% | MEDIUM — CLI entry point |
| `github.py` | 414 | Minimal (1 file) | ~15% | **HIGH** — issue/PR creation untested |
| `newrelic.py` | 286 | Minimal (1 file) | ~15% | **HIGH** — NRQL, filtering, traces untested |
| `prompts.py` | 212 | Partial | ~40% | MEDIUM — enrichment paths untested |
| `analyzer.py` | 677 | Good | ~65% | LOW — edge cases, error recovery |
| `health.py` | 178 | Basic | ~50% | MEDIUM — report generation gaps |
| `quality.py` | 95 | Basic | ~50% | MEDIUM — signal tracking gaps |
| `agents.py` | 132 | Good | ~70% | LOW |
| `models.py` | 251 | Good | ~75% | LOW |
| `patterns.py` | 600 | Excellent | ~85% | LOW |
| `validation.py` | 142 | Excellent | ~90% | LOW |
| `knowledge.py` | 346 | Excellent | ~85% | LOW |
| `research.py` | 203 | Good | ~75% | LOW |
| `test_run_context.py` | — | Good | ~80% | LOW |

### Existing Test Infrastructure

- **Framework**: pytest 8.0+
- **Mocking**: `unittest.mock` (MagicMock, patch)
- **No shared conftest.py** — each test file creates its own mocks independently
- **No fixtures** — duplicate mock setup across files
- **No coverage tracking** — no `pytest-cov` configured
- **No CI pipeline** — tests run manually only

### Key Testing Challenges

1. **External API mocking**: Claude (tool-use protocol), New Relic (GraphQL), GitHub (REST + PyGithub), Slack (Block Kit)
2. **Agentic loop**: Multi-iteration Claude conversations with tool calls and responses
3. **File I/O**: Knowledge base persistence, agent config loading, ignore.yml parsing
4. **Environment variables**: pydantic-settings loads from `.env` — tests must isolate from real config
5. **Rate limiting**: Anthropic retry/backoff logic in analyzer.py

---

## 3. Test Architecture

### 3.1 Directory Structure

```
tests/
├── conftest.py                    # NEW — shared fixtures, factories, mock clients
├── factories.py                   # NEW — factory functions for test data
│
├── unit/                          # NEW — unit tests organized by module
│   ├── test_config.py             # NEW — settings validation, env overrides
│   ├── test_newrelic.py           # NEW — NRQL queries, ranking, filtering, traces
│   ├── test_github.py             # REWRITE — comprehensive issue/PR/cache coverage
│   ├── test_slack.py              # NEW — report formatting, user lookup, Block Kit
│   ├── test_correlation.py        # NEW — PR correlation logic
│   ├── test_observability.py      # NEW — Opik configuration, tracing decorators
│   ├── test_cli.py                # NEW — CLI arg parsing, command dispatch
│   ├── test_prompts.py            # EXPAND — enrichment paths, token budgets
│   ├── test_health.py             # EXPAND — all report fields, edge cases
│   └── test_quality.py            # EXPAND — signal persistence, thresholds
│
├── test_analyzer.py               # EXPAND — error recovery, rate limits, edge cases
├── test_models.py                 # EXPAND — serialization, edge cases
├── test_patterns.py               # KEEP — already excellent
├── test_validation.py             # KEEP — already excellent
├── test_knowledge.py              # KEEP — already excellent
├── test_research.py               # KEEP — already excellent
├── test_run_context.py            # KEEP — already good
├── test_agents.py                 # KEEP — already good
├── test_ranking.py                # KEEP — already adequate
│
├── integration/                   # NEW — cross-module integration tests
│   ├── test_pipeline.py           # NEW — runner.py 12-step pipeline with mocks
│   ├── test_analysis_flow.py      # NEW — research → analyze → compound flow
│   └── test_reporting_flow.py     # NEW — analysis → slack + github issue flow
│
└── fixtures/                      # NEW — shared test data
    ├── sample_errors.py           # ErrorGroup factory data
    ├── sample_traces.py           # TraceData factory data
    ├── sample_analyses.py         # Analysis/ErrorAnalysisResult factory data
    ├── claude_responses.py        # Mock Claude API responses (tool_use, end_turn)
    ├── newrelic_responses.py      # Mock New Relic GraphQL responses
    └── agents/                    # Test agent config files
        ├── valid-agent.md
        ├── minimal-agent.md
        └── invalid-agent.md
```

### 3.2 Shared Fixtures (conftest.py)

```python
# tests/conftest.py — shared fixtures for all test files

@pytest.fixture
def mock_settings(monkeypatch):
    """Isolated settings that don't read from real .env."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
    monkeypatch.setenv("NEW_RELIC_API_KEY", "NRAK-TEST")
    monkeypatch.setenv("NEW_RELIC_ACCOUNT_ID", "12345")
    monkeypatch.setenv("NEW_RELIC_APP_NAME", "test-app")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_NOTIFY_USER", "test-user")
    monkeypatch.setenv("GITHUB_REPO", "test-org/test-repo")
    # Clear cached settings
    from nightwatch.config import get_settings
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()

@pytest.fixture
def mock_github_client():
    """Mock GitHubClient with common method stubs."""
    ...

@pytest.fixture
def mock_newrelic_client():
    """Mock NewRelicClient with sample NRQL responses."""
    ...

@pytest.fixture
def mock_anthropic_client():
    """Mock Anthropic client with configurable tool-use responses."""
    ...

@pytest.fixture
def mock_slack_client():
    """Mock SlackClient with DM channel setup."""
    ...

@pytest.fixture
def sample_error_group():
    """Factory for ErrorGroup test instances."""
    ...

@pytest.fixture
def sample_trace_data():
    """Factory for TraceData test instances."""
    ...

@pytest.fixture
def sample_analysis_result():
    """Factory for ErrorAnalysisResult test instances."""
    ...

@pytest.fixture
def tmp_knowledge_dir(tmp_path):
    """Temporary knowledge directory with proper structure."""
    ...
```

### 3.3 Factory Functions (factories.py)

```python
# tests/factories.py — reusable test data builders

def make_error_group(
    error_class="ActiveRecord::RecordNotFound",
    transaction="Controller/orders/show",
    occurrences=42,
    **overrides,
) -> ErrorGroup:
    """Build an ErrorGroup with sensible defaults."""
    ...

def make_trace_data(
    tx_error_count=5,
    stack_trace_count=3,
    **overrides,
) -> TraceData:
    """Build TraceData with sample transaction errors and stack traces."""
    ...

def make_analysis(
    confidence="high",
    has_fix=True,
    file_changes=None,
    **overrides,
) -> Analysis:
    """Build an Analysis with sensible defaults."""
    ...

def make_analysis_result(
    error=None,
    analysis=None,
    iterations=6,
    tokens_used=12000,
    **overrides,
) -> ErrorAnalysisResult:
    """Build a full ErrorAnalysisResult."""
    ...

def make_claude_response(
    stop_reason="end_turn",
    text="",
    tool_calls=None,
    input_tokens=1000,
    output_tokens=500,
) -> MagicMock:
    """Build a mock Anthropic Messages API response."""
    ...

def make_claude_tool_use_response(
    tool_name="search_code",
    tool_input=None,
) -> MagicMock:
    """Build a mock response with a tool_use stop reason."""
    ...
```

---

## 4. Phase 1: Critical Gap Coverage (Priority: CRITICAL)

Fill zero-coverage modules that represent the highest risk.

**Estimated effort**: 1.5-2 days

### 4.1 test_config.py — Settings Validation

**What to test:**
- Default values load correctly when no env vars set (except required ones)
- Each optional setting override works (NIGHTWATCH_MAX_ERRORS, etc.)
- Required settings raise ValidationError when missing
- Boolean settings parse from string env vars ("true", "false", "1", "0")
- Integer settings reject invalid values
- `get_settings()` caching works (returns same instance)
- `get_settings.cache_clear()` returns fresh instance
- `.env` file loading vs environment variable precedence

**Test count**: ~15 tests

### 4.2 test_newrelic.py — New Relic Client (Rewrite)

**What to test:**

*NRQL Queries:*
- `query_nrql()` sends correct GraphQL payload
- `query_nrql()` handles empty results
- `query_nrql()` handles API errors (401, 500, timeout)
- `query_nrql()` parses nested result structure correctly

*Error Fetching:*
- `fetch_errors()` builds correct NRQL with since parameter
- `fetch_errors()` groups by error_class + transactionName
- `fetch_errors()` handles zero errors gracefully
- `fetch_errors()` maps NRQL columns to ErrorGroup fields

*Trace Fetching:*
- `fetch_traces()` fetches both TransactionError and ErrorTrace events
- `fetch_traces()` combines results into TraceData
- `fetch_traces()` handles missing stack traces
- `fetch_traces()` respects trace limit

*Error Ranking:*
- `rank_errors()` applies weighted scoring (frequency 40%, severity 30%, recency 20%, impact 10%)
- `rank_errors()` returns sorted by score descending
- `rank_errors()` handles ties deterministically
- `rank_errors()` handles single-error input

*Ignore Filtering:*
- `load_ignore_patterns()` parses valid ignore.yml
- `load_ignore_patterns()` returns empty list for missing file
- `filter_errors()` removes matching errors by "contains" pattern
- `filter_errors()` removes matching errors by "exact" pattern
- `filter_errors()` preserves non-matching errors
- `filter_errors()` handles empty pattern list

*Client Lifecycle:*
- `NewRelicClient()` initializes with settings
- `close()` cleans up httpx client

**Test count**: ~25 tests

### 4.3 test_github.py — GitHub Client (Rewrite)

**What to test:**

*Issue Search:*
- `find_existing_issue()` finds exact match (error_class + transaction)
- `find_existing_issue()` falls back to error_class-only match
- `find_existing_issue()` returns None when no match
- `find_existing_issue()` handles GitHub API errors

*Issue Creation:*
- `create_issue()` builds correct title, body, and labels
- `create_issue()` applies `nightwatch` label
- `create_issue()` adds confidence label (confidence:high, etc.)
- `create_issue()` adds `has-fix` or `needs-investigation` label
- `create_issue()` includes correlated PR section when provided
- `create_issue()` returns CreatedIssueResult

*Occurrence Comments:*
- `add_occurrence_comment()` adds formatted comment to existing issue
- `add_occurrence_comment()` increments occurrence count
- `add_occurrence_comment()` returns CreatedIssueResult with action="updated"

*WIP Limits:*
- `get_open_nightwatch_issue_count()` counts open issues with nightwatch label
- WIP limit logic in runner blocks issue creation at limit

*PR Creation:*
- `create_pull_request()` creates branch, commits files, opens draft PR
- `create_pull_request()` links to issue number in PR body
- `create_pull_request()` handles file_changes with modify and create actions
- `create_pull_request()` returns CreatedPRResult

*Code Tools (used by Claude):*
- `read_file()` returns file content from repo
- `read_file()` returns None for missing files
- `search_code()` returns formatted search results
- `list_directory()` returns directory listing
- `CodeCache` caches file reads within a session

**Test count**: ~30 tests

### 4.4 test_slack.py — Slack Client

**What to test:**

*User Lookup:*
- `_get_user_id()` finds user by display name
- `_get_user_id()` returns None for unknown user
- `_get_user_id()` handles paginated user list
- `_get_user_id()` handles API errors

*DM Sending:*
- `_open_dm_channel()` opens conversation with user ID
- `send_report()` sends Block Kit message to correct user
- `send_report()` handles send failures gracefully

*Report Formatting:*
- `_build_report_blocks()` includes header with run stats
- `_build_report_blocks()` formats each analysis with confidence, status, error class
- `_build_report_blocks()` includes pattern section when patterns exist
- `_build_report_blocks()` includes ignore suggestions when present
- `_build_report_blocks()` respects Slack block limits (50 blocks max)
- `_build_report_blocks()` includes multi-pass retry count when present
- Block Kit output is valid (no None text fields, proper structure)

*Follow-up:*
- `send_followup()` sends issue/PR links
- `send_followup()` handles empty issues list
- `send_followup()` includes PR link when present

**Test count**: ~20 tests

### 4.5 test_correlation.py — PR Correlation

**What to test:**

*PR Fetching:*
- `fetch_recent_merged_prs()` fetches PRs merged within time window
- `fetch_recent_merged_prs()` respects PR limit (default 10)
- `fetch_recent_merged_prs()` handles empty results
- `fetch_recent_merged_prs()` extracts changed files from PR

*Correlation Logic:*
- `correlate_error_with_prs()` matches by file path overlap
- `correlate_error_with_prs()` matches by module name from transaction
- `correlate_error_with_prs()` scores overlap correctly
- `correlate_error_with_prs()` returns empty list for no correlation
- `correlate_error_with_prs()` handles errors with no transaction info

*Formatting:*
- `format_correlated_prs()` produces markdown section
- `format_correlated_prs()` limits to top 3 PRs
- `format_correlated_prs()` returns empty string for no correlations

**Test count**: ~15 tests

### 4.6 test_cli.py — CLI Entry Point

**What to test:**

*Argument Parsing:*
- `run` command with defaults
- `run` command with all flags (--since, --max-errors, --max-issues, --dry-run, --verbose, --model, --agent)
- `check` command
- No subcommand defaults to `run`
- Invalid subcommand shows help

*Logging Setup:*
- `--verbose` sets DEBUG level
- Default sets INFO level

*Error Handling:*
- Keyboard interrupt returns exit code 130
- Fatal error returns exit code 1
- Successful run returns exit code 0

**Test count**: ~12 tests

### 4.7 test_observability.py — Opik Integration

**What to test:**
- `configure_opik()` initializes when API key + workspace set
- `configure_opik()` is no-op when API key missing
- `configure_opik()` is no-op when `opik_enabled=False`
- `configure_opik()` handles import error gracefully (opik not installed)
- Tracing decorator applies correctly to analysis functions

**Test count**: ~8 tests

---

## 5. Phase 2: Deepen Existing Coverage (Priority: HIGH)

Expand tests for modules with partial coverage, focusing on edge cases and error paths.

**Estimated effort**: 1-1.5 days

### 5.1 test_analyzer.py — Expand

**Add tests for:**
- Rate limit handling (429 response → backoff → retry)
- Claude returns malformed JSON → fallback parsing
- Claude returns tool_use but tool execution fails → error recovery
- Max iterations reached → forced completion
- Token budget exceeded → early termination
- Multi-pass: pass 1 LOW → pass 2 improves to HIGH
- Multi-pass: pass 1 LOW → pass 2 still LOW → accept best
- Multi-pass disabled via config → single pass only
- Run context injection into prompt
- Research context injection into prompt
- Agent config loading and application
- `_build_retry_seed()` output format
- `_select_best_pass()` selection logic
- Conversation compression trigger and behavior

**Additional test count**: ~18 tests

### 5.2 test_prompts.py — Expand

**Add tests for:**
- `build_analysis_prompt()` with prior_analyses injection
- `build_analysis_prompt()` with research_context (file previews, correlated PRs)
- `build_analysis_prompt()` with seed_knowledge (multi-pass)
- `build_analysis_prompt()` with run_context
- `build_analysis_prompt()` with all enrichments combined
- Token estimation stays within budget
- SYSTEM_PROMPT constant is non-empty and contains required sections
- Tool definitions (TOOLS) match expected schema

**Additional test count**: ~12 tests

### 5.3 test_health.py — Expand

**Add tests for:**
- `check_configuration()` reports missing optional settings
- `record_analysis()` tracks success/failure counts
- `record_analysis()` accumulates token usage
- `generate()` produces all expected report fields
- `generate()` calculates success rate correctly
- `generate()` estimates cost based on token usage
- Health status thresholds: healthy / degraded / unhealthy
- Edge case: zero analyses recorded

**Additional test count**: ~10 tests

### 5.4 test_quality.py — Expand

**Add tests for:**
- `record_signal()` stores all fields
- `save()` persists to disk correctly
- `save()` handles write errors gracefully
- Load from existing quality data file
- Signal aggregation across multiple recordings
- Confidence float conversion edge cases

**Additional test count**: ~8 tests

### 5.5 test_models.py — Expand

**Add tests for:**
- `RunReport` computed properties (fixes_found, high_confidence, retry_rate)
- `RunContext.to_prompt_section()` with empty, partial, and full data
- `RunContext.to_prompt_section()` respects max_chars limit
- `RunContext.record_analysis()` accumulates correctly
- `ErrorAnalysisResult` with multi-pass data
- `Analysis` with and without file_changes
- `FileChange` validation (path, action, content)
- `PriorAnalysis` match_score edge cases
- All dataclass default values

**Additional test count**: ~12 tests

---

## 6. Phase 3: Integration Tests (Priority: HIGH)

Test cross-module interactions with all external services mocked.

**Estimated effort**: 1-1.5 days

### 6.1 test_pipeline.py — Full Runner Pipeline

**What to test:**

*Happy Path:*
- Full 12-step pipeline with 2 mock errors → analyses → issues → Slack report
- Dry run mode skips steps 6-11, prints summary
- Pipeline with zero errors found → early return

*Error Handling:*
- Single analysis failure → fail forward, continue with remaining errors
- Slack report failure → continue to issue creation
- GitHub issue creation failure → continue to next issue
- PR validation failure → skip PR, continue pipeline
- PR validation failure → correction attempt → success
- PR validation failure → correction attempt → still fails → skip PR

*Feature Flags:*
- `nightwatch_compound_enabled=False` → skip knowledge steps
- `nightwatch_multi_pass_enabled=False` → single pass only
- `nightwatch_quality_gate_enabled=False` → skip PR validation
- `nightwatch_quality_gate_correction=False` → skip correction attempt

*WIP Limits:*
- At WIP limit → skip all issue creation
- Partial WIP slots → create only N issues

*Resource Tracking:*
- Total tokens accumulated correctly across analyses
- Total API calls accumulated correctly
- Run duration tracked
- Multi-pass retries counted
- Health report generated with correct stats
- Quality signals saved

**Test count**: ~20 tests

### 6.2 test_analysis_flow.py — Research → Analyze → Compound

**What to test:**
- Research gathers prior knowledge + infers files → injected into analysis prompt
- Analysis produces result → compounded to knowledge base → index rebuilt
- Prior knowledge from previous run influences current analysis prompt
- Research context reduces Claude iterations (mock fewer tool calls needed)
- Run context accumulates across multiple error analyses

**Test count**: ~8 tests

### 6.3 test_reporting_flow.py — Analysis → Slack + GitHub

**What to test:**
- High-confidence fix → issue created with `has-fix` label → draft PR created → Slack follow-up with links
- Medium-confidence no fix → issue with `needs-investigation` → no PR → Slack follow-up with issue only
- Existing issue found → occurrence comment added instead of new issue
- Pattern detection results included in Slack report
- Ignore suggestions included in Slack report

**Test count**: ~8 tests

---

## 7. Phase 4: CI & Quality Gates (Priority: MEDIUM)

Establish coverage tracking, CI configuration, and quality thresholds.

**Estimated effort**: 0.5-1 day

### 7.1 Coverage Configuration

```toml
# pyproject.toml additions

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
markers = [
    "unit: Unit tests (fast, no I/O)",
    "integration: Integration tests (slower, may use tmp files)",
    "slow: Slow tests (>5s)",
]

[tool.coverage.run]
source = ["nightwatch"]
omit = [
    "nightwatch/__main__.py",  # CLI entry — tested via subprocess
    "nightwatch/observability.py",  # Optional dependency
]

[tool.coverage.report]
fail_under = 85
show_missing = true
exclude_lines = [
    "pragma: no cover",
    "if __name__ == .__main__.",
    "if TYPE_CHECKING:",
]
```

### 7.2 Dev Dependencies

```toml
# Add to pyproject.toml [project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=4.0",
    "ruff>=0.4",
]
```

### 7.3 Test Commands

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=nightwatch --cov-report=term-missing

# Run only unit tests (fast)
uv run pytest tests/unit/ tests/test_*.py -m "not integration"

# Run integration tests
uv run pytest tests/integration/

# Run specific module tests
uv run pytest tests/unit/test_slack.py -v
```

### 7.4 Quality Gate Thresholds

| Metric | Threshold | Enforcement |
|--------|-----------|-------------|
| Line coverage | ≥85% | `--cov-fail-under=85` |
| Branch coverage | ≥75% | Advisory (logged, not blocking) |
| All tests pass | 100% | pytest exit code |
| Ruff lint clean | 0 errors | `ruff check` exit code |
| No skipped tests | Advisory | Logged in CI output |

---

## 8. New Test Files Summary

| File | Phase | Tests (est.) | Module(s) Covered |
|------|-------|-------------|-------------------|
| `tests/conftest.py` | 1 | — (fixtures) | All |
| `tests/factories.py` | 1 | — (helpers) | All |
| `tests/unit/test_config.py` | 1 | 15 | config.py |
| `tests/unit/test_newrelic.py` | 1 | 25 | newrelic.py |
| `tests/unit/test_github.py` | 1 | 30 | github.py |
| `tests/unit/test_slack.py` | 1 | 20 | slack.py |
| `tests/unit/test_correlation.py` | 1 | 15 | correlation.py |
| `tests/unit/test_cli.py` | 1 | 12 | __main__.py |
| `tests/unit/test_observability.py` | 1 | 8 | observability.py |
| `tests/unit/test_prompts.py` | 2 | 12 | prompts.py |
| `tests/unit/test_health.py` | 2 | 10 | health.py |
| `tests/unit/test_quality.py` | 2 | 8 | quality.py |
| `tests/integration/test_pipeline.py` | 3 | 20 | runner.py + all |
| `tests/integration/test_analysis_flow.py` | 3 | 8 | research → analyzer → knowledge |
| `tests/integration/test_reporting_flow.py` | 3 | 8 | analyzer → github → slack |
| `tests/fixtures/*.py` | 1 | — (data) | All |
| **Total new** | | **~191 tests** | |
| **Expanded existing** | 2 | **~60 tests** | analyzer, models, prompts, health, quality |
| **Grand total** | | **~251 new tests** | |

Combined with ~120 existing tests = **~370 total tests**.

---

## 9. Migration Plan for Existing Tests

Existing test files remain in place and functional. The proposal **does not break** any current tests.

**Changes to existing test files:**
1. `test_github.py` — Replace with comprehensive `tests/unit/test_github.py` (old file deprecated)
2. `test_ranking.py` — Absorbed into `tests/unit/test_newrelic.py` (ranking is part of newrelic module)
3. All other existing test files — Keep as-is, they already work

**Migration approach:**
- Phase 1 creates `tests/unit/` and `tests/integration/` directories
- Existing root-level test files continue working (pytest discovers them)
- New tests import from `tests/conftest.py` for shared fixtures
- After Phase 4, optionally relocate existing tests into `tests/unit/` for consistency

---

## 10. Mock Strategy

### External Services

| Service | Mock Approach | Key Considerations |
|---------|-------------|-------------------|
| **Anthropic API** | `unittest.mock.patch("anthropic.Anthropic")` | Must simulate tool_use/end_turn stop reasons, multi-turn conversations, rate limit 429s |
| **GitHub API** | `unittest.mock.patch("github.Github")` via PyGithub | Mock repo, issues, pulls, contents objects. Use `MagicMock(spec=...)` for type safety |
| **New Relic API** | `unittest.mock.patch("httpx.Client.post")` | Mock GraphQL responses for NRQL queries, trace fetches |
| **Slack API** | `unittest.mock.patch("slack_sdk.WebClient")` | Mock users_list, conversations_open, chat_postMessage |
| **File System** | `tmp_path` fixture + `monkeypatch` | Knowledge dir, quality signals, agent configs |

### Mock Response Libraries

Pre-built response fixtures in `tests/fixtures/` for:
- Claude: `end_turn` with JSON analysis, `tool_use` with each tool type, malformed responses, rate limit errors
- New Relic: NRQL results with various error groups, trace data with/without stack traces
- GitHub: Issue search results, created issues, PR objects, file content, directory listings
- Slack: User list responses, conversation open responses, message send responses

---

## 11. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Mock drift from real APIs | Medium | Medium | Pin mock response shapes to actual API response samples; update when APIs change |
| Tests too coupled to implementation | Medium | Medium | Test behavior (outputs) not implementation (internal calls); use factories not fixtures |
| Shared conftest.py becomes bloated | Low | Low | Keep conftest.py to fixture wiring only; complex setup in factories.py |
| Integration tests become slow | Medium | Low | Mark with `@pytest.mark.integration`; skip in quick runs |
| Coverage target too aggressive | Low | Low | Start at 85%, increase to 90% after Phase 2 |
| Existing tests break during reorg | Low | Medium | Don't move existing files until Phase 4; new tests are additive |

---

## 12. Success Criteria

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Line coverage | ≥85% (Phase 2), ≥90% (Phase 4) | `pytest --cov` |
| Zero-coverage modules | 0 (from current 6) | Coverage report by module |
| Critical path coverage | 100% for runner.py happy path | Manual review |
| All API clients tested | github.py, newrelic.py, slack.py ≥80% | Coverage report |
| Test run time | <30s for unit tests, <60s total | `pytest --durations=10` |
| No test pollution | Tests pass in any order | `pytest --randomly` (optional) |
| CI-ready | All tests pass, coverage threshold met | Single `pytest --cov` command |

---

## 13. Implementation Order

```
Phase 1: Critical Gaps (1.5-2 days)
  ├── conftest.py + factories.py (shared infrastructure)
  ├── test_config.py
  ├── test_newrelic.py (rewrite)
  ├── test_github.py (rewrite)
  ├── test_slack.py
  ├── test_correlation.py
  ├── test_cli.py
  └── test_observability.py

Phase 2: Deepen Coverage (1-1.5 days)
  ├── Expand test_analyzer.py
  ├── Expand test_prompts.py → tests/unit/test_prompts.py
  ├── Expand test_health.py → tests/unit/test_health.py
  ├── Expand test_quality.py → tests/unit/test_quality.py
  └── Expand test_models.py

Phase 3: Integration Tests (1-1.5 days)
  ├── test_pipeline.py
  ├── test_analysis_flow.py
  └── test_reporting_flow.py

Phase 4: CI & Quality Gates (0.5-1 day)
  ├── pyproject.toml coverage config
  ├── pytest-cov dependency
  ├── Coverage threshold enforcement
  └── Optional: relocate existing tests into unit/
```

**Total: 3-5 days** (with parallelization of Phases 1-2: 2.5-4 days)

---

## 14. What We Deliberately Don't Build

| Item | Why Not |
|------|---------|
| **E2E tests hitting real APIs** | Too slow, flaky, costly. Mock everything external. |
| **Load/performance testing** | NightWatch runs once daily on 5 errors. Not a performance-critical system. |
| **Property-based testing (Hypothesis)** | Overkill for this codebase size. Standard example-based tests suffice. |
| **Snapshot testing** | Slack Block Kit output changes frequently. Assert structure, not exact strings. |
| **Browser/UI testing** | NightWatch is CLI-only. No UI to test. |
| **Contract testing (Pact)** | Would require API provider cooperation. Mock-based testing is sufficient. |

---

## 15. Decision Log

- [ ] **Approve Phase 1**: Critical gap coverage (~125 new tests)
- [ ] **Approve Phase 2**: Deepen existing coverage (~60 expanded tests)
- [ ] **Approve Phase 3**: Integration tests (~36 new tests)
- [ ] **Approve Phase 4**: CI configuration and quality gates

---

## 16. References

- [RALPH-001: Multi-Pass Analysis](../../changes/ralph-pattern-adoption/proposal.md) — Tests for multi-pass, quality gate, run context
- [COMPOUND-002: Compound Engineering](../../changes/compound-engineering-implementation/proposal.md) — Tests for knowledge, research, agents, patterns
- [pytest documentation](https://docs.pytest.org/)
- [unittest.mock documentation](https://docs.python.org/3/library/unittest.mock.html)
