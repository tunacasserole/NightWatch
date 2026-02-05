# OpenSpec Proposal: Compound Engineering Patterns for NightWatch

**ID**: COMPOUND-001
**Status**: Draft / Awaiting Approval
**Author**: Claude (AI Assistant)
**Date**: 2026-02-05
**Source**: [EveryInc/compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin) (MIT License)
**Scope**: NightWatch core pipeline + knowledge system

---

## 1. Executive Summary

The compound-engineering-plugin by Every, Inc. is an MIT-licensed Claude Code plugin ecosystem implementing a philosophy where **every unit of engineering work makes subsequent work easier**. It contains 29 specialized AI agents, 25 slash commands, 16 skills, and a cross-platform CLI converter.

This proposal evaluates which patterns and code are applicable to NightWatch and recommends a phased adoption plan. The core thesis: **NightWatch should get smarter with every run** — each error analyzed, each fix proposed, each pattern detected should compound into institutional knowledge that improves future analysis quality and reduces noise.

### Verdict

**Full implementation**: No — the plugin is a Claude Code development workflow tool; NightWatch is a standalone production error analysis CLI. Different domains.

**Pattern adoption**: Yes, strongly recommended — five patterns map directly to NightWatch's architecture and would deliver significant value.

**Code extraction**: Limited — the plugin is TypeScript, NightWatch is Python. We extract *designs and algorithms*, not literal code.

---

## 2. Source Repository Analysis

### What compound-engineering-plugin IS

| Component | Details |
|-----------|---------|
| **Claude Code Plugin** | 29 agents, 25 commands, 16 skills, 1 MCP server |
| **Cross-Platform CLI** | TypeScript converter: Claude Code → OpenCode/Codex formats |
| **License** | MIT (free to use, modify, distribute) |
| **Runtime** | Bun/TypeScript |
| **Architecture** | Parser → Converter → Writer pipeline |

### The Five-Stage Workflow

The plugin implements a compound engineering methodology:

```
Brainstorm → Plan → Work → Review → Compound → (repeat)
```

Each stage has dedicated commands and agents. The "Compound" stage is the key differentiator: it captures learnings from each cycle into searchable knowledge documents with YAML frontmatter, creating a feedback loop where the AI improves over time.

### Key Architectural Patterns

1. **Knowledge Compounding**: `compound-docs` skill + `learnings-researcher` agent = persistent AI memory
2. **Multi-Agent Parallel Review**: 13+ specialized reviewers run simultaneously on the same codebase
3. **Research-Before-Implementation**: Parallel research agents gather context before the main work begins
4. **Frontmatter-Driven Configuration**: YAML frontmatter on all Markdown files enables machine-readable metadata
5. **Progressive Disclosure**: Skills keep entry points concise, with `references/` subdirectories for deep content
6. **Agent Description Pattern**: `<example>` blocks in agent descriptions dramatically improve invocation accuracy
7. **Grep-First Research**: Search frontmatter metadata first, then read only matching documents
8. **Git Worktree Integration**: Shell scripts for parallel isolated development workspaces
9. **Autonomous Workflow Chains**: `/lfg` command chains entire workflows (plan→work→review→compound)
10. **Extensible Target Registry**: Plugin pattern for adding new output formats

---

## 3. Pattern-to-NightWatch Mapping

### 3.1 Knowledge Compounding System

**Source Pattern**: `compound-docs` skill + `learnings-researcher` agent

**How it works in compound-engineering**:
- Solved problems are documented in `docs/solutions/` with structured YAML frontmatter (tags, category, module, severity)
- The `learnings-researcher` agent uses grep-first strategy: search frontmatter tags → read matching docs → synthesize findings
- During planning, researchers automatically check past solutions to prevent repeated mistakes
- This creates a feedback loop: solve → document → search → improve

**NightWatch mapping**: Each NightWatch run produces error analyses. Currently these are ephemeral — lost after the run. The compound pattern transforms them into persistent, searchable knowledge.

**Concrete implementation**:
```
nightwatch/
└── knowledge/
    ├── index.yml                    # Machine-readable index of all solutions
    ├── errors/
    │   ├── 2026-02-05_net-read-timeout_products-controller.md
    │   ├── 2026-02-05_record-not-found_orders-controller.md
    │   └── ...
    └── patterns/
        ├── transient-network-errors.md
        ├── nil-reference-patterns.md
        └── ...
```

