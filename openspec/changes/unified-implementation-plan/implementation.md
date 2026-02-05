# NightWatch — Unified Implementation Plan

**ID**: IMPL-001
**Status**: Approved
**Approved Date**: 2026-02-05
**Author**: Claude (AI Assistant)
**Date**: 2026-02-05
**Scope**: NightWatch pipeline enhancements — multi-pass analysis, knowledge compounding, quality gates
**Inputs**: TOOL-002 (OpenCode evaluation), RALPH-001 (Ralph pattern adoption), COMPOUND-001 (Compound engineering patterns)
**Total Estimated Effort**: 3 days
**Dependencies**: Zero new runtime dependencies (all features use existing stack)

---

## 1. Executive Summary

TOOL-002 (OpenCode Evaluation) concluded: **don't adopt OpenCode**. Instead, invest in three high-ROI improvements to NightWatch's core pipeline:

| Stream | Source | Priority | Effort | Value |
|--------|--------|----------|--------|-------|
| **A. Multi-Pass Analysis + Quality Gates** | RALPH-001 | High | 1 day | Catches more root causes, eliminates broken PRs |
| **B. Knowledge Compounding** | COMPOUND-001 | High | 1.5 days | Each run makes the next smarter |
| **C. Amp Code Trial** | TOOL-001 | Low | 0.5 days | Evaluate Deep Mode for NightWatch dev |

This plan sequences all three streams into a **3-day implementation roadmap** with clear dependencies, file-level changes, and validation criteria.

---

## 2. Sequencing & Dependencies

```
Day 1 (AM)  ─── Stream A, Phase 1: Multi-Pass Analysis + Run Context
                 ├── models.py: Add RunContext, AnalysisPassResult, extend ErrorAnalysisResult
                 ├── analyzer.py: Extract _single_pass(), add multi-pass retry
                 ├── prompts.py: Add seed_knowledge to build_analysis_prompt()
                 ├── runner.py: Thread RunContext through analysis loop
                 ├── config.py: Add max_passes, retry_on_low_confidence
                 └── tests/test_analyzer.py: Multi-pass logic tests

Day 1 (PM)  ─── Stream A, Phase 2: Quality Gate for Draft PRs
                 ├── validation.py (NEW): validate_file_changes(), _check_ruby_syntax()
                 ├── analyzer.py: Add attempt_correction()
                 ├── runner.py: Wire validation before PR creation
                 ├── config.py: Add validate_pr, attempt_correction
                 └── tests/test_validation.py: Validation + correction tests

Day 2 (AM)  ─── Stream B, Phase 1: Knowledge Foundation
                 ├── nightwatch/knowledge/ directory (git-tracked)
                 ├── knowledge.py (NEW): KnowledgeStore, search, write
                 ├── models.py: Add SolutionDoc model
                 ├── analyzer.py: Inject knowledge before analysis
                 ├── runner.py: Write solution docs after analysis
                 └── tests/test_knowledge.py: Knowledge store tests

Day 2 (PM)  ─── Stream B, Phase 2: Pattern Detection
                 ├── patterns.py (NEW): detect_patterns(), PatternReport
                 ├── runner.py: Cross-error pattern detection at end of run
                 ├── slack.py: Add patterns section to daily report
                 └── tests/test_patterns.py: Pattern detection tests

Day 3 (AM)  ─── Stream A, Phase 3: Enhanced Reporting
                 ├── models.py: Add retry/correction metrics to RunReport
                 ├── slack.py: Update report blocks with multi-pass + validation metrics
                 └── Integration testing with dry-run

Day 3 (PM)  ─── Stream C: Amp Code Trial (optional, independent)
                 ├── Install Amp CLI alongside Claude Code
                 ├── Create AGENTS.md for NightWatch
                 ├── Run 2-3 NightWatch dev tasks with Deep Mode
                 └── Document comparison findings
```

**Critical path**: Stream A Phase 1 → Stream A Phase 2 → Stream B Phase 1

Stream B Phase 1 depends on Stream A Phase 1 because `RunContext` from Stream A becomes the in-memory precursor to the persistent `KnowledgeStore` in Stream B. The two share data structures and the injection point in `analyzer.py`.

Stream C (Amp Code trial) is fully independent and can be done anytime or skipped.

---

## 3. Stream A: Multi-Pass Analysis + Quality Gates (RALPH-001)

