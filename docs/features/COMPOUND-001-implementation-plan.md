# COMPOUND-001: Compound Intelligence Implementation Plan

**Status**: Ready to Execute
**Scope**: Synthesized implementation of 3 openspec proposals
**Estimated effort**: ~2 days (10-14 hours of focused work)
**PRs consolidated**: #1 (compound-engineering-patterns), #2 (ralph-integration), #3 (compound-product-integration)

---

## Executive Summary

This plan synthesizes three openspec proposals into a single, dependency-ordered implementation sequence. Rather than implementing each proposal in isolation, we interleave their features by dependency graph to deliver maximum value at each phase.

**What we're building:**
1. A knowledge compounding system that makes every NightWatch run smarter than the last
2. A research-before-analyze pipeline that pre-populates context before Claude's main loop
3. Multi-pass analysis for low-confidence errors (retry with accumulated knowledge)
4. Quality gates that validate PRs before creation (lint/typecheck/test)
5. Cross-error pattern detection within and across runs
6. Configurable agent definitions (markdown + YAML frontmatter)
7. Self-health reporting for future self-improvement integration

---

## Open Decisions (Confirm Before Starting)

These default to the recommended option from `decisions.md`. Override if needed.

| ID | Decision | Default | Alternatives |
|----|----------|---------|-------------|
| D1 | Knowledge base location | `nightwatch/knowledge/` | `~/.nightwatch/knowledge/`, separate repo |
| D2 | Git-track knowledge? | Hybrid: patterns yes, raw error data `.gitignore`'d | All tracked, none tracked |
| D4 | Agent config format | Markdown + YAML frontmatter | YAML only, TOML |
| D5 | Knowledge search timing | Before analysis, injected in prompt | During analysis via tool |
| D6 | Pattern detection frequency | Per-run (end of pipeline) | Per-error, daily cron |

---

## Phase 1: Knowledge Foundation

**Branch**: `feature/knowledge-foundation`
**Estimated time**: 3-4 hours
**Sources**: compound-engineering-patterns P1 (Knowledge Compounding) + P4 (Agent Config)

### What We're Building

A file-based knowledge store where NightWatch persists what it learns from each error analysis, plus a configurable agent definition system.

### Files to Create

#### `nightwatch/knowledge/README.md`
Schema documentation for knowledge entries.

#### `nightwatch/knowledge/.gitkeep`
Ensure directory exists in git. Raw error entries will be `.gitignore`'d; pattern files tracked.

#### `nightwatch/knowledge_store.py`
```
KnowledgeStore class:
  - __init__(knowledge_dir: Path)
  - save_entry(error_class, transaction, analysis, run_date) -> Path
  - search(query: str, limit: int = 5) -> list[KnowledgeEntry]
  - find_by_error_class(error_class: str) -> list[KnowledgeEntry]
  - find_by_pattern(pattern: str) -> list[KnowledgeEntry]
  - get_all_patterns() -> list[str]

Entry format: YAML frontmatter + markdown body
  ---
  error_class: "Net::ReadTimeout"
  transaction: "Controller/api/v2/products#show"
  confidence: "high"
  root_cause: "External API timeout without circuit breaker"
  has_fix: true
  date: "2025-01-15"
  tags: [timeout, external-api, circuit-breaker]
  ---
  ## Analysis
  [Full analysis text]
  ## Fix Applied
  [Description of fix if PR was created]

Search strategy: grep-first (no vector DB, no embeddings)
  - Primary: exact match on error_class
  - Secondary: grep for keywords in frontmatter tags
  - Tertiary: full-text grep across all entries
```

#### `nightwatch/agents/`
Directory for agent definition files.

#### `nightwatch/agents/error-analyst.md`
```
---
name: error-analyst
description: "Primary error analysis agent"
model: claude-sonnet-4-5-20250929
max_iterations: 15
thinking_budget: 8000
allowed_tools: [read_file, search_code, list_directory, get_error_traces]
---
## System Prompt
[Current system prompt from prompts.py, extracted into configurable file]
```

#### `nightwatch/agent_config.py`
```
AgentConfig dataclass:
  - name: str
  - description: str
  - model: str
  - max_iterations: int
  - thinking_budget: int
  - allowed_tools: list[str]
  - system_prompt: str

load_agent_config(path: Path) -> AgentConfig
  - Parse YAML frontmatter
  - Extract markdown body as system_prompt
  - Validate against schema
```

### Files to Modify

#### `nightwatch/models.py`
- Add `KnowledgeEntry` model (Pydantic)
- Add `AgentConfig` model (Pydantic)

#### `nightwatch/runner.py`
- Import KnowledgeStore
- Step 12 (new): After analysis, persist knowledge entry
- Initialize knowledge store in `run()` function