Each solution document uses YAML frontmatter:
```yaml
---
error_class: "Net::ReadTimeout"
transaction: "Controller/products/show"
module: "app/controllers/products_controller.rb"
root_cause: "External API timeout without circuit breaker"
fix_confidence: "high"
fix_applied: true
pr_number: 427
occurrences_at_detection: 145
tags: [timeout, external-api, circuit-breaker, products]
first_seen: "2026-02-05"
last_seen: "2026-02-05"
resolution_status: "fixed"
---
```

**Before each analysis**, NightWatch searches this knowledge base:
```python
def search_prior_knowledge(error: ErrorGroup) -> list[PriorAnalysis]:
    """Grep-first search: check frontmatter tags, then read matching docs."""
    candidates = grep_frontmatter(
        directory="knowledge/errors/",
        fields={"error_class": error.error_class, "module": error.transaction}
    )
    return [parse_solution(path) for path in candidates]
```

**Value**: Reduces redundant analysis. If NightWatch has seen `Net::ReadTimeout in ProductsController` before and proposed a circuit breaker fix, it feeds that prior analysis as context to Claude — resulting in faster, more accurate analysis that builds on past work.

**Feasibility**: HIGH — NightWatch already has `ignore.yml` for noise reduction and `.claude/errors/` for dev-time learning. This extends the same philosophy to runtime analysis.

---

### 3.2 Multi-Agent Parallel Analysis

**Source Pattern**: `workflows:review` command launching 13+ specialized reviewer agents simultaneously

**How it works in compound-engineering**:
- The review command spawns parallel Task agents, each with a specialized system prompt
- Agents run concurrently: security reviewer, performance reviewer, data integrity reviewer, architecture reviewer, etc.
- Results are synthesized into a unified review

**NightWatch mapping**: Currently, NightWatch analyzes each error with one generalist Claude agent loop. The compound pattern suggests spawning specialized sub-analyses for complex errors.

**Concrete implementation**:
```python
async def analyze_error_compound(error: ErrorGroup, traces: TraceData, gh: GitHubClient) -> Analysis:
    """Multi-perspective analysis using specialized sub-agents."""

    # Phase 1: Parallel specialized analysis (lightweight, focused prompts)
    sub_analyses = await asyncio.gather(
        analyze_root_cause(error, traces, gh),      # What went wrong?
        analyze_security_impact(error, traces, gh),   # Any security implications?
        analyze_blast_radius(error, traces, gh),      # What else could be affected?
        analyze_fix_approach(error, traces, gh),      # How should we fix this?
    )

    # Phase 2: Synthesis agent merges sub-analyses into unified report
    return synthesize_analyses(error, sub_analyses)
```

**Trade-off**: More API calls per error, but each call is cheaper (shorter, focused prompts) and the combined analysis is more thorough.

**Feasibility**: MEDIUM — Requires adding async support or using threading. NightWatch is currently synchronous by design (batch job simplicity). Could be opt-in via `--deep-analysis` flag for top-N highest-impact errors only.

**Recommendation**: Implement for top 1-2 errors only (highest impact score). Don't go async — use sequential specialized passes instead. Keep it simple.

---

### 3.3 Research-Before-Analyze Pattern

**Source Pattern**: `workflows:plan` runs `repo-research-analyst` + `learnings-researcher` in parallel before planning

**How it works in compound-engineering**:
- Before the main work begins, lightweight research agents gather context
- `repo-research-analyst`: scans codebase structure and conventions
- `learnings-researcher`: searches past solutions using grep-first strategy
- `best-practices-researcher`: fetches external documentation
- `framework-docs-researcher`: checks framework-specific patterns
- All research feeds into the main agent as enriched context

**NightWatch mapping**: Before Claude's main agentic analysis loop, run lightweight research to pre-populate context.

**Concrete implementation**:
```python
def pre_analyze_research(error: ErrorGroup, gh: GitHubClient) -> AnalysisContext:
    """Gather context before the main analysis loop."""

    context = AnalysisContext()

    # 1. Search knowledge base for prior encounters
    context.prior_analyses = search_prior_knowledge(error)

    # 2. Pre-fetch likely relevant files (avoid Claude burning iterations on file discovery)
    context.relevant_files = pre_fetch_relevant_files(error, gh)

    # 3. Check recent PR correlation (already exists in correlation.py)
    context.correlated_prs = correlate_error_with_prs(error, recent_prs)

    # 4. Check ignore patterns for similar errors
    context.similar_ignored = find_similar_ignored_patterns(error)

    return context
```

Then inject this context into Claude's initial prompt:
```python
initial_message = build_analysis_prompt(
    error=error,
    traces=traces,
    prior_analyses=context.prior_analyses,      # "You've seen this before..."
    relevant_files=context.relevant_files,       # "Here are likely relevant files..."
    correlated_prs=context.correlated_prs,       # "These PRs merged recently..."
)
```