> Full specification: [`openspec/changes/ralph-pattern-adoption/proposal.md`](../ralph-pattern-adoption/proposal.md)

### Phase 1: Multi-Pass Analysis + Run Context

**Goal**: When Claude returns `confidence="low"`, retry with fresh context + pass 1 findings. Share codebase discoveries across errors within a run.

#### File Changes

##### `nightwatch/models.py` — Add 2 new dataclasses, extend 2 existing

```
ADD: AnalysisPassResult (dataclass)
  - pass_number: int
  - analysis: Analysis
  - iterations: int
  - tokens_used: int
  - files_examined: list[str]
  - patterns_discovered: list[str]

ADD: RunContext (dataclass)
  - codebase_patterns: list[str]
  - files_examined: dict[str, str]  # path → summary
  - error_relationships: list[str]
  - to_prompt_section() → str  # format for Claude injection

EXTEND: ErrorAnalysisResult
  + passes: int = 1
  + pass_history: list[AnalysisPassResult]
  + files_examined: list[str]
  + patterns_discovered: list[str]
```

**Estimated lines added**: ~50

##### `nightwatch/analyzer.py` — Extract method, add multi-pass logic

```
REFACTOR: analyze_error() → wrapper that calls _single_pass() in a loop
  - Signature adds: run_context: RunContext | None, max_passes: int = 2
  - Loop: for pass_num in range(1, max_passes + 1)
  - Break if confidence != LOW or pass_num >= max_passes
  - Build seed knowledge from pass 1 for pass 2
  - Select best pass via _select_best_pass()
  - Update run_context with discoveries

EXTRACT: _single_pass() from current analyze_error() body
  - Signature: _single_pass(client, model, error, traces, github_client,
                             newrelic_client, max_iterations, seed_knowledge=None)
  - Returns: _PassResult (iterations, tokens, analysis, files_examined, patterns)
  - seed_knowledge prepended to initial user message

ADD: _build_retry_seed(result, run_context) → str
  - Formats pass 1 findings as structured context for pass 2
  - Includes: reasoning, root_cause, files_examined, suggested_next_steps

ADD: _select_best_pass(pass_history) → AnalysisPassResult
  - Prefer: has_fix=True > higher confidence > more file_changes
  - Tiebreak: later pass (more information)

ADD: _extract_files_examined(messages) → list[str]
  - Scan tool_use/tool_result blocks for read_file paths
  - Used to populate pass result

ADD: _extract_patterns(analysis) → list[str]
  - Extract codebase patterns from analysis reasoning
  - Simple: split reasoning into sentences, filter for pattern-like assertions
```

**Estimated lines added/modified**: ~120 added, ~30 modified (analyze_error refactor)

##### `nightwatch/prompts.py` — Accept seed knowledge

```
MODIFY: build_analysis_prompt()
  + seed_knowledge: str | None = None parameter
  - If seed_knowledge provided, append after trace data section:
    "\n## Additional Context\n{seed_knowledge}"
```

**Estimated lines modified**: ~5

##### `nightwatch/runner.py` — Thread RunContext, log relationships

```
MODIFY: run() function
  + Initialize: run_context = RunContext()
  + Pass run_context to analyze_error() calls
  + After each analysis: _note_relationships(run_context, result, prior_analyses)
  + Track multi_pass_retries count for RunReport

ADD: _note_relationships(run_context, result, prior_analyses)
  - Compare result.error.transaction with prior errors
  - If same controller/module prefix, add relationship note
```

**Estimated lines added/modified**: ~25

##### `nightwatch/config.py` — New settings

```
ADD: nightwatch_max_passes: int = 2
ADD: nightwatch_retry_on_low_confidence: bool = True
```

**Estimated lines added**: ~4

##### `tests/test_analyzer.py` — New test file

```
ADD: test_single_pass_returns_result()
ADD: test_multi_pass_triggers_on_low_confidence()
ADD: test_multi_pass_skips_on_high_confidence()
ADD: test_select_best_pass_prefers_has_fix()
ADD: test_build_retry_seed_includes_prior_findings()
ADD: test_run_context_accumulates_patterns()
ADD: test_run_context_to_prompt_section_caps_entries()
```

**Estimated lines**: ~120

#### Validation Criteria — Phase 1