#### `nightwatch/analyzer.py`
- Accept `AgentConfig` parameter (optional, backward-compatible)
- Use agent config for model, max_iterations, thinking_budget if provided

#### `nightwatch/prompts.py`
- Extract system prompt to `agents/error-analyst.md` (keep as fallback)
- Add function to load prompt from agent config

#### `.gitignore`
- Add `nightwatch/knowledge/entries/` (raw error data)
- Keep `nightwatch/knowledge/patterns/` tracked

### Tests

- `tests/test_knowledge_store.py` — save, search by class, search by pattern, dedup
- `tests/test_agent_config.py` — parse valid config, reject invalid, fallback to defaults

### Acceptance Criteria

- [ ] After `nightwatch run`, knowledge entries appear in `nightwatch/knowledge/`
- [ ] `KnowledgeStore.search("Net::ReadTimeout")` returns relevant prior analyses
- [ ] Agent config loads from markdown file and overrides defaults
- [ ] Existing behavior unchanged when no knowledge/config files present (backward compat)

---

## Phase 2: Analysis Enhancement

**Branch**: `feature/analysis-enhancement`
**Estimated time**: 2-3 hours
**Sources**: compound-engineering-patterns P3 (Research-Before-Analyze) + ralph-integration R1 (Multi-Pass)
**Depends on**: Phase 1 (knowledge store)

### What We're Building

A pre-analysis research step that searches the knowledge base and pre-fetches relevant code context before Claude's main analysis loop. Plus multi-pass retry logic for low-confidence results.

### Files to Create

#### `nightwatch/research.py`
```
ResearchContext dataclass:
  - prior_analyses: list[KnowledgeEntry]   # From knowledge store
  - related_files: list[str]               # Pre-identified file paths
  - recent_prs: list[dict]                 # Recently merged PRs touching error area
  - similar_ignores: list[dict]            # Similar patterns in ignore.yml

research_error(error_group, knowledge_store, github_client) -> ResearchContext
  1. Search knowledge store for error_class matches
  2. Search knowledge store for transaction matches
  3. Extract file paths from prior analyses
  4. Check recent PRs for related file changes (via correlation.py)
  5. Check ignore.yml for similar patterns
  6. Return assembled context

format_research_for_prompt(context: ResearchContext) -> str
  - Format prior analyses as "Previous findings for this error type:"
  - List known file paths as "Files likely relevant:"
  - Include recent PR context as "Recent changes in this area:"
  - Keep under 2000 tokens (summarize if needed)
```

### Files to Modify

#### `nightwatch/analyzer.py`
- Add `research_context: str | None` parameter to `analyze_error()`
- Inject research context into first user message (before error details)
- Add multi-pass logic:
  ```
  result = analyze_error(error, research_context)
  if result.confidence == "low" and not is_retry:
      # Second pass with accumulated knowledge
      enhanced_context = format_research_for_prompt(context) + format_first_pass(result)
      result = analyze_error(error, enhanced_context, is_retry=True)
  ```
- Track `api_calls_count` for cost monitoring

#### `nightwatch/runner.py`
- Add Step 6.5 (between fetch traces and analyze): research phase
  ```
  for error in selected_errors:
      research_ctx = research_error(error, knowledge_store, github)
      result = analyze_with_retry(error, research_ctx)
  ```

#### `nightwatch/models.py`
- Add `ResearchContext` model
- Add `is_retry: bool` field to `ErrorAnalysisResult`
- Add `research_tokens: int` to `RunReport` for cost tracking

### Tests

- `tests/test_research.py` — context assembly, token limit enforcement, empty knowledge handling
- `tests/test_analyzer.py` — multi-pass trigger on low confidence, no retry on high/medium

### Acceptance Criteria

- [ ] Errors with prior knowledge entries show research context in Claude's conversation
- [ ] Low-confidence analyses get a second pass (visible in logs)
- [ ] High/medium confidence analyses are NOT retried (cost control)
- [ ] Research context stays under 2000 tokens
- [ ] API cost delta tracked in run report

---

## Phase 3: Quality Gates & Run Context

**Branch**: `feature/quality-gates`
**Estimated time**: 3-4 hours
**Sources**: ralph-integration R2 (Quality Gate) + R3 (Progress Accumulation)
**Depends on**: Phase 1 (knowledge store for context persistence)

### What We're Building

A quality validation gate that runs lint/typecheck/test on proposed PR changes before creating the actual PR. Plus a run-level context accumulator that feeds discoveries from earlier error analyses into later ones.

### Files to Create