**Value**: Reduces Claude's iteration count (currently max 15 per error). If Claude already has the relevant source files and prior analysis context, it can skip 3-5 tool-use iterations of file discovery — saving tokens and time.

**Feasibility**: HIGH — Purely additive. No architectural changes needed. Uses existing `correlation.py` and extends it.

---

### 3.4 Frontmatter-Driven Agent Configuration

**Source Pattern**: Agents defined as Markdown files with YAML frontmatter (name, description, model, allowed-tools)

**How it works in compound-engineering**:
```yaml
---
name: "security-reviewer"
description: "Reviews code for security vulnerabilities..."
model: "claude-sonnet-4-5-20250929"
allowed-tools: ["Read", "Grep", "Glob"]
---

# Security Reviewer

You are a security specialist reviewing code changes...

<example>
  <context>User has a PR with authentication changes</context>
  <response>Check for: SQL injection, XSS, CSRF, auth bypass...</response>
</example>
```

**NightWatch mapping**: Instead of one monolithic `SYSTEM_PROMPT` in `prompts.py`, break analysis capabilities into composable agent definition files.

**Concrete implementation**:
```
nightwatch/
└── agents/
    ├── base-analyzer.md          # Core error analysis agent
    ├── ruby-specialist.md        # Ruby/Rails-specific patterns
    ├── security-assessor.md      # Security impact assessment
    ├── fix-proposer.md           # Fix generation specialist
    └── pattern-detector.md       # Cross-error pattern detection
```

Each agent file:
```yaml
---
name: "ruby-specialist"
description: "Specialized in Ruby on Rails error analysis"
model: "claude-sonnet-4-5-20250929"
thinking_budget: 8000
max_iterations: 10
tools: ["read_file", "search_code", "list_directory"]
---

# Ruby on Rails Error Specialist

You are an expert Ruby on Rails developer analyzing production errors.
Focus on Rails-specific patterns: ActiveRecord, ActionController, routing...

## Analysis Patterns

### ActiveRecord Errors
- N+1 queries → check for `includes` / `preload`
- RecordNotFound → check `find` vs `find_by`
...
```

**Value**: Makes NightWatch's analysis pipeline configurable without code changes. Users can customize analysis behavior by editing Markdown files. New language/framework specialists can be added as files.

**Feasibility**: HIGH — Simple Python implementation:
```python
import yaml

def load_agent(path: str) -> AgentConfig:
    with open(path) as f:
        content = f.read()
    frontmatter, body = content.split("---\n", 2)[1:]
    config = yaml.safe_load(frontmatter)
    config["system_prompt"] = body.strip()
    return AgentConfig(**config)
```

---

### 3.5 Autonomous Compound Loop

**Source Pattern**: `/lfg` command chains: plan → work → review → compound → (repeat)

**How it works in compound-engineering**:
- Single command triggers the full workflow autonomously
- Each stage's output feeds into the next
- The "compound" stage captures learnings for future cycles

**NightWatch mapping**: Extend the run pipeline to include a "compound" phase that feeds results back into the knowledge base.

**Concrete implementation — extend runner.py**:
```python
def run(...) -> RunReport:
    # ... existing Steps 1-11 ...

    # Step 12: COMPOUND — persist learnings
    if not dry_run:
        compound_learnings(report)

    return report


def compound_learnings(report: RunReport) -> None:
    """Persist analysis results as searchable knowledge documents."""
    for result in report.analyses:
        # Write solution document with YAML frontmatter
        write_solution_doc(result)

    # Detect cross-error patterns
    patterns = detect_patterns(report.analyses)
    for pattern in patterns:
        update_pattern_doc(pattern)

    # Update ignore suggestions (errors that keep recurring with no fix)
    suggest_ignore_updates(report)

    # Update knowledge index
    rebuild_knowledge_index()
```

**Value**: This is the core compound engineering principle applied to NightWatch. Each run makes future runs better:
- Repeated errors get faster analysis (prior knowledge)
- Pattern detection surfaces systemic issues
- Auto-suggested ignore patterns reduce noise
- Fix success/failure tracking improves confidence scoring

**Feasibility**: HIGH — Additive step in the existing pipeline. No architectural changes.

---

## 4. Patterns We Do NOT Adopt

| Pattern | Reason |
|---------|--------|
| Cross-platform CLI converter | NightWatch is not a Claude Code plugin |
| OpenCode/Codex format support | Irrelevant to NightWatch's domain |
| Claude Code marketplace | Not applicable |
| Git worktree management | Overkill for NightWatch's single-PR approach |
| Design sync (Figma) agents | Wrong domain |
| Browser testing agents | Wrong domain |
| The specific 29 agent definitions | Every-specific, not generalizable |
| Swarm/TeammateTool orchestration | Claude Code-specific feature |
| Context7 MCP server integration | NightWatch uses direct API calls |