- [ ] `analyze_error()` signature unchanged for callers not using new params (backward compatible)
- [ ] `RunContext.to_prompt_section()` stays under 2000 tokens with 10 patterns + 15 files
- [ ] Multi-pass only triggers when `confidence == Confidence.LOW`
- [ ] `_select_best_pass()` always returns a result (never empty)
- [ ] All existing tests pass
- [ ] Dry-run mode works with multi-pass enabled
- [ ] `ruff check` and `ruff format --check` pass

---

### Phase 2: Quality Gate for Draft PRs

**Goal**: Validate proposed file changes before creating a PR. If validation fails, give Claude one correction attempt.

#### File Changes

##### `nightwatch/validation.py` — New file

```
ADD: ValidationResult class
  - passed: bool
  - errors: list[str]
  - warnings: list[str]
  - fail(msg) / warn(msg) methods

ADD: validate_file_changes(file_changes, github_client) → ValidationResult
  Checks:
  1. Content exists for create/modify actions
  2. Modified files exist in repo (via github_client.read_file)
  3. Created files don't already exist (warning, not error)
  4. Ruby syntax basics for .rb files (_check_ruby_syntax)

ADD: _check_ruby_syntax(content) → list[str]
  - Count def/class/module/do/if/unless/begin openers vs end closers
  - Flag imbalance > 1
  - Lightweight, not a parser — catches obvious breaks only
```

**Estimated lines**: ~80

##### `nightwatch/analyzer.py` — Add correction function

```
ADD: attempt_correction(error, analysis, validation_errors, github_client) → Analysis | None
  - Fresh Claude call with correction prompt
  - Includes: validation errors, original analysis reasoning, proposed file changes
  - Returns corrected Analysis or None if correction fails
  - Max 1 correction attempt (no recursion)

ADD: _format_file_changes(file_changes) → str
  - Helper to format FileChange list as readable text for correction prompt
```

**Estimated lines added**: ~60

##### `nightwatch/runner.py` — Wire quality gate before PR creation

```
MODIFY: run() function, Step 10 (PR creation block, ~lines 223-231)
  + Import validate_file_changes, attempt_correction
  + Before create_pull_request():
    1. validation = validate_file_changes(result.analysis.file_changes, gh)
    2. If failed: attempt_correction()
    3. If correction succeeds: re-validate
    4. If still failing: skip PR, log warning
  + Track corrections_attempted, corrections_succeeded for RunReport
```

**Estimated lines modified**: ~30

##### `nightwatch/config.py` — New settings

```
ADD: nightwatch_validate_pr: bool = True
ADD: nightwatch_attempt_correction: bool = True
```

**Estimated lines added**: ~4

##### `tests/test_validation.py` — New test file

```
ADD: test_validate_empty_content_fails()
ADD: test_validate_modify_nonexistent_file_fails()
ADD: test_validate_create_existing_file_warns()
ADD: test_ruby_syntax_balanced_blocks()
ADD: test_ruby_syntax_unbalanced_fails()
ADD: test_valid_changes_pass()
ADD: test_attempt_correction_returns_fixed_analysis()
ADD: test_attempt_correction_returns_none_on_failure()
```

**Estimated lines**: ~100

#### Validation Criteria — Phase 2

- [ ] `validate_file_changes()` catches: empty content, nonexistent files, unbalanced Ruby blocks
- [ ] `attempt_correction()` creates a fresh Claude call (not appended to existing conversation)
- [ ] Correction pass is capped at 1 attempt (no infinite loops)
- [ ] If both validation and correction fail, PR is skipped (not created broken)
- [ ] If `nightwatch_validate_pr=False`, validation is skipped entirely
- [ ] All Phase 1 tests still pass
- [ ] `ruff check` and `ruff format --check` pass

---

### Phase 3: Enhanced Reporting (Day 3 AM)

**Goal**: Surface multi-pass and quality gate metrics in RunReport and Slack summary.

#### File Changes

##### `nightwatch/models.py` — Extend RunReport

```
EXTEND: RunReport
  + multi_pass_retries: int = 0
  + corrections_attempted: int = 0
  + corrections_succeeded: int = 0

  + @property retry_rate → float
  + @property correction_success_rate → float
```

**Estimated lines added**: ~12

##### `nightwatch/slack.py` — Update report blocks

```
MODIFY: _build_report_blocks()
  + Add "Pipeline Intelligence" section after analysis details:
    - "Multi-pass retries: {N} ({retry_rate}%)"
    - "PR corrections: {attempted} attempted, {succeeded} succeeded"
    - "Codebase patterns discovered: {N}"

MODIFY: Per-error section
  + If result.passes > 1: add "(2-pass)" indicator next to confidence emoji
```

