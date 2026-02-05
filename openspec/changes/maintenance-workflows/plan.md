# Implementation Plan: NightWatch Maintenance Workflows

**ID**: MAINT-001-PLAN
**Parent**: [MAINT-001 Proposal](./proposal.md) | [MAINT-001-IMPL Spec](./implementation.md)
**Date**: 2026-02-05
**Status**: Approved

---

## Execution Overview

4 phases, 18 tasks, each independently deployable. Each phase ends with a green test suite and a working `python -m nightwatch run` command that behaves identically to current behavior (plus new opt-in capabilities).

**Total estimated effort**: ~22 hours across 4 phases.

---

## Phase 1: Architecture Refactoring

**Goal**: Extract the monolithic `runner.py` pipeline into a pluggable workflow architecture. Zero behavior change — the existing command produces identical output.

**Branch**: `feat/workflow-architecture`

### Step 1.1 — Create the workflow package skeleton
- Create `nightwatch/workflows/__init__.py` (empty docstring)
- Create `nightwatch/workflows/base.py` with:
  - `SafeOutput` StrEnum (6 allowed actions)
  - `WorkflowItem`, `WorkflowAnalysis`, `WorkflowAction`, `WorkflowResult` dataclasses
  - `Workflow` ABC with 5 abstract methods: `fetch`, `filter`, `analyze`, `act`, `report_section`
  - `check_safe_output()` enforcement method
- Create `nightwatch/workflows/registry.py` with:
  - `_REGISTRY` dict
  - `@register` decorator
  - `get_enabled_workflows(config)` with backward-compat (no config = errors only)
  - `list_registered()` helper

**Verification**: Import from Python REPL — `from nightwatch.workflows.base import Workflow` succeeds.

### Step 1.2 — Move error pipeline into workflow
- Create `nightwatch/workflows/errors.py`:
  - `ErrorAnalysisWorkflow(Workflow)` class with `@register` decorator
  - Move pipeline logic from `runner.py` steps 2-11 into the 5-stage lifecycle
  - Internal state: `_error_analyses`, `_issues_created`, `_pr_created`
  - `fetch()` → NewRelicClient + filter + rank → `list[WorkflowItem]`
  - `filter()` → top N by severity
  - `analyze()` → Claude agentic loop per item (calls `analyze_error()`)
  - `act()` → issue creation + PR creation (calls `select_for_issues`, `_best_fix_candidate`)
  - `report_section()` → Slack Block Kit blocks via existing `_build_report_blocks`
  - `cleanup()` → close NewRelicClient

**Verification**: Unit test confirming `ErrorAnalysisWorkflow` can be instantiated and registered.

### Step 1.3 — Refactor runner.py to orchestrator
- Rewrite `runner.py`:
  - Keep `run()` function signature identical (same args, same return type)
  - Build `workflows_config` dict from args (backward compat)
  - Import workflow modules to trigger `@register` decorators
  - Loop: `fetch → filter → analyze → act` per workflow
  - Wrap each workflow in try/except (independent failure)
  - Build `WorkflowResult` per workflow
  - Preserve `select_for_issues()` and `_best_fix_candidate()` as module-level functions (imported by errors.py)
  - `_build_run_report()` extracts `ErrorAnalysisResult` from workflow results for backward compat
  - `_send_slack_report()` calls existing SlackClient
  - `_print_dry_run_summary()` extended for multi-workflow output

**Verification**: `python -m nightwatch run --dry-run` produces identical output to pre-refactor.

### Step 1.4 — Add CLI and config support
- Add `--workflows` flag to `__main__.py` run_parser
- Add `nightwatch_workflows` and `nightwatch_config_path` to `config.py` Settings
- Create `nightwatch.yml.example` with full reference config

**Verification**: `python -m nightwatch run --workflows errors` works. No `--workflows` flag = errors only (backward compat).

### Step 1.5 — Write Phase 1 tests
- `tests/test_workflows_base.py` — dataclass construction, SafeOutput enforcement, check_safe_output blocks unauthorized actions
- `tests/test_workflows_registry.py` — @register decorator, get_enabled_workflows, backward compat default
- `tests/test_workflows_errors.py` — ErrorAnalysisWorkflow stages produce correct types

**Verification**: `pytest tests/` — all existing + new tests green. `ruff check && ruff format --check` clean.

### Step 1.6 — Final validation
- Run full existing test suite against refactored code
- `ruff check nightwatch/` and `ruff format --check nightwatch/`
- Manual `--dry-run` comparison against pre-refactor output
- Commit on `feat/workflow-architecture`, PR to main

**Done when**: All existing tests pass unchanged. `select_for_issues()` and `_best_fix_candidate()` importable from `runner.py`. `python -m nightwatch run` produces identical behavior.

---

## Phase 2: CI Doctor Workflow

**Goal**: Diagnose GitHub Actions failures with Claude and post root-cause analysis comments on PRs/commits.

**Branch**: `feat/ci-doctor`
**Depends on**: Phase 1 merged