#### `nightwatch/quality_gate.py`
```
QualityGateResult dataclass:
  - passed: bool
  - lint_output: str | None
  - typecheck_output: str | None
  - test_output: str | None
  - errors: list[str]

validate_changes(
    repo_path: Path,           # Cloned repo path
    file_changes: list[FileChange],
    base_branch: str
) -> QualityGateResult:
    1. Create temp branch from base
    2. Apply file changes
    3. Run lint (detect linter from project config)
    4. Run typecheck (detect from project config)
    5. Run relevant tests (detect test framework)
    6. Collect results
    7. Clean up temp branch

attempt_correction(
    analysis_result: Analysis,
    gate_result: QualityGateResult,
    client: Anthropic,
    agent_config: AgentConfig
) -> Analysis | None:
    1. Feed gate errors back to Claude
    2. Ask for corrected file changes
    3. Re-validate
    4. Return corrected analysis or None if still failing
```

### Files to Modify

#### `nightwatch/github.py`
- Before `create_pull_request()`, run quality gate:
  ```
  gate = validate_changes(repo_clone_path, analysis.file_changes, base_branch)
  if not gate.passed:
      corrected = attempt_correction(analysis, gate, client, config)
      if corrected:
          analysis = corrected
      else:
          # Downgrade: create issue instead of PR
          log.warning("Quality gate failed after correction attempt")
          create_issue_instead(error, analysis)
          return
  ```
- Add `clone_repo()` helper (shallow clone to temp dir)

#### `nightwatch/runner.py`
- Add `run_context: dict` initialized at run start
- After each error analysis, accumulate discoveries:
  ```
  run_context["codebase_patterns"].append(result.analysis.root_cause)
  run_context["files_examined"].extend(result.files_read)
  run_context["common_themes"].append(result.analysis.reasoning)
  ```
- Inject summarized run context into subsequent analyses:
  ```
  context_summary = summarize_run_context(run_context)  # Keep < 500 tokens
  ```
- Add compression when run_context grows too large

#### `nightwatch/config.py`
- Add `NIGHTWATCH_QUALITY_GATE=true` setting (disable for dry-run)
- Add `NIGHTWATCH_REPO_CLONE_DIR=/tmp/nightwatch-repos` setting

### Tests

- `tests/test_quality_gate.py` — pass/fail scenarios, correction attempt, cleanup
- `tests/test_runner.py` — context accumulation, summarization, token limits

### Acceptance Criteria

- [ ] PRs that fail lint/typecheck trigger a correction pass to Claude
- [ ] Corrected PRs are re-validated before creation
- [ ] Failed corrections result in issue creation (not PR)
- [ ] Run context from error 1 is available during error 5's analysis
- [ ] Run context stays under 500 tokens (summarized)
- [ ] Quality gate is skippable via `--no-quality-gate` or `--dry-run`

---

## Phase 4: Compound Intelligence

**Branch**: `feature/compound-intelligence`
**Estimated time**: 1-2 hours
**Sources**: compound-engineering-patterns P5 (Autonomous Compound Loop)
**Depends on**: Phase 1 (knowledge store) + Phase 3 (run context)

### What We're Building

End-of-run intelligence that detects patterns across errors, suggests ignore.yml updates, and builds a knowledge index for faster future searches.

### Files to Modify

#### `nightwatch/knowledge_store.py`
- Add `detect_patterns(entries: list[KnowledgeEntry]) -> list[Pattern]`
  ```
  Pattern detection rules:
  - Same error_class appearing 3+ times → suggest ignore pattern
  - Same root_cause across different errors → extract common pattern
  - Same file appearing in 5+ analyses → flag as hotspot
  - Low confidence on same error_class repeatedly → flag for human review
  ```
- Add `suggest_ignore_updates(patterns) -> list[IgnoreSuggestion]`
- Add `build_index() -> dict` — generates searchable index of all entries

#### `nightwatch/runner.py`
- Step 12 (enhanced): After all analyses complete:
  ```
  # Persist individual learnings (Phase 1)
  for result in results:
      knowledge_store.save_entry(result)

  # Detect cross-error patterns (Phase 4)
  all_entries = knowledge_store.get_recent(days=30)
  patterns = knowledge_store.detect_patterns(all_entries)

  # Suggest ignore.yml updates
  suggestions = knowledge_store.suggest_ignore_updates(patterns)
  if suggestions:
      report.ignore_suggestions = suggestions
      log.info(f"Suggested {len(suggestions)} ignore pattern updates")

  # Rebuild knowledge index
  knowledge_store.build_index()
  ```

#### `nightwatch/slack.py`
- Add "Compound Intelligence" section to daily report:
  ```
  - Patterns detected: N
  - Ignore suggestions: [list]
  - Knowledge entries: N total, M new today
  - Hotspot files: [list]
  ```

#### `nightwatch/models.py`
- Add `Pattern` model
- Add `IgnoreSuggestion` model
- Add `ignore_suggestions` and `patterns_detected` to `RunReport`