**Estimated lines modified**: ~20

##### Integration Testing

```
RUN: python -m nightwatch run --dry-run --verbose
  - Verify multi-pass triggers on low-confidence mock
  - Verify RunContext accumulates across errors
  - Verify validation blocks bad PRs
  - Verify report shows new metrics
```

---

## 4. Stream B: Knowledge Compounding (COMPOUND-001)

> Extends the in-memory `RunContext` from Stream A into a persistent, searchable knowledge base.

### Phase 1: Knowledge Foundation (Day 2 AM)

**Goal**: After each error analysis, write a solution document to `nightwatch/knowledge/`. Before each analysis, search existing knowledge for relevant context.

#### Architecture

```
nightwatch/knowledge/
├── README.md                    # Auto-generated index
├── 2026-02-06_001_net-timeout-products-controller.md
├── 2026-02-06_002_no-method-error-users-api.md
└── ...
```

Each solution document is a Markdown file with YAML frontmatter:

```yaml
---
error_class: Net::ReadTimeout
transaction: Controller/products/show
confidence: medium
has_fix: true
root_cause: External API call in product#show lacks timeout
date: 2026-02-06
run_id: nightwatch-20260206-060000
tags: [timeout, external-api, products]
files_examined: [app/controllers/products_controller.rb, app/services/product_service.rb]
---

# Net::ReadTimeout in Controller/products/show

## Root Cause
External API call in product#show lacks timeout...

## Fix
Add timeout configuration to HTTParty call...

## Codebase Patterns Discovered
- Product service wraps all external APIs via `ExternalApi` concern
- Timeout config lives in `config/timeouts.yml`
```

#### File Changes

##### `nightwatch/knowledge.py` — New file

```
ADD: KnowledgeStore class
  - __init__(base_dir: Path = Path("nightwatch/knowledge"))
  - search(error: ErrorGroup) → list[SolutionDoc]
    Grep-first search: scan frontmatter for error_class, transaction, tags
    Return top 3 matches sorted by relevance
  - write(result: ErrorAnalysisResult) → Path
    Generate filename: YYYY-MM-DD_NNN_<slug>.md
    Write frontmatter + body
    Return path to created file
  - update_index() → None
    Regenerate README.md with counts and recent entries

ADD: SolutionDoc (dataclass)
  - path: Path
  - error_class: str
  - transaction: str
  - confidence: str
  - has_fix: bool
  - root_cause: str
  - date: str
  - tags: list[str]
  - content: str

ADD: _generate_slug(error_class, transaction) → str
  - Lowercase, strip namespace, join with dash, truncate to 50 chars

ADD: _search_frontmatter(base_dir, error_class, transaction) → list[Path]
  - Scan all .md files in knowledge dir
  - Parse YAML frontmatter
  - Score: exact error_class match (1.0) + transaction overlap (0.5) + tag overlap (0.3)
  - Return sorted by score

ADD: _format_knowledge_context(docs: list[SolutionDoc]) → str
  - Format matched docs as prompt section:
    "## Prior Knowledge\n### Similar Error: {title}\n{root_cause}\n{fix}"
```

**Estimated lines**: ~180

##### `nightwatch/models.py` — Add SolutionDoc if not using knowledge.py's version

Minimal — `SolutionDoc` lives in `knowledge.py` to keep models.py clean.

##### `nightwatch/analyzer.py` — Inject knowledge before analysis

```
MODIFY: analyze_error()
  + Accept knowledge_store: KnowledgeStore | None = None
  + Before first pass: search knowledge for this error
  + If matches found: prepend knowledge context to seed_knowledge
  + After final pass: extract patterns for knowledge write
```

**Estimated lines modified**: ~15

##### `nightwatch/runner.py` — Write solution docs after analysis

```
MODIFY: run()
  + Initialize: knowledge_store = KnowledgeStore()
  + Pass knowledge_store to analyze_error()
  + After each analysis: knowledge_store.write(result)
  + After all analyses: knowledge_store.update_index()
```

**Estimated lines modified**: ~10

##### `nightwatch/config.py` — New settings

```
ADD: nightwatch_knowledge_enabled: bool = True
ADD: nightwatch_knowledge_dir: str = "nightwatch/knowledge"
```

**Estimated lines added**: ~4

##### `.gitignore` — Do NOT ignore knowledge/