---

## 5. Implementation Plan

### Phase 1: Knowledge Foundation (2-3 days)

**Goal**: NightWatch remembers what it learns.

1. **Create `nightwatch/knowledge/` directory structure**
   - `errors/` — individual error solution documents
   - `patterns/` — cross-error pattern documents
   - `index.yml` — machine-readable index

2. **Implement solution document writer**
   - YAML frontmatter with structured metadata
   - Markdown body with analysis summary
   - Auto-generated from `ErrorAnalysisResult`

3. **Implement grep-first knowledge search**
   - Search frontmatter tags before reading full documents
   - Return prior analyses for matching error class/transaction/module

4. **Add "compound" step to runner.py (Step 12)**
   - After all analysis, persist results as solution documents
   - Rebuild knowledge index

5. **Inject prior knowledge into analysis prompt**
   - Modify `build_analysis_prompt()` to include prior analysis context
   - Claude sees "You've analyzed this error class 3 times before. Previous findings: ..."

**Files modified**: `runner.py`, `prompts.py`, `analyzer.py`
**Files created**: `knowledge.py`, `nightwatch/knowledge/` directory

### Phase 2: Research Enhancement (1-2 days)

**Goal**: NightWatch gathers context before analyzing.

1. **Implement pre-analysis research**
   - Pre-fetch likely relevant files based on error transaction name
   - Search knowledge base for prior encounters
   - Aggregate recent PR correlations (already exists)

2. **Inject research context into initial prompt**
   - Prior analysis summaries
   - Pre-fetched source file snippets
   - Correlated PR information

3. **Track iteration reduction metrics**
   - Log iterations-saved when prior knowledge was available
   - Report efficiency gains in Slack summary

**Files modified**: `analyzer.py`, `prompts.py`, `runner.py`
**Files created**: `research.py`

### Phase 3: Agent Configuration (1-2 days)

**Goal**: Analysis behavior is configurable via Markdown files.

1. **Create agent definition format**
   - YAML frontmatter + Markdown body
   - Fields: name, model, thinking_budget, max_iterations, tools

2. **Implement agent loader**
   - Parse frontmatter, extract system prompt
   - Validate configuration against available tools

3. **Migrate `SYSTEM_PROMPT` from `prompts.py` to `agents/base-analyzer.md`**
   - Backward compatible — falls back to inline prompt if no agent files

4. **Add framework-specific agent files**
   - `agents/ruby-specialist.md` (default for Rails repos)
   - `agents/python-specialist.md` (for Python repos)

**Files modified**: `prompts.py`, `analyzer.py`
**Files created**: `agents/`, agent definition files

### Phase 4: Pattern Detection (2-3 days)

**Goal**: NightWatch surfaces systemic issues across runs.

1. **Implement cross-error pattern detection**
   - Cluster errors by module, error class, and root cause
   - Detect recurring patterns across runs (e.g., "timeout errors in external API calls")
   - Generate pattern documents with trend data

2. **Auto-suggest ignore pattern updates**
   - Errors that recur 5+ times with no fix → suggest adding to `ignore.yml`
   - Errors that stopped occurring → suggest removing from ignore

3. **Add pattern summary to Slack report**
   - "Recurring pattern detected: External API timeouts (3rd occurrence this week)"
   - "Suggested ignore additions: 2 transient patterns detected"

**Files modified**: `runner.py`, `slack.py`
**Files created**: `patterns.py`

### Phase 5 (Future): Multi-Perspective Analysis

**Goal**: Complex errors get analyzed from multiple angles.

1. **Implement specialized analysis passes**
   - Security impact assessment
   - Performance impact assessment
   - Blast radius estimation

2. **Add `--deep-analysis` flag**
   - Opt-in for top N errors
   - Runs additional specialized passes sequentially

3. **Implement analysis synthesis**
   - Merge findings from multiple passes
   - De-duplicate and prioritize

**Decision**: Defer this to after Phases 1-4 prove value. The multi-agent pattern is powerful but adds complexity. NightWatch's synchronous batch design should stay simple until there's evidence it needs more depth.

---

## 6. Code Extraction Inventory

These algorithms and designs are extractable from the MIT-licensed source:

