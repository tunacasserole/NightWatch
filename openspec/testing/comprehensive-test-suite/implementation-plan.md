# TEST-001: Implementation Plan

**Status**: In Progress
**Date**: 2026-02-05

---

## Implementation Order

### Step 1: Shared Test Infrastructure
- `tests/conftest.py` — Shared pytest fixtures (mock_settings, mock clients, sample data factories)
- `tests/factories.py` — Builder functions for ErrorGroup, TraceData, Analysis, ErrorAnalysisResult, mock API responses
- `tests/fixtures/` — Static response data (Claude responses, NR GraphQL, GitHub REST)

### Step 2: Phase 1 — Critical Gap Tests (zero-coverage modules)
Order: config → newrelic → github → slack → correlation → cli → observability

1. `tests/unit/test_config.py` — Settings defaults, overrides, validation, caching
2. `tests/unit/test_newrelic.py` — NRQL, fetch_errors, fetch_traces, ranking, filtering
3. `tests/unit/test_github.py` — Issue CRUD, PR creation, code tools, caching
4. `tests/unit/test_slack.py` — Report blocks, user lookup, DM, follow-up
5. `tests/unit/test_correlation.py` — PR fetch, correlation scoring, formatting
6. `tests/unit/test_cli.py` — Arg parsing, command dispatch, exit codes
7. `tests/unit/test_observability.py` — Opik config, no-op when disabled

### Step 3: Phase 2 — Expand Existing Tests
- Expand `tests/test_analyzer.py` — Rate limits, malformed JSON, token budget, multi-pass edge cases
- New `tests/unit/test_prompts.py` — All enrichment paths, token budget estimation
- Expand `tests/test_health.py` — All report fields, status thresholds
- Expand `tests/test_quality.py` — Persistence, load, aggregation
- Expand `tests/test_models.py` — Computed properties, serialization edge cases

### Step 4: Phase 3 — Integration Tests
1. `tests/integration/test_pipeline.py` — Full runner.py with all steps mocked
2. `tests/integration/test_analysis_flow.py` — research → analyze → compound
3. `tests/integration/test_reporting_flow.py` — analysis → github + slack

### Step 5: Phase 4 — CI Configuration
- Add `pytest-cov` to dev dependencies
- Add coverage config to pyproject.toml
- Verify 85% coverage threshold

### Step 6: Run & Verify
- `uv run pytest --cov=nightwatch --cov-report=term-missing`
- Fix any failures
- Verify coverage meets threshold

---

## Key Design Decisions

1. **All external APIs mocked** — No real API calls in tests
2. **Factory pattern** — `make_error_group()`, `make_analysis()` etc. avoid brittle fixtures
3. **monkeypatch for env vars** — Tests never read real `.env`
4. **`get_settings.cache_clear()`** — Every test that touches config must clear the lru_cache
5. **`tmp_path` for file I/O** — Knowledge base, quality signals, agent configs use tmp dirs
6. **Tests organized by phase** — Can implement incrementally, each phase independently valuable