Knowledge is git-tracked (shared team learning). No gitignore changes.

##### `tests/test_knowledge.py` — New test file

```
ADD: test_write_creates_solution_doc()
ADD: test_search_finds_exact_error_class_match()
ADD: test_search_returns_empty_for_no_match()
ADD: test_search_scores_transaction_overlap()
ADD: test_format_knowledge_context()
ADD: test_update_index_generates_readme()
ADD: test_generate_slug()
```

**Estimated lines**: ~100

#### Validation Criteria — Phase 1 (Knowledge)

- [ ] Solution docs are valid Markdown with valid YAML frontmatter
- [ ] `search()` returns results in <100ms for 100 docs (glob + frontmatter parse)
- [ ] `search()` correctly prioritizes exact error_class matches
- [ ] Knowledge injection stays under 1500 tokens (cap at 3 docs, truncate)
- [ ] `write()` creates files with correct naming: `YYYY-MM-DD_NNN_slug.md`
- [ ] `update_index()` generates accurate README.md
- [ ] Works with `nightwatch_knowledge_enabled=False` (no-op)
- [ ] No new dependencies (uses `pyyaml` already in deps)

---

### Phase 2: Pattern Detection (Day 2 PM)

**Goal**: At the end of each run, detect cross-error patterns and surface them in the Slack report.

#### File Changes

##### `nightwatch/patterns.py` — New file

```
ADD: PatternReport (dataclass)
  - patterns: list[DetectedPattern]
  - run_date: str
  - errors_analyzed: int

ADD: DetectedPattern (dataclass)
  - description: str
  - affected_errors: list[str]  # error_class list
  - evidence: str
  - suggested_action: str

ADD: detect_patterns(analyses: list[ErrorAnalysisResult]) → PatternReport
  Detections:
  1. Module clustering: multiple errors in same controller/module
  2. Error class clustering: same exception across different transactions
  3. File hotspots: same file implicated in multiple analyses
  4. Severity correlation: multiple high-severity errors in related areas

ADD: _detect_module_clusters(analyses) → list[DetectedPattern]
  - Group by transaction prefix (e.g., "Controller/products/*")
  - If 2+ errors share prefix: pattern detected

ADD: _detect_class_clusters(analyses) → list[DetectedPattern]
  - Group by error_class
  - If same class appears in 2+ different transactions: pattern detected

ADD: _detect_file_hotspots(analyses) → list[DetectedPattern]
  - Collect files_examined across all analyses
  - If same file in 3+ analyses: hotspot detected
```

**Estimated lines**: ~120

##### `nightwatch/runner.py` — Run pattern detection at end

```
MODIFY: run()
  + After all analyses, before Slack report:
    pattern_report = detect_patterns(analyses)
  + Pass pattern_report to slack.send_report()
  + Log pattern count
```

**Estimated lines modified**: ~10

##### `nightwatch/slack.py` — Add patterns to daily report

```
MODIFY: _build_report_blocks()
  + If pattern_report has patterns:
    Add "Cross-Error Patterns" section
    For each pattern: description + affected errors + suggested action
```

**Estimated lines modified**: ~25

##### `tests/test_patterns.py` — New test file

```
ADD: test_detect_module_cluster()
ADD: test_detect_class_cluster()
ADD: test_detect_file_hotspot()
ADD: test_no_patterns_returns_empty()
ADD: test_pattern_report_format()
```

**Estimated lines**: ~80

#### Validation Criteria — Phase 2 (Patterns)

- [ ] Pattern detection runs in <50ms for 10 analyses
- [ ] Module cluster detection catches 2+ errors with same transaction prefix
- [ ] File hotspot detection catches files in 3+ analyses
- [ ] Slack report renders patterns cleanly (Block Kit)
- [ ] No patterns = no patterns section (clean report)

---

## 5. Stream C: Amp Code Trial (TOOL-001)

> Independent of Streams A and B. Can be done Day 3 PM or deferred.

### Trial Protocol

**Step 1: Install (15 min)**
```bash
npm install -g @sourcegraph/amp
```
- Requires Node.js v22+
- Verify: `amp --version`

**Step 2: Configure (30 min)**
- Create `AGENTS.md` in NightWatch root with project context:
  - Python 3.11+, sync, batch CLI
  - Key files and their purposes
  - Code conventions (ruff, 100-char lines)
  - Rails target codebase context
- Register existing MCP servers with Amp

