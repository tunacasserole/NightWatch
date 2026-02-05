# Implementation Plan: Compound Engineering for NightWatch

**Proposal**: COMPOUND-002
**Date**: 2026-02-05
**Estimated Effort**: 4-6 days (with parallelization)

---

## Execution Order

```
Day 1-2:  Phase 1 — Knowledge Foundation (core)
Day 2-3:  Phase 2 + Phase 3 in parallel
Day 3-4:  Phase 4 — Pattern Detection
Day 4:    Integration testing, CI, docs
```

---

## Phase 1: Knowledge Foundation

### Task 1.1: Create directory structure
```
mkdir -p nightwatch/knowledge/errors
mkdir -p nightwatch/knowledge/patterns
touch nightwatch/knowledge/.gitkeep
touch nightwatch/knowledge/errors/.gitkeep
touch nightwatch/knowledge/patterns/.gitkeep
```

Add to `.gitignore`:
```gitignore
nightwatch/knowledge/errors/
nightwatch/knowledge/index.yml
```

### Task 1.2: Add `PriorAnalysis` model to `models.py`

Add after `CorrelatedPR`:

```python
@dataclass
class PriorAnalysis:
    """A prior analysis retrieved from the knowledge base."""
    error_class: str
    transaction: str
    root_cause: str
    fix_confidence: str
    has_fix: bool
    summary: str
    match_score: float
    source_file: str
    first_detected: str
```

Add two new fields to `RunReport`:

```python
@dataclass
class RunReport:
    # ... existing fields ...
    patterns: list = field(default_factory=list)
    ignore_suggestions: list = field(default_factory=list)
```

### Task 1.3: Add config settings to `config.py`

Add to `Settings`:

```python
nightwatch_knowledge_dir: str = "nightwatch/knowledge"
nightwatch_compound_enabled: bool = True
```

### Task 1.4: Create `nightwatch/knowledge.py`

Full module with these functions:

| Function | Lines (est.) | Purpose |
|----------|-------------|---------|
| `search_prior_knowledge()` | 40 | Index-first search, score, read top 3 |
| `compound_result()` | 45 | Write ErrorAnalysisResult as frontmatter+markdown doc |
| `rebuild_index()` | 35 | Scan errors/ + patterns/, write index.yml |
| `update_result_metadata()` | 20 | Back-fill issue_number/pr_number into existing doc |
| `_match_score()` | 15 | Scoring: error_class=0.5, transaction=0.3, tags=0.1 each |
| `_extract_tags()` | 12 | Split error_class on `::`, transaction on `/`, lowercase |
| `_parse_frontmatter()` | 10 | Split `---` blocks, yaml.safe_load |
| `_render_frontmatter()` | 5 | yaml.dump between `---` markers |
| `_slugify()` | 5 | Lowercase, replace non-alnum with hyphens |

**Total**: ~190 lines

### Task 1.5: Modify `prompts.py` — add `prior_analyses` parameter

Change `build_analysis_prompt()` signature:

```python
def build_analysis_prompt(
    error_class: str,
    transaction: str,
    message: str,
    occurrences: int,
    trace_summary: str,
    prior_analyses: list | None = None,  # NEW
) -> str:
```

Append prior knowledge section when `prior_analyses` is not empty. Include "verify independently" instruction.

### Task 1.6: Modify `analyzer.py` — accept and pass `prior_analyses`

Change `analyze_error()` signature:

```python
def analyze_error(
    error: ErrorGroup,
    traces: TraceData,
    github_client: Any,
    newrelic_client: Any,
    prior_analyses: list | None = None,  # NEW
) -> ErrorAnalysisResult:
```

Pass `prior_analyses` through to `build_analysis_prompt()` when building `initial_message`.

### Task 1.7: Modify `runner.py` — add Steps 0 and 12

**Step 0** (before Step 2): Search knowledge base for each error.

```python
from nightwatch.knowledge import search_prior_knowledge, compound_result, rebuild_index, update_result_metadata

# Between rank_errors() and fetch_traces():
prior_knowledge_map: dict[int, list] = {}
if settings.nightwatch_compound_enabled:
    for error in top_errors:
        prior = search_prior_knowledge(error)
        if prior:
            prior_knowledge_map[id(error)] = prior
```

