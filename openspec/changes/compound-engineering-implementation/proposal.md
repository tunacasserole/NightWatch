# OpenSpec Proposal: Compound Engineering Implementation

**ID**: COMPOUND-002
**Status**: Completed (Phase 1 implemented; Phases 2-4 planned)
**Approved By**: AI Review (Claude Opus 4.6)
**Approved Date**: 2025-02-05
**Completed Date**: 2025-02-05
**Author**: Claude (AI Assistant)
**Date**: 2025-02-05
**Supersedes**: COMPOUND-001 (Pattern Evaluation — merged into this document)
**See Also**: [CP-001](../../compound-product-integration/proposal.md) (Product integration layer)
**Scope**: 4 new modules, 3 modified modules, 1 new directory tree, 2 new CLI flags

---

## 1. Problem Statement

NightWatch analyzes production errors nightly. Each run is stateless — analysis results are consumed (GitHub issues, Slack messages) then discarded. This means:

1. **Repeated work**: If the same `Net::ReadTimeout in ProductsController` appears 5 nights in a row, Claude re-investigates from scratch each time — burning ~15K tokens per duplicate analysis
2. **No pattern detection**: Systemic issues (e.g., "all external API calls lack circuit breakers") are never surfaced because each error is analyzed in isolation
3. **No learning feedback loop**: When a NightWatch PR gets merged (fix worked) or closed (fix was wrong), that outcome is never fed back into future analysis
4. **Wasted iterations**: Claude spends 3-5 of its 15 iterations just finding relevant files — file paths it already discovered in previous runs
5. **Monolithic prompt**: The system prompt in `prompts.py` is one static string. Adding language/framework support or tuning analysis behavior requires code changes

## 2. Proposal

Implement 4 phases of compound engineering patterns extracted from [EveryInc/compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin) (MIT licensed). Each phase is independently deployable and valuable.

### What Changes

| Phase | New Files | Modified Files | New Dependencies |
|-------|-----------|----------------|------------------|
| 1. Knowledge Foundation | `nightwatch/knowledge.py` | `runner.py`, `analyzer.py`, `prompts.py`, `models.py` | None |
| 2. Research Enhancement | `nightwatch/research.py` | `runner.py`, `analyzer.py`, `prompts.py` | None |
| 3. Agent Configuration | `nightwatch/agents.py`, `nightwatch/agents/*.md` | `analyzer.py`, `prompts.py` | None (`pyyaml` already installed) |
| 4. Pattern Detection | `nightwatch/patterns.py` | `runner.py`, `slack.py`, `__main__.py` | None |

**Zero new dependencies.** All implementations use existing `pyyaml`, `pydantic`, and stdlib.

### What Doesn't Change