**Step 3: Comparative Tasks (2-3 hours)**

| Task | Mode | What to Observe |
|------|------|----------------|
| Debug a tricky NightWatch bug | Deep Mode | Does 5-15 min research phase produce better understanding? |
| Implement a small feature | Smart Mode | Quality vs Claude Code Sonnet |
| Quick config fix | Rush Mode | Speed vs Claude Code for trivial changes |

**Step 4: Document Findings (30 min)**
- Quality comparison: Deep Mode vs Claude Code extended thinking
- Speed comparison: Rush Mode vs Claude Code
- Cost comparison: Daily grant usage
- Workflow friction: config, keybindings, MCP compat

### Success Criteria

| Metric | Target |
|--------|--------|
| Deep Mode produces better analysis | Measurably better on 1+ tasks |
| MCP servers work with Amp | All existing servers functional |
| Cost within free tier | <$10/day average |
| No workflow regression | Development velocity maintained |

### Decision at End of Trial

- **A) Claude Code only** — Amp didn't add enough value
- **B) Both tools** — Claude Code for SuperClaude workflows, Amp for deep research
- **C) Migrate to Amp** — only if trial clearly demonstrates superiority (unlikely)

---

## 6. Complete File Inventory

### New Files (5)

| File | Stream | Phase | Lines (est) | Purpose |
|------|--------|-------|-------------|---------|
| `nightwatch/validation.py` | A | 2 | ~80 | PR file change validation |
| `nightwatch/knowledge.py` | B | 1 | ~180 | Persistent knowledge store |
| `nightwatch/patterns.py` | B | 2 | ~120 | Cross-error pattern detection |
| `tests/test_analyzer.py` | A | 1 | ~120 | Multi-pass analysis tests |
| `tests/test_validation.py` | A | 2 | ~100 | Validation + correction tests |
| `tests/test_knowledge.py` | B | 1 | ~100 | Knowledge store tests |
| `tests/test_patterns.py` | B | 2 | ~80 | Pattern detection tests |

**Total new**: ~780 lines across 7 files

### Modified Files (7)

| File | Stream | Phase | Changes |
|------|--------|-------|---------|
| `nightwatch/models.py` | A, B | 1, 3 | +RunContext, +AnalysisPassResult, extend ErrorAnalysisResult, extend RunReport |
| `nightwatch/analyzer.py` | A | 1, 2 | Extract _single_pass(), multi-pass logic, attempt_correction() |
| `nightwatch/runner.py` | A, B | 1, 2 | Thread RunContext, quality gate, knowledge write, pattern detection |
| `nightwatch/prompts.py` | A | 1 | seed_knowledge param in build_analysis_prompt() |
| `nightwatch/config.py` | A, B | 1, 2 | 6 new settings |
| `nightwatch/slack.py` | A, B | 3, 2 | Multi-pass metrics, pattern report section |
| `AGENTS.md` | C | trial | Amp Code config (if trial proceeds) |

**Total modified**: ~160 lines added/changed across 7 files

### New Directories (1)

| Directory | Stream | Purpose |
|-----------|--------|---------|
| `nightwatch/knowledge/` | B | Git-tracked solution documents |

---

## 7. Configuration Summary

All new features are **on by default** but fully configurable via environment variables:

```bash
# Stream A: Multi-Pass Analysis
NIGHTWATCH_MAX_PASSES=2                    # Max analysis passes per error (1=disable multi-pass)
NIGHTWATCH_RETRY_ON_LOW_CONFIDENCE=true    # Enable multi-pass retry

# Stream A: Quality Gate
NIGHTWATCH_VALIDATE_PR=true                # Enable PR validation before creation
NIGHTWATCH_ATTEMPT_CORRECTION=true         # Try to fix validation failures

# Stream B: Knowledge Compounding
NIGHTWATCH_KNOWLEDGE_ENABLED=true          # Enable knowledge store
NIGHTWATCH_KNOWLEDGE_DIR=nightwatch/knowledge  # Knowledge directory path
```

**Backward compatibility**: Setting all to `false`/`1` restores exact v0.1.0 behavior.

---

## 8. Cost & Performance Impact