### Step 2.1 — Create CI Doctor workflow
- Create `nightwatch/workflows/ci_doctor.py`:
  - `CI_DOCTOR_SYSTEM_PROMPT` — inline prompt for CI failure diagnosis
  - `KNOWN_PATTERNS` dict — network timeout, rate limit, disk full (skip Claude)
  - `CIDoctorWorkflow(Workflow)` with `@register` decorator
  - `safe_outputs = [ADD_COMMENT, ADD_LABEL, SEND_SLACK]`
  - `fetch()` → `repo.get_workflow_runs(status="failure")` → `list[WorkflowItem]`
  - `filter()` → sort by severity (main branch first), take top N
  - `analyze()`:
    - `_fetch_run_logs()` → download zip, extract log text from failed jobs
    - `_check_known_patterns()` → instant diagnosis for obvious failures
    - Claude analysis for non-obvious failures → parse JSON diagnosis
  - `act()` → post diagnosis comment on PR (via `pr.create_issue_comment`) or commit (via `commit.create_comment`)
  - `report_section()` → Slack Block Kit blocks with category + confidence
  - `_build_diagnosis_comment()` → formatted markdown table with root cause, suggested fix, confidence

**Verification**: Instantiate workflow, mock GitHub API, verify log fetching and comment formatting.

### Step 2.2 — Register and wire up
- Add `import nightwatch.workflows.ci_doctor` to `runner.py` imports
- Verify `python -m nightwatch run --workflows errors,ci_doctor` runs both
- Verify `--dry-run` prints CI Doctor results without posting comments

**Verification**: Both workflows execute in sequence. Errors workflow unaffected.

### Step 2.3 — Write Phase 2 tests
- `tests/test_ci_doctor.py`:
  - Known pattern matching returns instant diagnosis
  - Log parsing extracts failure sections correctly
  - Diagnosis comment markdown formatting
  - Safe output enforcement (CI Doctor cannot create_issue or create_pr)
  - JSON parsing fallback for malformed Claude responses

**Verification**: `pytest tests/test_ci_doctor.py` green. Full suite still passes.

### Step 2.4 — Integration test with real GitHub repo
- Run `--dry-run` against the actual NightWatch repo (which may have CI runs)
- Verify fetched workflow runs are real and log extraction works
- If no failures available, verify graceful "0 failed runs found" behavior

**Done when**: CI Doctor fetches failed runs, diagnoses them (or returns known-pattern results), formats comments correctly. `--dry-run` shows results. Live posting tested on a test PR.

---

## Phase 3: Cross-Error Pattern Analysis

**Goal**: Detect systemic patterns across NightWatch's accumulated error history.

**Branch**: `feat/pattern-analysis`
**Depends on**: Phase 1 merged (Phase 2 not required)

### Step 3.1 — Implement run history persistence
- Create `nightwatch/history.py`:
  - `HISTORY_DIR = Path.home() / ".nightwatch"`
  - `HISTORY_FILE = HISTORY_DIR / "run_history.jsonl"`
  - `save_run(report: RunReport)` — append one JSON line per run
  - `load_history(days: int = 30)` — read JSONL, return last 100 entries
- Wire `save_run(report)` into `runner.py` after `_build_run_report()`
- Add `NIGHTWATCH_HISTORY_DIR` env var to `config.py`

**Verification**: Run `--dry-run`, confirm `~/.nightwatch/run_history.jsonl` created with valid JSON per line. `load_history()` returns it.

### Step 3.2 — Create Pattern Analysis workflow
- Create `nightwatch/workflows/patterns.py`:
  - `PATTERN_SYSTEM_PROMPT` — inline prompt for systemic pattern detection
  - `PatternAnalysisWorkflow(Workflow)` with `@register`
  - `safe_outputs = [CREATE_ISSUE, SEND_SLACK]`
  - `fetch()` → `load_history()` → pre-aggregate by error class and transaction → `WorkflowItem` with `raw_data` containing aggregations
  - `filter()` → only proceed if recurring errors exist (min_occurrences threshold)
  - `analyze()` → send aggregated history to Claude → parse JSON patterns response
  - `act()` → create GitHub issues with `pattern` label, deduplicate against existing open pattern issues
  - `report_section()` → Slack blocks per detected pattern with severity emoji

**Verification**: Mock history data, verify aggregation, filtering, and issue creation logic.

### Step 3.3 — Register and wire up
- Add `import nightwatch.workflows.patterns` to `runner.py`
- Verify `--workflows patterns` works standalone
- Verify pattern analysis gracefully skips when insufficient data

### Step 3.4 — Write Phase 3 tests
- `tests/test_history.py` — save/load round-trip, JSONL format, empty file handling
- `tests/test_patterns.py` — aggregation logic, min_occurrences filtering, pattern issue dedup, graceful skip on empty history

**Done when**: History saved after each run. Pattern analysis detects recurring error classes. Pattern issues created with dedup. Graceful skip when insufficient data.

---

## Phase 4: Ralph Feedback Loop

**Goal**: Generate `guardrails.md`-compatible output from NightWatch findings for Ralph consumption.

**Branch**: `feat/ralph-guardrails`
**Depends on**: Phase 1 merged, Phase 3 recommended (for pattern-based signs)