| What | Source Location | NightWatch Equivalent |
|------|----------------|----------------------|
| YAML frontmatter parser | `src/utils/frontmatter.ts` | Python `pyyaml` + custom parser (trivial) |
| Grep-first search strategy | `learnings-researcher` agent | `knowledge.py:search_prior_knowledge()` |
| Agent definition schema | `src/types/claude.ts` | `AgentConfig` Pydantic model |
| Solution document format | `compound-docs` skill | `knowledge.py:write_solution_doc()` |
| Autonomous workflow chain | `/lfg` command | `runner.py` Step 12 compound phase |
| Temperature inference | `claude-to-opencode.ts` | Not needed (single model use) |
| Permission mapping | `claude-to-opencode.ts` | Not needed (no plugin system) |

**Note**: We extract designs and algorithms, not literal TypeScript code. NightWatch is Python.

---

## 7. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Knowledge base grows unbounded | Medium | Low | Automatic archival of old entries; size cap per category |
| Prior knowledge biases analysis | Low | Medium | Include "but verify independently" in prompt; flag when prior knowledge is used |
| Frontmatter parsing fragility | Low | Low | Use battle-tested `pyyaml`; validate on write |
| Additional disk I/O slows runs | Low | Low | Knowledge base will be small (<1000 files); grep is fast |
| Agent config files diverge from code | Medium | Medium | Validate agent configs at startup; integration tests |

---

## 8. Success Metrics

| Metric | Baseline | Target | How Measured |
|--------|----------|--------|--------------|
| Iterations per error | ~8 avg | ~5 avg | Log in `RunReport` |
| Tokens per error | ~15K avg | ~10K avg | Log in `RunReport` |
| Duplicate analysis rate | Unknown | <10% | Count errors with prior knowledge match |
| Fix confidence accuracy | Unknown | Track | Compare confidence to actual fix success |
| Knowledge base growth | 0 docs | +5/run avg | Count solution documents |
| Pattern detection rate | 0 | 2+ patterns/week | Count pattern documents |

---

## 9. Dependency Impact

**No new dependencies required.** All implementations use existing NightWatch dependencies:
- `pyyaml` — already installed (for `ignore.yml`)
- `pydantic` — already installed (for models)
- `anthropic` — already installed (for Claude API)
- File I/O — stdlib `pathlib`, `os`

---

## 10. Decisions Required

| # | Decision | Options | Recommendation |
|---|----------|---------|----------------|
| 1 | Knowledge base location | `nightwatch/knowledge/` vs `~/.nightwatch/knowledge/` vs alongside `ignore.yml` | `nightwatch/knowledge/` — git-trackable, project-local |
| 2 | Git-track knowledge? | Yes (shared learning) vs No (local-only) | **Yes** — the whole point is compound learning; sharing across team is valuable |
| 3 | Phase 5 multi-agent | Implement now vs defer | **Defer** — prove Phases 1-4 first |
| 4 | Agent config format | YAML frontmatter in Markdown vs pure YAML vs Python | **Markdown + frontmatter** — matches compound-engineering pattern, human-readable |
| 5 | Knowledge search timing | Before analysis vs during (tool call) vs both | **Before** — inject as context in initial prompt, cheaper than tool calls |
| 6 | Pattern detection | Per-run vs periodic batch | **Per-run** — simple, immediate feedback |

---

## 11. Relationship to Existing Systems

- **`.claude/errors/`** (LEARN-001): Dev-time error learning for Claude Code sessions. **Complementary** — `.claude/errors/` is for development errors; `knowledge/` is for production error analysis results. Different audiences, different data.
- **`ignore.yml`**: Static noise filter. **Enhanced** — Phase 4 auto-suggests ignore pattern updates based on knowledge base trends.
- **`correlation.py`**: PR-to-error correlation. **Integrated** — Phase 2 includes correlation data in pre-analysis research context.
- **`prompts.py`**: Monolithic system prompt. **Evolved** — Phase 3 migrates to configurable agent definitions while maintaining backward compatibility.

---

## 12. Summary

The compound-engineering-plugin is a rich source of **patterns**, not code. Its core philosophy — every unit of work should make subsequent work easier — maps perfectly to NightWatch's mission.

**Recommended adoption**:
- **Phase 1** (Knowledge Foundation): Highest value, lowest effort. Start here.
- **Phase 2** (Research Enhancement): Builds on Phase 1, reduces token costs.
- **Phase 3** (Agent Configuration): Extensibility play for multi-language support.
- **Phase 4** (Pattern Detection): Strategic value for long-term noise reduction.
- **Phase 5** (Multi-Agent): Defer until Phases 1-4 prove value.

**Total estimated effort**: 6-10 days for Phases 1-4. No new dependencies. No architectural changes. Purely additive to existing pipeline.

---

**Status**: DRAFT — Awaiting Approval