| Metric | v0.1.0 (Current) | After All Streams | Delta |
|--------|-------------------|-------------------|-------|
| API calls per error (avg) | ~8 | ~10 | +25% (LOW retries only) |
| Tokens per error (avg) | ~12K | ~16K | +33% (retries + knowledge) |
| API calls per run (5 errors) | ~40 | ~50 | +25% |
| Run duration (5 errors) | ~3 min | ~4 min | +33% |
| Estimated cost per run (Sonnet) | ~$0.15 | ~$0.20 | +$0.05 |
| Knowledge search overhead | 0 | <100ms | Negligible |
| Pattern detection overhead | 0 | <50ms | Negligible |

**Cost guard**: Multi-pass only triggers on `confidence="low"` (~20% of analyses). Worst case adds ~$0.05/run. Quality gate validation uses GitHub API (no Claude cost). Knowledge search is local file glob (no API cost).

---

## 9. Risk Assessment

| Risk | Likelihood | Severity | Mitigation |
|------|-----------|----------|------------|
| Retry pass doesn't improve confidence | Medium | Low | `_select_best_pass()` picks best from all passes |
| RunContext grows too large for prompt | Low | Medium | Cap: 10 patterns + 15 files (hard limit in `to_prompt_section()`) |
| Knowledge search becomes slow | Low | Low | Under 100 docs for months; add indexing later if needed |
| Validation false positives block valid PRs | Medium | Medium | Conservative checks only; warnings don't block |
| Ruby syntax check too naive | High | Low | Safety net, not a linter — catches obvious breaks |
| Correction pass generates worse code | Low | Medium | Re-validate after correction; skip PR if still failing |
| Knowledge frontmatter parsing brittle | Low | Low | Use `pyyaml` safe_load; skip malformed files gracefully |
| Pattern detection too noisy | Medium | Low | Require 2+ errors for module cluster, 3+ for file hotspot |

---

## 10. Success Criteria

### Stream A (Multi-Pass + Quality Gate)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Low-confidence rate drops | ≥30% reduction | Compare `confidence="low"` rate across 10+ runs |
| Zero broken PRs | No draft PRs with syntax errors | `corrections_attempted` / `corrections_succeeded` in RunReport |
| Cross-error context visible | Later errors reference earlier discoveries | Log `RunContext.codebase_patterns` growth |
| No significant slowdown | <30% run time increase | `run_duration_seconds` in RunReport |

### Stream B (Knowledge Compounding)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Knowledge accumulates | 5+ solution docs per week | Count files in `nightwatch/knowledge/` |
| Knowledge improves analysis | Analyses citing prior knowledge show higher confidence | Compare confidence when knowledge matches found vs not |
| Patterns detected | 2+ patterns per week | `PatternReport.patterns` count in Slack reports |
| Duplicate analysis avoided | <10% repeat analyses for known errors | Knowledge search match rate |

### Stream C (Amp Code Trial)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Deep Mode adds value | Better on 1+ tasks | Subjective quality comparison |
| Within free tier | <$10/day average | Amp usage dashboard |
| No workflow regression | Velocity maintained | Subjective assessment |

---

## 11. What We Deliberately Don't Build

| Feature | Why Not |
|---------|---------|
| **OpenCode adoption** | TOOL-002 concluded no unique value for NightWatch (see evaluation) |
| **Full Ralph integration** | Bash wrapper around CLI; we adopt the pattern natively |
| **Cross-run persistent RunContext** | Knowledge store covers this; RunContext stays in-memory per-run |
| **Story decomposition** | Overkill for error analysis; revisit if scope expands |
| **Multi-agent parallel analysis** | COMPOUND-001 Phase 5; deferred until Phases 1-4 prove value |
| **compound-product self-improvement** | Blocked on licensing; not critical |
| **Vector memory / embeddings** | Grep-first knowledge search is sufficient at current scale |
| **Full Ruby parser for validation** | Basic regex catches obvious breaks; not building a linter |

---

## 12. Decision Required

- [ ] **Approve all 3 streams** (3 days) — Full implementation of multi-pass + knowledge + Amp trial
- [x] **Approve Streams A+B only** (2.5 days) — Skip Amp trial, focus on pipeline improvements
- [ ] **Approve Stream A only** (1 day) — Multi-pass + quality gate, defer knowledge compounding
- [ ] **Approve Stream A Phase 1 only** (4 hours) — Multi-pass analysis without quality gate
- [ ] **Defer all** — Current pipeline is sufficient; revisit after more production data

**Recommended**: Approve Streams A+B (2.5 days). These are the highest-ROI improvements and every day of delay is a day of lost compounding value from the knowledge store. The Amp trial can be done independently whenever there's slack time.