- The 11-step pipeline in `runner.py` stays intact (we add steps 12-13, don't modify existing steps)
- `newrelic.py` — untouched
- `github.py` — untouched
- `correlation.py` — untouched (but consumed by Phase 2)
- `config.py` — minor additions (2 new optional settings)
- `slack.py` — minor additions (Phase 4 adds pattern section to report blocks)

---

## 3. Architecture Overview

```
                          ┌──────────────────────┐
                          │    Knowledge Base     │
                          │  nightwatch/knowledge/│
                          │  ├── errors/          │
                          │  ├── patterns/        │
                          │  └── index.yml        │
                          └──────┬──────┬─────────┘
                                 │      │
                          read   │      │ write
                          before │      │ after
                                 │      │
┌─────────┐  ┌──────────┐  ┌────▼──────▼────┐  ┌──────────┐  ┌─────────┐
│ NewRelic │→│  Rank &   │→│   Analyze       │→│  GitHub   │→│  Slack   │
│  fetch   │ │  filter   │ │  (Claude loop)  │ │  issues   │ │  report  │
└─────────┘  └──────────┘  └────────┬────────┘  └──────────┘  └─────────┘
                                     │
                            ┌────────▼────────┐
                            │  Phase 2:       │
                            │  Research       │
                            │  (pre-analysis) │
                            └─────────────────┘

Existing pipeline (Steps 1-11):  unchanged
New Steps:
  Step 0:   Load knowledge index           (Phase 1)
  Step 3.5: Pre-analysis research per error (Phase 2)
  Step 12:  Compound — persist learnings    (Phase 1)
  Step 13:  Detect patterns                 (Phase 4)
```

---

## 4. Phase 1: Knowledge Foundation

**Goal**: NightWatch remembers what it learns. Each run persists analysis results as searchable documents. Future runs search them before analyzing.

**Estimated effort**: 2-3 days

### 4.1 New Data Models (`models.py` additions)

```python
# Add to nightwatch/models.py

@dataclass
class PriorAnalysis:
    """A prior analysis from the knowledge base, returned by search."""
    error_class: str
    transaction: str
    root_cause: str
    fix_confidence: str
    has_fix: bool
    summary: str          # First 500 chars of analysis body
    match_score: float    # 0.0 - 1.0 relevance to current error
    source_file: str      # Path to knowledge doc
    first_detected: str   # ISO date
```

### 4.2 New Module: `nightwatch/knowledge.py`

**Purpose**: Read/write knowledge documents with YAML frontmatter. Search using index-first (grep-first) strategy.

**Public API**:

```python
def search_prior_knowledge(error: ErrorGroup, max_results: int = 3) -> list[PriorAnalysis]:
    """Search knowledge base for prior analyses of similar errors.

    Strategy (from compound-engineering 'learnings-researcher'):
    1. Load index.yml (small, structured)
    2. Score each entry against error (error_class match = 0.5, transaction match = 0.3, tag overlap = 0.1 each)
    3. Read only top N matching full documents
    4. Return structured PriorAnalysis objects
    """

def compound_result(result: ErrorAnalysisResult) -> Path:
    """Persist an ErrorAnalysisResult as a knowledge document.

    Creates: nightwatch/knowledge/errors/YYYY-MM-DD_<slug>.md
    With YAML frontmatter: error_class, transaction, root_cause, fix_confidence,
    has_fix, tags, occurrences, iterations_used, tokens_used, pr_number, issue_number
    Body: title, root cause section, analysis section, next steps, file changes
    """

def rebuild_index() -> None:
    """Rebuild nightwatch/knowledge/index.yml from all documents.

    Scans errors/ and patterns/ directories.
    Writes structured YAML with solutions[] and patterns[] arrays.
    """

def update_result_metadata(
    error_class: str, transaction: str,
    issue_number: int | None = None, pr_number: int | None = None
) -> None:
    """Update a knowledge doc's frontmatter with issue/PR numbers after creation."""
```

**Internal functions**:

```python
def _match_score(error: ErrorGroup, solution: dict) -> float:
    """Score relevance: error_class exact=0.5, transaction exact=0.3, tag overlap=0.1 each."""

def _extract_tags(error: ErrorGroup) -> set[str]:
    """Extract searchable tags from error class and transaction name.
    Split on ::, /, #. Lowercase. Filter noise words (Controller, Action)."""

def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split '---\\n...---\\n' YAML from Markdown body. Uses yaml.safe_load."""

def _render_frontmatter(data: dict) -> str:
    """Render dict as '---\\n{yaml}---\\n' block."""

def _slugify(text: str) -> str:
    """Lowercase, replace non-alnum with hyphens, truncate to 60 chars."""
```

### 4.3 Knowledge Document Format

File: `nightwatch/knowledge/errors/2026-02-05_activerecord-recordnotfound_controller-orders-update.md`

```yaml
---
error_class: "ActiveRecord::RecordNotFound"
transaction: "Controller/orders/update"
message: "Couldn't find Order with 'id'=12345"
occurrences: 87
root_cause: "Race condition between order deletion and status update"
fix_confidence: high
has_fix: true
issue_number: null
pr_number: null
tags:
  - activerecord
  - recordnotfound
  - orders
  - update
first_detected: "2026-02-05"
run_id: "2026-02-05T06:00:00+00:00"
iterations_used: 6
tokens_used: 12340
---

# ActiveRecord::RecordNotFound in orders/update

## Root Cause

Race condition between order deletion and status update...

## Analysis

[Full analysis.reasoning text]

## Next Steps

- Add nil guard on Order.find
- Consider using find_by with explicit nil handling

## File Changes

- `app/controllers/orders_controller.rb`: modify — Replace find with find_by
```

### 4.4 Knowledge Index Format

File: `nightwatch/knowledge/index.yml`

```yaml
last_updated: "2026-02-05T06:15:00+00:00"
total_solutions: 47
total_patterns: 3

solutions:
  - file: "errors/2026-02-05_activerecord-recordnotfound_controller-orders-update.md"
    error_class: "ActiveRecord::RecordNotFound"
    transaction: "Controller/orders/update"
    fix_confidence: "high"
    has_fix: true
    tags: [activerecord, recordnotfound, orders, update]

  - file: "errors/2026-02-05_net-readtimeout_controller-products-show.md"
    error_class: "Net::ReadTimeout"
    transaction: "Controller/products/show"
    fix_confidence: "medium"
    has_fix: false
    tags: [net, readtimeout, products, show]
```

### 4.5 Runner Integration

**Modifications to `runner.py`**:

```python
# At top of run(), before Step 2:
# Step 0: Load knowledge base
from nightwatch.knowledge import search_prior_knowledge, compound_result, rebuild_index, update_result_metadata

# Between Step 3 (traces) and Step 4 (analyze), build prior knowledge map:
prior_knowledge_map: dict[int, list[PriorAnalysis]] = {}
for error in top_errors:
    prior = search_prior_knowledge(error)
    if prior:
        prior_knowledge_map[id(error)] = prior
        logger.info(f"  Found {len(prior)} prior analyses for {error.error_class}")

# Step 4: pass prior_analyses to analyze_error()
result = analyze_error(
    error=error,
    traces=traces_map[id(error)],
    github_client=gh,
    newrelic_client=nr,
    prior_analyses=prior_knowledge_map.get(id(error)),  # NEW PARAM
)

# After Step 11, add Step 12:
# Step 12: Compound — persist learnings
if not dry_run:
    logger.info("Persisting analysis results to knowledge base...")
    for result in analyses:
        compound_result(result)
    # Back-fill issue/PR numbers
    for issue_result in issues_created:
        update_result_metadata(
            error_class=issue_result.error.error_class,
            transaction=issue_result.error.transaction,
            issue_number=issue_result.issue_number,
        )
    if pr_result:
        best, _ = best_fix
        update_result_metadata(
            error_class=best.error.error_class,
            transaction=best.error.transaction,
            pr_number=pr_result.pr_number,
        )
    rebuild_index()
```

### 4.6 Analyzer Integration

**Modifications to `analyzer.py`**:

Add `prior_analyses` parameter to `analyze_error()`:

```python
def analyze_error(
    error: ErrorGroup,
    traces: TraceData,
    github_client: Any,
    newrelic_client: Any,
    prior_analyses: list[PriorAnalysis] | None = None,  # NEW
) -> ErrorAnalysisResult:
```

Pass `prior_analyses` through to `build_analysis_prompt()`.

### 4.7 Prompts Integration

**Modifications to `prompts.py`**:

Add `prior_analyses` parameter to `build_analysis_prompt()`:

```python
def build_analysis_prompt(
    error_class: str,
    transaction: str,
    message: str,
    occurrences: int,
    trace_summary: str,
    prior_analyses: list | None = None,  # NEW
) -> str:
    prompt = f"""Analyze this production error and propose a fix:
    ...existing prompt text...
    """

    if prior_analyses:
        prompt += "\n\n## Prior Knowledge\n\n"
        prompt += (
            "NightWatch has analyzed similar errors before. "
            "Use this as context but verify independently — "
            "the root cause may differ this time.\n\n"
        )
        for i, prior in enumerate(prior_analyses, 1):
            prompt += f"### Prior Analysis #{i} (match: {prior.match_score:.0%})\n"
            prompt += f"- **Error**: `{prior.error_class}` in `{prior.transaction}`\n"
            prompt += f"- **Root cause**: {prior.root_cause}\n"
            prompt += f"- **Confidence**: {prior.fix_confidence}\n"
            prompt += f"- **Had fix**: {'Yes' if prior.has_fix else 'No'}\n"
            prompt += f"- **Summary**: {prior.summary}\n\n"

    return prompt
```

### 4.8 Directory Structure

```
nightwatch/
├── knowledge/                    # NEW — git-tracked
│   ├── .gitkeep
│   ├── index.yml                 # Auto-generated index
│   ├── errors/                   # Per-error solution docs
│   │   └── .gitkeep
│   └── patterns/                 # Cross-error pattern docs (Phase 4)
│       └── .gitkeep
├── knowledge.py                  # NEW — knowledge read/write module
└── ... (existing files unchanged)
```

### 4.9 Config Additions

```python
# Add to Settings in config.py:
nightwatch_knowledge_dir: str = "nightwatch/knowledge"
nightwatch_compound_enabled: bool = True  # Master switch to disable knowledge system
```

---

## 5. Phase 2: Research Enhancement

**Goal**: Before Claude's main analysis loop, gather context to reduce iterations and token usage.

**Estimated effort**: 1-2 days

### 5.1 New Module: `nightwatch/research.py`

**Purpose**: Pre-analysis research that gathers context Claude would otherwise spend iterations discovering.

**Public API**:

```python
@dataclass
class ResearchContext:
    """Pre-gathered context injected into analysis prompt."""
    prior_analyses: list[PriorAnalysis]   # From Phase 1 knowledge base
    likely_files: list[str]               # Inferred from transaction name + traces
    correlated_prs: list[CorrelatedPR]    # From existing correlation.py
    file_previews: dict[str, str]         # Pre-fetched file snippets (first 100 lines)

def research_error(
    error: ErrorGroup,
    traces: TraceData,
    github_client: Any,
    correlated_prs: list[CorrelatedPR],
    prior_analyses: list[PriorAnalysis] | None = None,
) -> ResearchContext:
    """Gather all available context before the main analysis loop.

    Steps:
    1. Collect prior analyses (passed in from Phase 1)
    2. Infer likely relevant files from transaction name + stack traces
    3. Pre-fetch file previews (first 100 lines of each likely file)
    4. Collect correlated PRs (passed in from existing correlation system)
    """
```

**Internal functions**:

```python
def _infer_files_from_transaction(transaction: str) -> list[str]:
    """Extract file paths from Rails transaction name.

    "Controller/products/show" -> [
        "app/controllers/products_controller.rb",
        "app/models/product.rb",
    ]
    "Sidekiq/ImportJob" -> [
        "app/jobs/import_job.rb",
    ]
    """

def _infer_files_from_traces(traces: TraceData) -> list[str]:
    """Extract file paths from stack trace frames.

    Looks at error_traces[].stackTrace or error_traces[].error.stack_trace.
    Extracts app-relative paths (ignores gem paths).
    Returns top 5 unique paths.
    """

def _pre_fetch_files(
    files: list[str], github_client: Any, max_lines: int = 100
) -> dict[str, str]:
    """Read the first max_lines of each file from GitHub.

    Returns {path: content} dict. Silently skips files that don't exist.
    Caps at 5 files to avoid excessive GitHub API calls.
    """
```

### 5.2 Prompts Integration

**Extend `build_analysis_prompt()`** with research context:

```python
def build_analysis_prompt(
    error_class: str,
    transaction: str,
    message: str,
    occurrences: int,
    trace_summary: str,
    prior_analyses: list | None = None,      # Phase 1
    research_context: ResearchContext | None = None,  # Phase 2 — NEW
) -> str:
    prompt = "...existing..."

    # Phase 1: prior knowledge (already added)

    # Phase 2: pre-fetched file context
    if research_context and research_context.file_previews:
        prompt += "\n\n## Pre-Fetched Source Files\n\n"
        prompt += (
            "These files were identified as likely relevant based on the "
            "transaction name and stack traces. You can read_file for full "
            "content or search_code for related files.\n\n"
        )
        for path, content in research_context.file_previews.items():
            prompt += f"### `{path}` (first 100 lines)\n```ruby\n{content}\n```\n\n"

    # Phase 2: correlated PRs
    if research_context and research_context.correlated_prs:
        prompt += "\n\n## Recently Merged PRs (Possible Cause)\n\n"
        for pr in research_context.correlated_prs[:3]:
            prompt += (
                f"- **PR #{pr.number}**: {pr.title} "
                f"(merged {pr.merged_at}, overlap: {pr.overlap_score:.0%})\n"
                f"  Changed: {', '.join(pr.changed_files[:5])}\n"
            )

    return prompt
```

### 5.3 Runner Integration

```python
# In runner.py, between trace fetching (Step 3) and analysis (Step 4):

# Step 3.5: Pre-analysis research
logger.info("Running pre-analysis research...")
research_map: dict[int, ResearchContext] = {}
for error in top_errors:
    related_prs = correlate_error_with_prs(error, correlated_prs)
    ctx = research_error(
        error=error,
        traces=traces_map[id(error)],
        github_client=gh,
        correlated_prs=related_prs,
        prior_analyses=prior_knowledge_map.get(id(error)),
    )
    research_map[id(error)] = ctx

# Step 4: Pass research_context to analyze_error()
result = analyze_error(
    error=error,
    traces=traces_map[id(error)],
    github_client=gh,
    newrelic_client=nr,
    prior_analyses=prior_knowledge_map.get(id(error)),
    research_context=research_map.get(id(error)),  # NEW
)
```

### 5.4 Expected Impact

| Metric | Before | After | Why |
|--------|--------|-------|-----|
| Avg iterations/error | ~8 | ~5 | Claude already has relevant files, skips discovery |
| Avg tokens/error | ~15K | ~11K | Fewer tool-use round trips |
| File-not-found tool errors | ~2/error | ~0.5/error | Pre-fetched files are validated |

---

## 6. Phase 3: Agent Configuration

**Goal**: Break the monolithic system prompt into configurable Markdown agent definition files. Enable language/framework-specific analysis without code changes.

**Estimated effort**: 1-2 days

### 6.1 New Module: `nightwatch/agents.py`

**Public API**:

```python
@dataclass
class AgentConfig:
    """Configuration for a NightWatch analysis agent."""
    name: str
    system_prompt: str
    model: str = "claude-sonnet-4-5-20250929"
    thinking_budget: int = 8000
    max_tokens: int = 16384
    max_iterations: int = 15
    tools: list[str] = field(default_factory=lambda: [
        "read_file", "search_code", "list_directory", "get_error_traces"
    ])
    description: str = ""

AGENTS_DIR = Path(__file__).parent / "agents"

def load_agent(name: str = "base-analyzer") -> AgentConfig:
    """Load agent from nightwatch/agents/{name}.md.

    File format: YAML frontmatter + Markdown body (= system prompt).
    Falls back to existing SYSTEM_PROMPT from prompts.py if file not found.
    """

def list_agents() -> list[str]:
    """List available agent names from agents/ directory."""
```

### 6.2 Agent Definition Files

**`nightwatch/agents/base-analyzer.md`**:

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

[Contents of current SYSTEM_PROMPT from prompts.py, migrated here]
```

**`nightwatch/agents/ruby-rails.md`** (optional, extends base):

```yaml
---
name: ruby-rails
description: "Specialized Ruby on Rails error analysis with framework-specific patterns"
model: claude-sonnet-4-5-20250929
thinking_budget: 10000
max_tokens: 16384
max_iterations: 15
tools:
  - read_file
  - search_code
  - list_directory
  - get_error_traces
---

You are NightWatch, an AI agent specialized in Ruby on Rails production errors.

[Enhanced prompt with Rails-specific investigation patterns, common error categories,
 ActiveRecord gotchas, controller/concern patterns, etc.]
```

### 6.3 Analyzer Integration

```python
# In analyzer.py, modify _call_claude_with_retry():

def analyze_error(
    error: ErrorGroup,
    traces: TraceData,
    github_client: Any,
    newrelic_client: Any,
    prior_analyses: list | None = None,
    research_context: Any = None,
    agent_name: str = "base-analyzer",  # NEW
) -> ErrorAnalysisResult:
    settings = get_settings()

    # Load agent config (Phase 3)
    from nightwatch.agents import load_agent
    agent = load_agent(agent_name)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    # Use agent config for model, iterations, etc.
    max_iterations = agent.max_iterations
    ...

# In _call_claude_with_retry, use agent.system_prompt instead of SYSTEM_PROMPT:
    response = client.messages.create(
        model=agent.model,
        max_tokens=agent.max_tokens,
        system=[{
            "type": "text",
            "text": agent.system_prompt,  # From agent file, not hardcoded
            "cache_control": {"type": "ephemeral"},
        }],
        tools=TOOLS,  # Still use TOOLS from prompts.py (tool schemas don't change)
        messages=messages,
        thinking={"type": "enabled", "budget_tokens": agent.thinking_budget},
    )
```

### 6.4 CLI Integration

```python
# In __main__.py, add --agent flag to run subcommand:
run_parser.add_argument(
    "--agent", default="base-analyzer",
    help="Agent definition to use (e.g. 'ruby-rails', 'python')",
)

# In runner.py, pass agent_name through:
def run(..., agent_name: str = "base-analyzer") -> RunReport:
```

### 6.5 Backward Compatibility

If `nightwatch/agents/base-analyzer.md` doesn't exist, `load_agent()` falls back to the inline `SYSTEM_PROMPT` from `prompts.py`. The existing prompt string stays in `prompts.py` as the default. No behavior change unless agent files are present.

---

## 7. Phase 4: Pattern Detection

**Goal**: Detect systemic patterns across errors within and across runs. Surface them in Slack reports. Auto-suggest ignore pattern updates.

**Estimated effort**: 2-3 days

### 7.1 New Module: `nightwatch/patterns.py`

**Public API**:

```python
@dataclass
class DetectedPattern:
    """A systemic pattern detected across multiple errors."""
    title: str
    description: str
    error_classes: list[str]    # Error classes that exhibit this pattern
    modules: list[str]          # Affected modules/transactions
    occurrences: int            # Total occurrences across matched errors
    suggestion: str             # Actionable recommendation
    pattern_type: str           # "recurring_error" | "systemic_issue" | "transient_noise"

@dataclass
class IgnoreSuggestion:
    """A suggested addition to ignore.yml."""
    pattern: str
    match: str                  # "contains" | "exact" | "prefix"
    reason: str
    evidence: str               # Why this should be ignored

def detect_patterns(
    analyses: list[ErrorAnalysisResult],
    knowledge_dir: str = "nightwatch/knowledge",
) -> list[DetectedPattern]:
    """Detect cross-error patterns in current run + historical knowledge.

    Pattern detection strategies:
    1. Same root_cause across multiple errors in this run
    2. Same error_class appearing in knowledge base 3+ times
    3. Cluster by tags — multiple errors sharing the same tag set
    4. All-transient: errors where no fix is possible (external service, network, etc.)
    """

def suggest_ignore_updates(
    analyses: list[ErrorAnalysisResult],
    knowledge_dir: str = "nightwatch/knowledge",
    current_ignores: list[dict] | None = None,
) -> list[IgnoreSuggestion]:
    """Suggest additions to ignore.yml based on recurring unfixable errors.

    Criteria:
    - Error appeared 3+ times across runs with has_fix=False
    - Error class contains known transient indicators (Timeout, Connection, SSL)
    - Error was analyzed but confidence was always "low"

    Does NOT auto-modify ignore.yml — returns suggestions for human review.
    """

def write_pattern_doc(pattern: DetectedPattern, knowledge_dir: str) -> Path:
    """Persist a detected pattern as a knowledge document.

    Creates/updates: nightwatch/knowledge/patterns/<slug>.md
    """
```

### 7.2 Runner Integration

```python
# After Step 12 (compound), add Step 13:

# Step 13: Detect patterns
from nightwatch.patterns import detect_patterns, suggest_ignore_updates, write_pattern_doc

patterns = detect_patterns(analyses)
if patterns:
    logger.info(f"Detected {len(patterns)} cross-error patterns")
    for p in patterns:
        write_pattern_doc(p)
        logger.info(f"  Pattern: {p.title} ({p.occurrences} occurrences)")

ignore_suggestions = suggest_ignore_updates(
    analyses, current_ignores=ignore_patterns
)
if ignore_suggestions:
    logger.info(f"  {len(ignore_suggestions)} ignore suggestions generated")

report.patterns = patterns                  # NEW field on RunReport
report.ignore_suggestions = ignore_suggestions  # NEW field on RunReport
```

### 7.3 Model Additions

```python
# Add to RunReport in models.py:
@dataclass
class RunReport:
    ...
    patterns: list[DetectedPattern] = field(default_factory=list)           # NEW
    ignore_suggestions: list[IgnoreSuggestion] = field(default_factory=list) # NEW
```

### 7.4 Slack Integration

**Add pattern section to `_build_report_blocks()` in `slack.py`**:

```python
# After the analysis blocks, before the context footer:
if report.patterns:
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "*:mag: Detected Patterns*",
        },
    })
    for p in report.patterns[:3]:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{p.title}*\n"
                    f"{p.description}\n"
                    f"_Suggestion: {p.suggestion}_"
                ),
            },
        })