**Step 4** (modify): Pass `prior_analyses` to `analyze_error()`.

**Step 12** (after Step 11): Compound learnings.

```python
if not dry_run and settings.nightwatch_compound_enabled:
    logger.info("Persisting analysis results to knowledge base...")
    for result in analyses:
        compound_result(result)
    for issue_result in issues_created:
        update_result_metadata(
            error_class=issue_result.error.error_class,
            transaction=issue_result.error.transaction,
            issue_number=issue_result.issue_number,
        )
    if pr_result and best_fix:
        result_for_pr, _ = best_fix
        update_result_metadata(
            error_class=result_for_pr.error.error_class,
            transaction=result_for_pr.error.transaction,
            pr_number=pr_result.pr_number,
        )
    rebuild_index()
```

### Task 1.8: Write `tests/test_knowledge.py`

| Test | What It Validates |
|------|-------------------|
| `test_extract_tags_from_error_class` | `"ActiveRecord::RecordNotFound"` → `{"activerecord", "recordnotfound"}` |
| `test_extract_tags_from_transaction` | `"Controller/products/show"` → `{"products", "show"}` |
| `test_match_score_exact_class` | Same error_class → score ≥ 0.5 |
| `test_match_score_exact_transaction` | Same transaction → score ≥ 0.3 |
| `test_match_score_no_match` | Different everything → score 0.0 |
| `test_parse_frontmatter_valid` | Standard `---\nkey: value\n---\nbody` |
| `test_parse_frontmatter_no_frontmatter` | Plain text returns empty dict + full text |
| `test_render_frontmatter` | Dict → `---\n{yaml}\n---\n` |
| `test_slugify` | `"ActiveRecord::RecordNotFound"` → `"activerecord-recordnotfound"` |
| `test_compound_result_creates_file` | Mock ErrorAnalysisResult → file exists with correct frontmatter |
| `test_rebuild_index` | Create 3 fixture docs → index.yml has 3 solutions |
| `test_search_prior_knowledge_finds_match` | Create fixture doc, search with matching error → returns result |
| `test_search_prior_knowledge_no_match` | Search with unrelated error → empty list |
| `test_update_result_metadata` | Create doc, update with issue_number → frontmatter updated |

### Task 1.9: Run lint + tests

```bash
uv run ruff check nightwatch/ tests/
uv run ruff format nightwatch/ tests/
uv run pytest tests/ -v
```

---

## Phase 2: Research Enhancement

### Task 2.1: Create `nightwatch/research.py`

| Function | Lines (est.) | Purpose |
|----------|-------------|---------|
| `research_error()` | 25 | Orchestrate all research steps |
| `_infer_files_from_transaction()` | 25 | Rails transaction → file paths |
| `_infer_files_from_traces()` | 20 | Stack trace frames → file paths |
| `_pre_fetch_files()` | 20 | Read first 100 lines from GitHub per file |
| `ResearchContext` dataclass | 10 | Container for all pre-gathered context |

**Total**: ~100 lines

#### Transaction-to-File Mapping Rules

```python
# "Controller/products/show" → "app/controllers/products_controller.rb"
# "Controller/api/v3/reviews/create" → "app/controllers/api/v3/reviews_controller.rb"
# "Sidekiq/ImportJob" → "app/jobs/import_job.rb"
# "OtherTransaction/Rake/db:migrate" → skip (no meaningful file)

# Also infer related model:
# "Controller/products/show" → "app/models/product.rb" (singularize, remove trailing 's')
```

### Task 2.2: Modify `prompts.py` — add `research_context` parameter

Extend `build_analysis_prompt()` with a second new parameter. Add sections for pre-fetched files and correlated PRs.

### Task 2.3: Modify `analyzer.py` — accept `research_context`

Add parameter, pass through to prompt builder.

### Task 2.4: Modify `runner.py` — add Step 3.5

Between trace fetching and analysis, run `research_error()` for each error. Pass the result through to `analyze_error()`.

