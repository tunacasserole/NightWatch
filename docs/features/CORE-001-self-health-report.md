# CORE-001: Self-Health Report Generation

**Status**: Not Started
**Priority**: High
**Effort**: 2-3 hours
**Depends On**: None (standalone value)

---

## Overview

**Goal**: NightWatch generates a structured markdown report about its own operational health after every run — metrics, failures, resource usage, and quality signals.

**Value**: Enables operational visibility, debugging, cost tracking, and (optionally) autonomous self-improvement via compound-product integration.

**RICE Score**: Reach (daily) × Impact (high — enables compound loop + debugging) × Confidence (95%) / Effort (3h) = **High**

---

## Scope

### In Scope
- `HealthCollector` class that captures events during a run
- `RunHealthReport` dataclass aggregating run metrics
- Markdown report renderer with structured sections
- Integration into `runner.py` pipeline (additive, non-breaking)
- CLI flags: `--self-report`, `--report-dir`
- Config settings for report directory and retention
- Automatic cleanup of reports older than 30 days
- Tests for all new code

### Out of Scope
- Quality signal feedback loop (separate feature: CORE-002)
- compound-product integration (separate feature: COMPOUND-001)
- Slack notification of self-report contents
- Dashboard or web UI for reports
- Report diffing between runs

---

## Technical Details

### New File: `nightwatch/health.py`

| Component | Purpose |
|-----------|---------|
| `HealthCollector` | Accumulates `HealthEvent` objects during pipeline execution |
| `build_health_report()` | Converts `RunReport` + events into `RunHealthReport` |
| `write_report_markdown()` | Renders report to `reports/YYYY-MM-DD_HH-MM_self-report.md` |
| `cleanup_old_reports()` | Deletes reports older than retention period |

### Modified Files

| File | Changes |
|------|---------|
| `nightwatch/models.py` | Add `HealthEvent` and `RunHealthReport` dataclasses |
| `nightwatch/runner.py` | Create `HealthCollector` at start, instrument exception handlers, call `write_report_markdown()` after pipeline |
| `nightwatch/__main__.py` | Add `--self-report` and `--report-dir` arguments |
| `nightwatch/config.py` | Add `nightwatch_report_dir`, `nightwatch_report_retention_days`, `nightwatch_self_report` |
| `.gitignore` | Add `reports/` |

### New Test File: `tests/test_health.py`

- `test_health_collector_records_events`
- `test_health_collector_severity_levels`
- `test_build_health_report_from_run_report`
- `test_build_health_report_empty_run`
- `test_render_markdown_has_required_sections`
- `test_render_markdown_failures_present`
- `test_render_markdown_clean_run`
- `test_estimated_cost_calculation`
- `test_max_iterations_hit_count`
- `test_cleanup_old_reports`

### Report Format (Example Output)

```markdown
# NightWatch Daily Self-Report — 2026-02-05

## Run Metrics
- **Duration**: 522s
- **Lookback**: 24h
- Errors found: 47
- Errors filtered (ignored): 5
- Errors analyzed: 5
- Fixes found: 3
- High confidence fixes: 2
- Issues created: 2
- Issues updated: 1
- Draft PRs created: 1

## Resource Usage
- Total tokens: 284,000
- Estimated cost: $4.26
- API calls: 42
- Avg iterations/error: 8.4
- Avg tokens/error: 56,800
- Errors hitting max iterations: 1

## Failures
- **analyzer**: Analysis failed for Net::ReadTimeout — hit max iterations
  - error_class: Net::ReadTimeout
  - iterations: 15
- **github**: Rate limited on search_code
  - retries: 3
  - succeeded: 1

## Analysis Details
1. [HIGH] [FIX] **TypeError** in `ProductsController#show` (23 occ, 6 iter, 48,000 tok)
2. [MEDIUM] [FIX] **NoMethodError** in `CheckoutController#create` (12 occ, 9 iter, 62,000 tok)
3. [HIGH] [FIX] **ArgumentError** in `ReportsJob#perform` (8 occ, 4 iter, 31,000 tok)
4. [LOW] [INVESTIGATE] **Net::ReadTimeout** in `ExternalAPI#fetch` (89 occ, 15 iter, 95,000 tok)
5. [MEDIUM] [FIX] **ActiveRecord::RecordNotFound** in `UsersController#update` (5 occ, 8 iter, 48,000 tok)

## Quality Signals
No quality signals available yet (first run or no past data).
```

### Key Design Decisions

1. **Fail-safe**: Entire self-report generation is wrapped in `try/except` — a failure here never crashes the main pipeline
2. **Additive only**: No existing behavior changes. All new code is called *after* the pipeline completes.
3. **Markdown format**: Human-readable and compound-product compatible. No YAML frontmatter needed (compound-product's `analyze-report.sh` reads plain markdown).
4. **Cost estimation**: Blended rate approximation. Good enough for trend tracking, not for billing.
5. **Gitignored**: Reports contain operational data (token counts, error details) that shouldn't be committed.

---

## Implementation Plan

1. Add `HealthEvent` and `RunHealthReport` to `models.py`
2. Create `nightwatch/health.py` with collector + renderer
3. Add config settings to `config.py`
4. Add CLI flags to `__main__.py`
5. Instrument `runner.py` exception handlers with collector calls
6. Add post-pipeline report generation call
7. Add `reports/` to `.gitignore`
8. Write tests in `tests/test_health.py`
9. Run `uv run ruff check` + `uv run pytest` — all green
10. Manual test: `uv run python -m nightwatch run --dry-run --self-report`

---

## Success Criteria

- [ ] Self-report markdown file generated after every non-dry-run
- [ ] Report contains all 5 sections (Metrics, Resources, Failures, Details, Quality)
- [ ] Failures captured from every instrumented exception handler
- [ ] Cost estimation within 50% of actual (verified against Anthropic dashboard)
- [ ] Old reports cleaned up (>30 days)
- [ ] All tests pass, ruff clean
- [ ] Pipeline behavior unchanged when self-report is disabled
- [ ] Pipeline completes even if self-report generation fails