if report.ignore_suggestions:
    suggestions_text = "\n".join(
        f"• `{s.pattern}` — {s.reason}" for s in report.ignore_suggestions[:3]
    )
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*:mute: Suggested Ignore Additions*\n{suggestions_text}",
        },
    })
```

---

## 8. File Change Matrix

### New Files (7)

| File | Phase | Lines (est.) | Purpose |
|------|-------|-------------|---------|
| `nightwatch/knowledge.py` | 1 | ~250 | Knowledge base read/write/search |
| `nightwatch/research.py` | 2 | ~120 | Pre-analysis research context gathering |
| `nightwatch/agents.py` | 3 | ~80 | Agent config loader from Markdown files |
| `nightwatch/agents/base-analyzer.md` | 3 | ~60 | Default agent (migrated from `prompts.py`) |
| `nightwatch/agents/ruby-rails.md` | 3 | ~80 | Rails-specific enhanced agent (optional) |
| `nightwatch/patterns.py` | 4 | ~200 | Pattern detection and ignore suggestions |
| `nightwatch/knowledge/` (directory tree) | 1 | — | Knowledge storage with .gitkeep files |

### Modified Files (7)

| File | Phase | Changes |
|------|-------|---------|
| `nightwatch/models.py` | 1, 4 | Add `PriorAnalysis` dataclass, add `patterns`/`ignore_suggestions` to `RunReport` |
| `nightwatch/runner.py` | 1, 2, 4 | Add Steps 0, 3.5, 12, 13; pass new params through pipeline |
| `nightwatch/analyzer.py` | 1, 2, 3 | Add `prior_analyses`, `research_context`, `agent_name` params |
| `nightwatch/prompts.py` | 1, 2 | Extend `build_analysis_prompt()` with prior knowledge + research sections |
| `nightwatch/config.py` | 1 | Add `nightwatch_knowledge_dir`, `nightwatch_compound_enabled` |
| `nightwatch/slack.py` | 4 | Add pattern + ignore suggestion blocks to report |
| `nightwatch/__main__.py` | 3 | Add `--agent` CLI flag |

### New Test Files (4)

| File | Tests |
|------|-------|
| `tests/test_knowledge.py` | search_prior_knowledge, compound_result, rebuild_index, _match_score, _extract_tags, frontmatter parsing |
| `tests/test_research.py` | _infer_files_from_transaction, _infer_files_from_traces, research_error integration |
| `tests/test_agents.py` | load_agent from file, fallback to default, list_agents, validation |
| `tests/test_patterns.py` | detect_patterns, suggest_ignore_updates, pattern doc writing |

---

## 9. Implementation Order & Dependencies

```
Phase 1 (Knowledge Foundation)     Phase 3 (Agent Config)
    │                                  │
    │ models.py changes                │ agents.py + agents/*.md
    │ knowledge.py                     │ analyzer.py changes
    │ runner.py Steps 0, 12            │ __main__.py --agent flag
    │ prompts.py prior_analyses        │
    │ analyzer.py prior_analyses       │
    │                                  │
    ▼                                  ▼
Phase 2 (Research Enhancement)     Phase 4 (Pattern Detection)
    │                                  │
    │ research.py                      │ patterns.py
    │ runner.py Step 3.5               │ runner.py Step 13
    │ prompts.py research_context      │ models.py RunReport additions
    │ analyzer.py research_context     │ slack.py pattern blocks
    │                                  │
    ▼                                  ▼
  Done                               Done
```

**Phase 1 → Phase 2**: Phase 2 uses `PriorAnalysis` from Phase 1. Must be done in order.

**Phase 3**: Independent of Phases 1-2. Can be done in parallel.

**Phase 4**: Depends on Phase 1 (reads knowledge base for historical patterns). Can be done after Phase 1, in parallel with Phase 2.

**Recommended order**: Phase 1 → (Phase 2 + Phase 3 in parallel) → Phase 4

---

## 10. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Knowledge base grows unbounded | Medium | Low | Cap at 500 error docs. Oldest auto-archived when exceeded. |
| Prior knowledge biases Claude | Low | Medium | Prompt includes "verify independently" instruction. Log when prior knowledge was used vs. not, track accuracy difference. |
| Pre-fetched files add too many tokens | Low | Medium | Cap at 5 files × 100 lines = ~5K tokens max. Drop if initial prompt exceeds 20K tokens. |
| Agent config files get out of sync | Medium | Low | `load_agent()` validates required frontmatter fields. Missing fields use defaults. Tests validate all agent files on CI. |
| Pattern detection false positives | Medium | Low | Patterns are surfaced in Slack (advisory), not acted on automatically. Human reviews suggestions. |
| Index rebuild is slow with many docs | Low | Low | Index rebuild is O(n) file reads. At 500 docs with ~1KB frontmatter each, this is <1 second. |

---

## 11. Success Metrics

| Metric | Baseline (current) | Phase 1 Target | Phase 2 Target | How Measured |
|--------|-------------------|----------------|----------------|--------------|
| Avg iterations/error | ~8 | ~7 (prior knowledge) | ~5 (pre-fetched files) | `ErrorAnalysisResult.iterations` |
| Avg tokens/error | ~15K | ~13K | ~10K | `ErrorAnalysisResult.tokens_used` |
| Duplicate analyses | Unknown | <15% | <10% | Knowledge search hit rate |
| Knowledge docs created | 0 | +5/run avg | — | Count files in `knowledge/errors/` |
| Patterns detected | 0 | — | — | Count in Phase 4 |
| File-not-found tool errors | ~2/error | — | ~0.5/error | Log grep for "File not found" |

---

## 12. Testing Strategy

### Unit Tests (per module)

- **`test_knowledge.py`**: Test search scoring, frontmatter parsing, document writing, index rebuild with fixture documents
- **`test_research.py`**: Test file inference from transaction names (Rails controller → file path), trace extraction, pre-fetch with mock GitHub client
- **`test_agents.py`**: Test loading from valid/invalid/missing Markdown files, frontmatter validation, default fallback
- **`test_patterns.py`**: Test pattern detection with known error clusters, ignore suggestion logic, pattern doc writing

### Integration Tests

- **`test_runner_compound.py`**: End-to-end test of Steps 0 → 12 → 13 with mock clients. Verify knowledge docs are written, index is rebuilt, patterns are detected.
- **`test_prompts_enriched.py`**: Verify `build_analysis_prompt()` with all enrichment (prior knowledge + research context) produces valid, reasonable prompts under the token budget.

### CI Validation

- All agent files (`nightwatch/agents/*.md`) validated for required frontmatter fields
- Knowledge index schema validated against known format
- Ruff lint + format on all new modules

---

## 13. Decisions (Resolved from COMPOUND-001)

| # | Decision | Resolution | Rationale |
|---|----------|-----------|-----------|
| D1 | Knowledge base location | `nightwatch/knowledge/` | Git-trackable, project-local, inspectable |
| D2 | Git-track knowledge? | **Hybrid**: `patterns/` tracked, `errors/` in `.gitignore` | Patterns are shared team knowledge; raw error details may contain sensitive data |
| D3 | Phase 5 multi-agent | **Deferred** | Prove Phases 1-4 first |
| D4 | Agent config format | Markdown + YAML frontmatter | Matches compound-engineering pattern, human-readable, `pyyaml` already installed |
| D5 | Knowledge search timing | Before analysis (inject in prompt) | Cheaper than tool calls, compound-engineering uses same approach |
| D6 | Pattern detection frequency | Per-run + cross-run via knowledge base | Simple, immediate feedback |

### New Decision: `.gitignore` additions

```gitignore
# NightWatch knowledge base — error docs may contain sensitive stack traces
nightwatch/knowledge/errors/
nightwatch/knowledge/index.yml

# Keep patterns tracked (shared team knowledge)
# !nightwatch/knowledge/patterns/
```

---

## 14. Rollback Plan

Each phase has an independent feature flag:

```python
# config.py
nightwatch_compound_enabled: bool = True   # Phase 1+2: knowledge + research
nightwatch_agents_enabled: bool = True     # Phase 3: agent config files
nightwatch_patterns_enabled: bool = True   # Phase 4: pattern detection
```

If any phase causes issues:
1. Set the corresponding env var to `false` (e.g., `NIGHTWATCH_COMPOUND_ENABLED=false`)
2. Pipeline falls back to existing behavior
3. No data loss — knowledge docs remain on disk for re-enablement

---

## 15. Estimated Total Effort

| Phase | Effort | Can Parallelize With |
|-------|--------|---------------------|
| Phase 1: Knowledge Foundation | 2-3 days | — (must be first) |
| Phase 2: Research Enhancement | 1-2 days | Phase 3 |
| Phase 3: Agent Configuration | 1-2 days | Phase 2 |
| Phase 4: Pattern Detection | 2-3 days | — (needs Phase 1) |
| **Total** | **6-10 days** | **4-6 days with parallelization** |

---

**Status**: APPROVED