### Tests

- `tests/test_compound.py` — pattern detection rules, ignore suggestions, index building

### Acceptance Criteria

- [ ] Repeated error classes (3+) generate ignore suggestions
- [ ] Common root causes across errors are detected and logged
- [ ] Hotspot files are identified and included in Slack report
- [ ] Knowledge index is rebuilt at end of each run
- [ ] Suggestions appear in Slack daily report

---

## Phase 5: Self-Health Report

**Branch**: `feature/health-report`
**Estimated time**: 1 hour
**Sources**: compound-product-integration (prerequisites only — full integration blocked on license)
**Depends on**: Phase 4 (knowledge store with patterns)

### What We're Building

A `nightwatch health` CLI command that generates a structured self-health report about NightWatch's own operation. This is the prerequisite for future compound-product integration.

### Files to Create

#### `nightwatch/health_report.py`
```
generate_health_report(
    knowledge_store: KnowledgeStore,
    config: Settings,
    last_n_runs: int = 7
) -> str:
    Report sections:
    1. Run history (last N runs: success/fail, errors analyzed, issues created)
    2. Analysis quality (confidence distribution, retry rate, correction rate)
    3. Knowledge base stats (total entries, growth rate, pattern coverage)
    4. API usage (tokens consumed, cost estimate, cache hit rate)
    5. Quality gate stats (pass rate, common failures)
    6. Top recurring errors (candidates for ignore.yml)
    7. Suggested improvements (auto-detected from patterns)

    Output: Markdown document suitable for LLM consumption
```

### Files to Modify

#### `nightwatch/__main__.py`
- Add `health` subcommand:
  ```
  python -m nightwatch health [--days 7] [--output report.md]
  ```

#### `nightwatch/runner.py`
- Add `save_run_metrics(report: RunReport)` at end of run
- Persist to `nightwatch/knowledge/runs/YYYY-MM-DD.json`

### Tests

- `tests/test_health_report.py` — report generation, missing data handling

### Acceptance Criteria

- [ ] `python -m nightwatch health` produces a readable markdown report
- [ ] Report includes all 7 sections
- [ ] Report works even with zero prior runs (empty state)
- [ ] Run metrics are persisted after each `nightwatch run`

---

## Phase 6: Future Work (Not Scheduled)

### Multi-Agent Parallel Analysis (compound-engineering-patterns P2)
- **Status**: Deferred
- **Reason**: Medium feasibility, unclear value until single-agent is well-tuned
- **Prerequisite**: Phase 1 agent config must be stable
- **Approach**: Specialized sub-agents (root cause, security, blast radius, fix) → synthesis agent

### Full compound-product Integration
- **Status**: BLOCKED — no license on compound-product repo
- **Prerequisite**: License resolution (contact snarktank or wait)
- **When unblocked**: Install compound-product, schedule after NightWatch health report, validate for 30 days

### Story Decomposition for Complex Fixes (ralph-integration R4)
- **Status**: Deferred
- **Reason**: Overkill for current scope (single daily batch run)
- **When needed**: When NightWatch attempts multi-file fixes that consistently fail quality gates

---

## Branching & Merge Strategy

```
main
  ├── feature/knowledge-foundation    → PR #4 → merge to main
  ├── feature/analysis-enhancement    → PR #5 → merge to main
  ├── feature/quality-gates           → PR #6 → merge to main
  ├── feature/compound-intelligence   → PR #7 → merge to main
  └── feature/health-report           → PR #8 → merge to main
```

Each phase merges to main before the next begins. Each PR includes:
- Implementation code
- Tests
- Updated `docs/features/COMPOUND-001-implementation-plan.md` (status updates)

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Knowledge search too slow (large store) | Medium | Low | Grep-first strategy, index file, no vector DB |
| Multi-pass doubles API cost | High | Medium | Only retry LOW confidence, track cost in report |
| Quality gate requires repo clone | Medium | Medium | Shallow clone to /tmp, cleanup after |
| Run context prompt bloat | Medium | Medium | Hard cap at 500 tokens, summarization |
| compound-product license never resolved | Low | Medium | Health report has standalone value regardless |
| Agent config breaks backward compat | High | Low | Fallback to hardcoded defaults when no config present |

---

## Success Metrics (After 30 Days)

- **Knowledge entries**: 100+ accumulated (5 errors/day × 20 runs)
- **Research hit rate**: >30% of analyses have relevant prior knowledge
- **Confidence improvement**: Average confidence moves from medium → high
- **Multi-pass rate**: <20% of analyses need retry (learning reduces over time)
- **Quality gate pass rate**: >70% of PRs pass on first attempt
- **Pattern detection**: 5-10 ignore suggestions generated
- **Hotspot identification**: Top 5 problem files identified