Note: Move `correlated_prs = fetch_recent_merged_prs(gh.repo, hours=24)` earlier (before Step 4 instead of Step 8) so it's available for research.

### Task 2.5: Write `tests/test_research.py`

| Test | What It Validates |
|------|-------------------|
| `test_infer_files_controller` | `"Controller/products/show"` → includes `products_controller.rb` |
| `test_infer_files_api` | `"Controller/api/v3/reviews/create"` → includes `api/v3/reviews_controller.rb` |
| `test_infer_files_job` | `"Sidekiq/ImportJob"` → includes `import_job.rb` |
| `test_infer_files_model` | Controller transaction → also infers model file |
| `test_infer_files_from_traces` | Mock trace with stackTrace frames → extracts app paths |
| `test_pre_fetch_files_caps_at_5` | 10 files input → only 5 fetched |
| `test_pre_fetch_files_skips_missing` | 2 valid + 1 missing → dict has 2 entries |
| `test_research_error_integration` | Full mock → ResearchContext with all fields populated |

### Task 2.6: Run lint + tests

---

## Phase 3: Agent Configuration (parallel with Phase 2)

### Task 3.1: Create `nightwatch/agents/` directory

```bash
mkdir -p nightwatch/agents
```

### Task 3.2: Create `nightwatch/agents.py`

| Function | Lines (est.) | Purpose |
|----------|-------------|---------|
| `AgentConfig` dataclass | 15 | name, system_prompt, model, thinking_budget, max_tokens, max_iterations, tools, description |
| `load_agent()` | 30 | Load from `agents/{name}.md`, parse frontmatter, fallback to default |
| `list_agents()` | 8 | Glob `agents/*.md`, return names |
| `_default_agent()` | 5 | Return AgentConfig with SYSTEM_PROMPT from prompts.py |

**Total**: ~60 lines

### Task 3.3: Create `nightwatch/agents/base-analyzer.md`

Migrate current `SYSTEM_PROMPT` from `prompts.py` into this file with YAML frontmatter:

```yaml
---
name: base-analyzer
description: "Core NightWatch error analysis agent for Ruby on Rails applications"
model: claude-sonnet-4-5-20250929
thinking_budget: 8000
max_tokens: 16384
max_iterations: 15
tools:
  - read_file
  - search_code
  - list_directory
  - get_error_traces
---
```

Body = current `SYSTEM_PROMPT` text from `prompts.py`.

### Task 3.4: Create `nightwatch/agents/ruby-rails.md` (optional enhancement)

Extended prompt with Rails-specific investigation patterns, common ActiveRecord errors, concern/service/job patterns.

### Task 3.5: Modify `analyzer.py` — use agent config

Add `agent_name` parameter to `analyze_error()`. Load agent config. Use `agent.system_prompt` instead of `SYSTEM_PROMPT`, `agent.thinking_budget`, `agent.max_iterations`, `agent.model`.

### Task 3.6: Modify `__main__.py` — add `--agent` flag

```python
run_parser.add_argument(
    "--agent", default="base-analyzer",
    help="Agent definition to use (e.g. 'ruby-rails')",
)
```

Pass through `_run()` → `runner.run()` → `analyze_error()`.

### Task 3.7: Modify `runner.py` — accept `agent_name` parameter

```python
def run(..., agent_name: str = "base-analyzer") -> RunReport:
```

### Task 3.8: Write `tests/test_agents.py`

| Test | What It Validates |
|------|-------------------|
| `test_load_agent_from_file` | Create fixture .md → AgentConfig fields match frontmatter |
| `test_load_agent_missing_file_uses_default` | Non-existent name → falls back to SYSTEM_PROMPT |
| `test_load_agent_partial_frontmatter` | Only `name:` specified → other fields use defaults |
| `test_load_agent_validates_name` | Frontmatter `name` must match filename |
| `test_list_agents` | Create 3 fixture files → list returns 3 names |
| `test_base_analyzer_exists` | `nightwatch/agents/base-analyzer.md` exists and loads |

### Task 3.9: Run lint + tests

---

## Phase 4: Pattern Detection

### Task 4.1: Create `nightwatch/patterns.py`