### Step 4.1 — Implement guardrails generator
- Create `nightwatch/guardrails.py`:
  - `generate_guardrails(report, output_path)` → markdown string
  - Per high-confidence analysis: generate a Sign (Trigger, Instruction, Added after, Example)
  - `_generate_pattern_signs()` → recurring error classes from history become Signs
  - `_extract_module()` — parse transaction name to readable module
  - `_slugify()` — clean text for sign names

**Verification**: Given a mock RunReport with 3 analyses (2 high-confidence, 1 low), generate guardrails with exactly 2 signs.

### Step 4.2 — Wire up CLI and config
- Add `--guardrails-output` flag to `__main__.py`
- Add `NIGHTWATCH_GUARDRAILS_OUTPUT` to `config.py`
- Call `generate_guardrails()` in `runner.py` after Slack report, if output path configured

**Verification**: `python -m nightwatch run --guardrails-output .ralph/guardrails.md --dry-run` creates the file.

### Step 4.3 — Write Phase 4 tests
- `tests/test_guardrails.py`:
  - Sign format correctness (markdown structure)
  - High-confidence analyses produce signs, low-confidence skipped
  - Pattern-based signs generated from history
  - Empty run produces valid empty guardrails file
  - Output file written to specified path

**Done when**: Guardrails file generated in Ralph's Sign format. File written to configured path. Ralph can read it.

---

## Dependency Graph

```
Phase 1 (Architecture) ──┬── Phase 2 (CI Doctor)
                          ├── Phase 3 (Pattern Analysis)
                          └── Phase 4 (Ralph Guardrails)

Phase 3 ──── Phase 4 benefits from history data (soft dependency)
```

Phases 2, 3, 4 are independent of each other. They all depend on Phase 1. Phase 4 produces richer guardrails when Phase 3 has generated history, but works without it.

---

## Files Created / Modified Per Phase

### Phase 1 (6 new, 3 modified)
| Action | File |
|--------|------|
| CREATE | `nightwatch/workflows/__init__.py` |
| CREATE | `nightwatch/workflows/base.py` |
| CREATE | `nightwatch/workflows/registry.py` |
| CREATE | `nightwatch/workflows/errors.py` |
| CREATE | `nightwatch.yml.example` |
| CREATE | `tests/test_workflows_base.py`, `tests/test_workflows_registry.py`, `tests/test_workflows_errors.py` |
| MODIFY | `nightwatch/runner.py` |
| MODIFY | `nightwatch/__main__.py` |
| MODIFY | `nightwatch/config.py` |

### Phase 2 (2 new, 1 modified)
| Action | File |
|--------|------|
| CREATE | `nightwatch/workflows/ci_doctor.py` |
| CREATE | `tests/test_ci_doctor.py` |
| MODIFY | `nightwatch/runner.py` (add import) |

### Phase 3 (3 new, 1 modified)
| Action | File |
|--------|------|
| CREATE | `nightwatch/history.py` |
| CREATE | `nightwatch/workflows/patterns.py` |
| CREATE | `tests/test_history.py`, `tests/test_patterns.py` |
| MODIFY | `nightwatch/runner.py` (add import + save_run call) |

### Phase 4 (2 new, 2 modified)
| Action | File |
|--------|------|
| CREATE | `nightwatch/guardrails.py` |
| CREATE | `tests/test_guardrails.py` |
| MODIFY | `nightwatch/runner.py` (add guardrails call) |
| MODIFY | `nightwatch/__main__.py` (add --guardrails-output flag) |

---

## Risk Checkpoints

After each phase, verify before proceeding:

| Check | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|-------|---------|---------|---------|---------|
| `pytest tests/` all green | Required | Required | Required | Required |
| `ruff check && ruff format --check` clean | Required | Required | Required | Required |
| `python -m nightwatch run --dry-run` works | Required | Required | Required | Required |
| Existing behavior unchanged | Required | Required | Required | Required |
| New feature works with `--workflows` flag | N/A | Required | Required | N/A |
| New feature works with `--dry-run` | N/A | Required | Required | Required |

---

## Execution Order Recommendation

1. **Phase 1 first** — foundation for everything. Ship and merge before starting Phase 2/3/4.
2. **Phase 3 next** — history persistence benefits all future phases, and pattern analysis is self-contained.
3. **Phase 2 next** — CI Doctor is highest user-facing value but has more external dependencies (GitHub Actions API, real CI failures to test against).
4. **Phase 4 last** — guardrails are most valuable once history data exists from Phase 3.

Alternative: Phases 2 and 3 can be developed in parallel on separate branches since they're independent.

---

## No New Dependencies

All 4 phases use existing dependencies from `pyproject.toml`:
- `anthropic` — Claude API (CI Doctor + Patterns use same client)
- `PyGithub` — GitHub Actions runs, workflow logs, issue/comment creation
- `pydantic` — workflow dataclasses already using it
- `pyyaml` — nightwatch.yml config file
- Standard library: `zipfile`, `json`, `pathlib`, `collections`, `re`

Zero new pip installs required.