| Function | Lines (est.) | Purpose |
|----------|-------------|---------|
| `DetectedPattern` dataclass | 12 | title, description, error_classes, modules, occurrences, suggestion, pattern_type |
| `IgnoreSuggestion` dataclass | 8 | pattern, match, reason, evidence |
| `detect_patterns()` | 60 | Core detection: same root_cause, recurring error_class, tag clustering, transient detection |
| `suggest_ignore_updates()` | 40 | Find recurring unfixable errors, check against current ignores |
| `write_pattern_doc()` | 25 | Write/update pattern Markdown file |
| `_cluster_by_root_cause()` | 20 | Group analyses by root_cause similarity |
| `_find_recurring_in_knowledge()` | 25 | Search knowledge index for error_class appearing 3+ times |
| `_is_transient_error()` | 10 | Check error_class against known transient indicators |

**Total**: ~200 lines

#### Pattern Detection Strategies

1. **Same root_cause in current run**: If 2+ errors in this run share similar root_cause text (fuzzy match), flag as systemic
2. **Recurring error_class**: If an error_class appears in the knowledge base 3+ times with `has_fix=false`, flag as recurring unfixable
3. **Tag clustering**: If 3+ errors share 2+ tags, flag as related cluster
4. **Transient noise**: If error_class contains timeout/connection/SSL indicators and has_fix is always false, suggest ignore addition

### Task 4.2: Modify `runner.py` — add Step 13

After Step 12 (compound), run pattern detection. Store results on `report`.

### Task 4.3: Modify `slack.py` — add pattern blocks

Add pattern section and ignore suggestion section to `_build_report_blocks()`. Only show when `report.patterns` or `report.ignore_suggestions` are non-empty.

### Task 4.4: Write `tests/test_patterns.py`

| Test | What It Validates |
|------|-------------------|
| `test_detect_same_root_cause` | 2 errors with same root_cause → DetectedPattern |
| `test_detect_recurring_error_class` | 3+ knowledge docs for same class → pattern detected |
| `test_no_patterns_when_all_unique` | All different errors → empty list |
| `test_suggest_ignore_transient` | Timeout error, 3 occurrences, no fix → IgnoreSuggestion |
| `test_suggest_ignore_skips_already_ignored` | Error already in ignore.yml → no suggestion |
| `test_write_pattern_doc` | Write pattern → file exists with correct frontmatter |
| `test_is_transient_error` | Known transient classes → True, others → False |

### Task 4.5: Run lint + tests

---

## Final Integration

### Task F.1: Full integration test

Create `tests/test_compound_integration.py`:

1. Set up fixture knowledge base with 3 existing docs
2. Create mock ErrorGroups that partially match existing docs
3. Run through the full pipeline (Steps 0 → 12 → 13) with mocked clients
4. Verify: prior knowledge was found, research context was built, analyses were compounded, patterns were detected

### Task F.2: Update documentation

Run the doc-action or manually update `docs/architecture.md` to include:
- New Steps 0, 3.5, 12, 13 in pipeline description
- Knowledge base directory structure
- Agent configuration system
- New CLI flags (`--agent`)
- New config vars (`NIGHTWATCH_COMPOUND_ENABLED`, `NIGHTWATCH_KNOWLEDGE_DIR`)

### Task F.3: CI validation

Verify all tests pass:
```bash
uv run ruff check nightwatch/ tests/
uv run ruff format nightwatch/ tests/
uv run pytest tests/ -v --tb=short
```

### Task F.4: Commit strategy

One commit per phase for clean history:

```
git add nightwatch/knowledge/ nightwatch/knowledge.py nightwatch/models.py nightwatch/config.py nightwatch/runner.py nightwatch/analyzer.py nightwatch/prompts.py tests/test_knowledge.py
git commit -m "feat: Phase 1 — knowledge foundation (compound engineering)

Add persistent knowledge base that stores analysis results as searchable
YAML-frontmatter Markdown documents. Prior analyses are injected into
Claude's prompt context to reduce duplicate work and improve accuracy.

New: nightwatch/knowledge.py, nightwatch/knowledge/ directory
Modified: runner.py (Steps 0, 12), analyzer.py, prompts.py, models.py, config.py"

git add nightwatch/research.py tests/test_research.py nightwatch/runner.py nightwatch/analyzer.py nightwatch/prompts.py
git commit -m "feat: Phase 2 — pre-analysis research enhancement

Gather context before Claude's main analysis loop: infer likely files
from transaction names and stack traces, pre-fetch source code, collect
correlated PRs. Reduces avg iterations from ~8 to ~5 per error.

New: nightwatch/research.py"

git add nightwatch/agents.py nightwatch/agents/ tests/test_agents.py nightwatch/__main__.py nightwatch/runner.py nightwatch/analyzer.py
git commit -m "feat: Phase 3 — configurable agent definitions

Break monolithic system prompt into Markdown files with YAML frontmatter.
Enables language/framework-specific analysis without code changes.
Add --agent CLI flag.

New: nightwatch/agents.py, nightwatch/agents/*.md"

git add nightwatch/patterns.py tests/test_patterns.py nightwatch/runner.py nightwatch/slack.py nightwatch/models.py
git commit -m "feat: Phase 4 — cross-error pattern detection

Detect systemic patterns across errors within and across runs.
Surface patterns in Slack reports. Auto-suggest ignore.yml additions
for recurring transient errors.

New: nightwatch/patterns.py"
```

---

## Checklist

### Phase 1 — Knowledge Foundation
- [ ] Create `nightwatch/knowledge/` directory tree with .gitkeep files
- [ ] Add `nightwatch/knowledge/errors/` to `.gitignore`
- [ ] Add `PriorAnalysis` dataclass to `models.py`
- [ ] Add `patterns` + `ignore_suggestions` fields to `RunReport`
- [ ] Add `nightwatch_knowledge_dir` + `nightwatch_compound_enabled` to `config.py`
- [ ] Create `nightwatch/knowledge.py` with full API
- [ ] Modify `prompts.py`: add `prior_analyses` param to `build_analysis_prompt()`
- [ ] Modify `analyzer.py`: add `prior_analyses` param to `analyze_error()`
- [ ] Modify `runner.py`: add Step 0 (search knowledge) + Step 12 (compound)
- [ ] Create `tests/test_knowledge.py` (14 tests)
- [ ] `uv run ruff check && uv run pytest` — all green

### Phase 2 — Research Enhancement
- [ ] Create `nightwatch/research.py` with `ResearchContext` + research functions
- [ ] Modify `prompts.py`: add `research_context` param
- [ ] Modify `analyzer.py`: add `research_context` param
- [ ] Modify `runner.py`: add Step 3.5, move correlated_prs fetch earlier
- [ ] Create `tests/test_research.py` (8 tests)
- [ ] `uv run ruff check && uv run pytest` — all green

### Phase 3 — Agent Configuration
- [ ] Create `nightwatch/agents/` directory
- [ ] Create `nightwatch/agents.py` with `AgentConfig` + `load_agent()`
- [ ] Create `nightwatch/agents/base-analyzer.md` (migrated from SYSTEM_PROMPT)
- [ ] Optionally create `nightwatch/agents/ruby-rails.md`
- [ ] Modify `analyzer.py`: use agent config for model/prompt/budget
- [ ] Modify `__main__.py`: add `--agent` flag
- [ ] Modify `runner.py`: accept and pass `agent_name`
- [ ] Create `tests/test_agents.py` (6 tests)
- [ ] `uv run ruff check && uv run pytest` — all green

### Phase 4 — Pattern Detection
- [ ] Create `nightwatch/patterns.py` with detection + suggestion logic
- [ ] Modify `runner.py`: add Step 13
- [ ] Modify `slack.py`: add pattern + ignore suggestion blocks to report
- [ ] Create `tests/test_patterns.py` (7 tests)
- [ ] `uv run ruff check && uv run pytest` — all green

### Final
- [ ] Create `tests/test_compound_integration.py`
- [ ] Update docs (architecture.md, configuration.md)
- [ ] Full CI pass
- [ ] Commit per phase with descriptive messages
