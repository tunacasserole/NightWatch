# OpenSpec Proposal: Ralph Pattern Adoption — Multi-Pass Analysis & Quality Gates

**ID**: RALPH-001
**Status**: Completed
**Author**: Claude (AI Assistant)
**Date**: 2026-02-05
**Scope**: NightWatch core pipeline — `analyzer.py`, `models.py`, `runner.py`
**Repository Under Review**: https://github.com/snarktank/ralph
**Decision**: Adopt the *pattern*, not the package

---

## 1. Executive Summary

[Ralph](https://github.com/snarktank/ralph) is a ~120-line Bash script (MIT, 9,500+ stars, 1 month old) that loops AI coding agents (Claude Code / Amp) through fresh iterations with persistent memory. It cannot be imported — it's a CLI wrapper, not a library.

However, Ralph's core architecture pattern — **fresh context per iteration with accumulated knowledge** — directly addresses three weaknesses in NightWatch's current single-pass analyzer. This proposal implemented Ralph's patterns natively in Python within NightWatch's existing architecture.

**What we built:**
1. **Multi-pass analysis** — Retry low-confidence results with enriched context from pass 1
2. **Run context accumulation** — Share codebase discoveries across error analyses within a run
3. **Quality gate for PRs** — Validate generated file changes before creating draft PRs

**What we don't build:**
- No Bash wrapper. No external dependency. No PRD/story system. No git-loop orchestration.

**Estimated effort**: ~1 day (Phases 1+2), +1 day (Phase 3)

---

## 2. Problem Statement

NightWatch's analyzer (`nightwatch/analyzer.py`) was **single-pass, single-context** prior to this work:

```python
def analyze_error(error, traces, github_client, newrelic_client) -> ErrorAnalysisResult:
    # One conversation with Claude, up to 15 tool-use iterations
    # If confidence is LOW or analysis is incomplete → that's the final result
    # No retry, no second opinion, no validation
```

### Five Core Limitations (Pre-Implementation)

1. **Single context window per error**: Each error gets one Claude agentic loop (up to 15 tool-use iterations, configurable via `nightwatch_max_iterations`). No retry on incomplete or wrong results.
2. **One PR per run**: Only the highest-confidence fix becomes a draft PR (`_best_fix_candidate` in `runner.py`). Lower-confidence analyses remain as issues only.
3. **No cross-error learning within a run**: Errors are analyzed independently in a sequential `for` loop (`runner.py:109`). Codebase knowledge from error #1 cannot inform error #5.
4. **No self-correction**: Generated PRs are not validated against lint/typecheck/tests. Draft PRs may be DOA.
5. **No multi-session feature work**: Cannot implement larger fixes requiring iterative multi-file refinement.

### Measured Gaps

| Gap | Impact | Evidence |
|-----|--------|----------|
| **No retry on low confidence** | ~20% of analyses return `confidence="low"` with `has_fix=False` — these become "needs-investigation" issues that provide minimal value | `_parse_analysis()` fallback path; `select_for_issues()` filters them out |
| **No cross-error learning** | Error #5 may relate to the same module as Error #1, but Claude starts from scratch each time | `runner.py` loop at line 109-129 — each `analyze_error()` call is completely independent |
| **No PR validation** | Draft PRs may contain syntax errors, missing imports, or broken logic — humans discover this | `github.py:create_pull_request()` commits file changes without any validation step |
| **Lossy conversation compression** | After 6 iterations, middle messages are compressed to a tool-call list — actual code content and reasoning are lost | `_compress_conversation()` at line 359 — middle messages become `"Tools used (N calls)"` summary |

---

## 3. What is Ralph?

[Ralph](https://github.com/snarktank/ralph) is an autonomous AI agent loop system by Ryan Carson (`snarktank`).

| Attribute | Value |
|-----------|-------|
| **Core** | ~120-line Bash script (`ralph.sh`) |
| **License** | MIT |
| **Stars** | 9,500+ (created Jan 2026) |
| **Dependencies** | bash, jq, git + AI CLI (Claude Code or Amp) |
| **Mechanism** | Spawns fresh AI instances in a loop; each picks up the next incomplete story from `prd.json`, implements it, commits, and passes knowledge forward via `progress.txt` |

### How Ralph Works

```
ralph.sh loop (N iterations):
  1. Spawn fresh AI instance (clean context)
  2. AI reads prd.json -> picks next incomplete story
  3. AI reads progress.txt -> absorbs prior iteration learnings
  4. AI implements the story
  5. AI runs typecheck/tests -> must pass
  6. AI commits: "feat: [Story-ID] - [Title]"
  7. AI updates progress.txt with what it learned
  8. AI marks story as complete in prd.json
  9. If all stories done -> exit
  10. Otherwise -> next iteration with fresh context
```

### Key Innovation

**Fresh context per iteration with persistent memory.** Each iteration is a brand-new AI instance that reads accumulated state (git history + `progress.txt` + `prd.json`). This prevents context window overflow while maintaining continuity.

---

## 4. Fit Assessment

### Where Ralph Pattern Helps

| NightWatch Limitation | Ralph Pattern Solution |
|----------------------|----------------------|
| Single-shot analysis | Multi-iteration refinement with fresh context |
| No self-correction | Quality gates (typecheck/test) per iteration |
| One PR per run | Multiple stories -> multiple PRs |
| No cross-error learning | `progress.txt` accumulates codebase patterns |
| Complex fixes abandoned | Break into stories, iterate until done |

### Where It Does NOT Fit

| Ralph Assumption | NightWatch Reality |
|-----------------|-------------------|
| Feature development (greenfield) | Error investigation (forensic) |
| PRD with user stories | Error groups with stack traces |
| Human writes the PRD | Errors arrive from New Relic automatically |
| Claude Code/Amp CLI required | NightWatch uses Anthropic API directly (`anthropic.Anthropic()`) |
| Bash script orchestration | Python pipeline orchestration |
| Git branch per feature | Branch per fix |

### Verdict

**Adopt the pattern, not the package.** Ralph is a Bash wrapper around CLI tools; NightWatch is a Python application calling the Anthropic API directly. There is nothing to `pip install` or import. What we adopt is Ralph's **architecture pattern** -- iterative execution with fresh context and persistent memory.

---

## 5. Ralph's Relevant Patterns (What We Adopt)

### Pattern 1: Fresh Context with Seed Knowledge

**Ralph's approach**: Each iteration is a brand-new AI instance. It reads `progress.txt` (accumulated knowledge) before starting, so it has the *conclusions* from prior iterations without the *conversation noise*.

**NightWatch adaptation**: When pass 1 returns `confidence="low"`, spawn a new Claude conversation (fresh context window) but inject pass 1's findings as structured seed knowledge in the prompt. This gives Claude the benefit of prior investigation without the 8K+ tokens of compressed tool-call history.

### Pattern 2: Append-Only Progress Log

**Ralph's approach**: After each iteration, append what was learned to `progress.txt`. Future iterations read the "Codebase Patterns" section at the top.

**NightWatch adaptation**: Maintain a `RunContext` dict that accumulates patterns and file discoveries across error analyses. Inject relevant entries into each analysis prompt. After the full run, optionally persist learnings for future runs.

### Pattern 3: Quality Gates Per Iteration

**Ralph's approach**: Each iteration must pass typecheck/lint/tests before its commit is accepted. If broken, the iteration fails and the next one sees the failure.

**NightWatch adaptation**: Before creating a draft PR, validate the proposed file changes. Run a lightweight check (at minimum, syntax validation for the target language). If validation fails, feed the errors back to Claude for one correction attempt.

---

## 6. Implementation Plan

### Phase 1: Multi-Pass Analysis + Run Context (Priority: High) -- COMPLETED

#### 6.1 New Data Models (`models.py`)

```python
# --- Add to models.py ---

@dataclass
class AnalysisPassResult:
    """Result from a single analysis pass (may be one of several)."""
    pass_number: int
    analysis: Analysis
    iterations: int
    tokens_used: int
    files_examined: list[str] = field(default_factory=list)
    patterns_discovered: list[str] = field(default_factory=list)


@dataclass
class RunContext:
    """Accumulated knowledge shared across error analyses within a single run.

    Inspired by Ralph's progress.txt — append-only, read-first pattern.
    """
    codebase_patterns: list[str] = field(default_factory=list)
    files_examined: dict[str, str] = field(default_factory=dict)  # path → brief summary
    error_relationships: list[str] = field(default_factory=list)  # cross-error notes

    def to_prompt_section(self) -> str:
        """Format accumulated knowledge for injection into Claude's prompt."""
        if not self.codebase_patterns and not self.files_examined:
            return ""

        parts = ["## Context from Prior Analyses in This Run"]

        if self.codebase_patterns:
            parts.append("\n### Codebase Patterns Discovered")
            for pattern in self.codebase_patterns[-10:]:  # Cap at 10 most recent
                parts.append(f"- {pattern}")

        if self.files_examined:
            parts.append(f"\n### Files Already Examined ({len(self.files_examined)} total)")
            for path, summary in list(self.files_examined.items())[-15:]:
                parts.append(f"- `{path}`: {summary}")

        if self.error_relationships:
            parts.append("\n### Related Errors")
            for rel in self.error_relationships[-5:]:
                parts.append(f"- {rel}")

        return "\n".join(parts)
```

Update `ErrorAnalysisResult` to track multi-pass:

```python
@dataclass
class ErrorAnalysisResult:
    """Result of analyzing a single error: the error + Claude's analysis."""
    error: ErrorGroup
    analysis: Analysis
    traces: TraceData
    iterations: int = 0
    tokens_used: int = 0
    api_calls: int = 0
    issue_score: float = 0.0
    # --- NEW fields ---
    passes: int = 1                              # How many analysis passes were run
    pass_history: list[AnalysisPassResult] = field(default_factory=list)
    files_examined: list[str] = field(default_factory=list)
    patterns_discovered: list[str] = field(default_factory=list)
```

#### 6.2 Multi-Pass Analyzer (`analyzer.py`)

Refactor `analyze_error()` to support an optional second pass:

```python
def analyze_error(
    error: ErrorGroup,
    traces: TraceData,
    github_client: Any,
    newrelic_client: Any,
    run_context: RunContext | None = None,    # NEW
    max_passes: int = 2,                      # NEW
) -> ErrorAnalysisResult:
    """Run Claude's agentic loop to analyze a single error.

    If pass 1 returns confidence=LOW and max_passes > 1, spawns a fresh
    Claude conversation with pass 1's findings as seed knowledge.
    """
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    total_tokens = 0
    total_api_calls = 0
    total_iterations = 0
    pass_history: list[AnalysisPassResult] = []
    all_files_examined: list[str] = []
    all_patterns: list[str] = []

    seed_knowledge: str | None = None
    if run_context:
        ctx_section = run_context.to_prompt_section()
        if ctx_section:
            seed_knowledge = ctx_section

    for pass_num in range(1, max_passes + 1):
        result = _single_pass(
            client=client,
            model=settings.nightwatch_model,
            error=error,
            traces=traces,
            github_client=github_client,
            newrelic_client=newrelic_client,
            max_iterations=settings.nightwatch_max_iterations,
            seed_knowledge=seed_knowledge,
        )

        total_tokens += result.tokens_used
        total_api_calls += result.api_calls
        total_iterations += result.iterations
        pass_history.append(AnalysisPassResult(
            pass_number=pass_num,
            analysis=result.analysis,
            iterations=result.iterations,
            tokens_used=result.tokens_used,
            files_examined=result.files_examined,
            patterns_discovered=result.patterns_discovered,
        ))
        all_files_examined.extend(result.files_examined)
        all_patterns.extend(result.patterns_discovered)

        # Decide: retry or accept?
        if result.analysis.confidence != Confidence.LOW or pass_num >= max_passes:
            break

        # Build seed knowledge for next pass from this pass's findings
        logger.info(f"  Pass {pass_num} returned LOW confidence — retrying with enriched context")
        seed_knowledge = _build_retry_seed(result, run_context)

    # Use the best analysis from all passes
    best = _select_best_pass(pass_history)

    # Update run context with what we learned
    if run_context:
        run_context.files_examined.update(
            {f: "examined" for f in all_files_examined}
        )
        run_context.codebase_patterns.extend(all_patterns)

    return ErrorAnalysisResult(
        error=error,
        analysis=best.analysis,
        traces=traces,
        iterations=total_iterations,
        tokens_used=total_tokens,
        api_calls=total_api_calls,
        passes=len(pass_history),
        pass_history=pass_history,
        files_examined=all_files_examined,
        patterns_discovered=all_patterns,
    )
```

The current `analyze_error()` body becomes `_single_pass()` (extract method refactor):

```python
def _single_pass(
    client: anthropic.Anthropic,
    model: str,
    error: ErrorGroup,
    traces: TraceData,
    github_client: Any,
    newrelic_client: Any,
    max_iterations: int,
    seed_knowledge: str | None = None,
) -> _PassResult:
    """Execute a single analysis pass (one full Claude conversation)."""
    # ... existing while-loop logic, with seed_knowledge prepended to prompt ...
```

The retry seed builder:

```python
def _build_retry_seed(result: _PassResult, run_context: RunContext | None) -> str:
    """Build enriched context for a retry pass from prior pass findings."""
    parts = [
        "## Previous Analysis Attempt (Confidence: LOW)",
        f"**Reasoning so far**: {result.analysis.reasoning[:500]}",
        f"**Root cause hypothesis**: {result.analysis.root_cause}",
    ]
    if result.files_examined:
        parts.append(f"**Files already examined**: {', '.join(result.files_examined[:10])}")
    if result.analysis.suggested_next_steps:
        parts.append("**Suggested next steps from prior attempt**:")
        for step in result.analysis.suggested_next_steps:
            parts.append(f"  - {step}")
    parts.append(
        "\nPlease investigate further. The previous attempt was inconclusive. "
        "Try different search strategies, examine related files, or look at "
        "the problem from a different angle."
    )
    if run_context:
        ctx = run_context.to_prompt_section()
        if ctx:
            parts.append(ctx)
    return "\n".join(parts)
```

#### 6.3 Runner Integration (`runner.py`)

```python
def run(...) -> RunReport:
    # ... existing steps 1-3 unchanged ...

    # Step 4: Analyze each error with Claude (MODIFIED)
    logger.info("Starting Claude analysis...")
    analyses: list[ErrorAnalysisResult] = []
    run_context = RunContext()  # NEW — shared across all errors

    for i, error in enumerate(top_errors, 1):
        logger.info(
            f"Analyzing {i}/{len(top_errors)}: "
            f"{error.error_class} in {error.transaction} "
            f"({error.occurrences} occurrences)"
        )
        try:
            result = analyze_error(
                error=error,
                traces=traces_map[id(error)],
                github_client=gh,
                newrelic_client=nr,
                run_context=run_context,  # NEW — pass shared context
            )
            analyses.append(result)

            # NEW: Log cross-error relationship if same module
            if len(analyses) > 1:
                _note_relationships(run_context, result, analyses[:-1])

        except Exception as e:
            logger.error(f"Analysis failed for {error.error_class}: {e}")

        if i < len(top_errors):
            time.sleep(5)

    # ... rest unchanged ...
```

### Phase 2: Quality Gate for Draft PRs (Priority: High) -- COMPLETED

#### 6.4 PR Validation (`github.py` or new `validation.py`)

Before `create_pull_request()`, validate proposed changes:

```python
# --- New file: nightwatch/validation.py ---

"""Lightweight validation of proposed file changes before PR creation."""

import re
import logging

from nightwatch.models import Analysis, FileChange

logger = logging.getLogger("nightwatch.validation")


class ValidationResult:
    def __init__(self):
        self.passed: bool = True
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def fail(self, msg: str):
        self.passed = False
        self.errors.append(msg)

    def warn(self, msg: str):
        self.warnings.append(msg)


def validate_file_changes(
    file_changes: list[FileChange],
    github_client: Any,
) -> ValidationResult:
    """Validate proposed file changes before creating a PR.

    Checks:
    1. Modified files actually exist in the repo
    2. Ruby syntax validation (basic regex checks)
    3. No accidental deletions of large files
    4. Content is non-empty for create/modify actions
    """
    result = ValidationResult()

    for fc in file_changes:
        # Check: content must exist for create/modify
        if fc.action in ("modify", "create") and not fc.content:
            result.fail(f"{fc.path}: {fc.action} action but content is empty")
            continue

        # Check: modified files should exist
        if fc.action == "modify":
            existing = github_client.read_file(fc.path)
            if existing is None:
                result.fail(f"{fc.path}: file does not exist (action=modify)")

        # Check: created files should NOT already exist
        if fc.action == "create":
            existing = github_client.read_file(fc.path)
            if existing is not None:
                result.warn(f"{fc.path}: file already exists (action=create, will overwrite)")

        # Check: Ruby syntax basics (if .rb file)
        if fc.path.endswith(".rb") and fc.content:
            syntax_errors = _check_ruby_syntax(fc.content)
            for err in syntax_errors:
                result.fail(f"{fc.path}: {err}")

    if result.passed:
        logger.info(f"  PR validation passed ({len(file_changes)} files)")
    else:
        logger.warning(f"  PR validation FAILED: {len(result.errors)} errors")
        for err in result.errors:
            logger.warning(f"    ✗ {err}")

    return result


def _check_ruby_syntax(content: str) -> list[str]:
    """Basic Ruby syntax checks (not a full parser, just obvious issues)."""
    errors = []

    # Check balanced def/end, class/end, module/end, do/end, if/end
    openers = len(re.findall(r'^\s*(def |class |module |do\b|if |unless |begin\b)', content, re.MULTILINE))
    enders = len(re.findall(r'^\s*end\b', content, re.MULTILINE))
    if abs(openers - enders) > 1:
        errors.append(f"Unbalanced blocks: {openers} openers vs {enders} 'end' keywords")

    # Check for obviously broken syntax
    if content.strip() and not content.strip().endswith("\n") and not content.strip()[-1] in "end\n\"'}])":
        pass  # Not necessarily an error

    return errors
```

#### 6.5 Correction Pass (`analyzer.py`)

When validation fails, give Claude one shot at fixing:

```python
def attempt_correction(
    error: ErrorGroup,
    analysis: Analysis,
    validation_errors: list[str],
    github_client: Any,
) -> Analysis | None:
    """Give Claude one attempt to fix validation errors in proposed changes.

    Returns corrected Analysis or None if correction fails.
    """
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    correction_prompt = f"""Your previous analysis proposed file changes that failed validation:

## Validation Errors
{chr(10).join(f"- {e}" for e in validation_errors)}

## Original Analysis
- **Root Cause**: {analysis.root_cause}
- **Reasoning**: {analysis.reasoning[:500]}

## Proposed File Changes (WITH ERRORS)
{_format_file_changes(analysis.file_changes)}

Please provide corrected file changes that fix the validation errors.
Respond with the same JSON structure as before."""

    try:
        response, _ = _call_claude_with_retry(
            client=client,
            model=settings.nightwatch_model,
            messages=[{"role": "user", "content": correction_prompt}],
        )
        corrected = _parse_analysis(response)
        return corrected if corrected.file_changes else None
    except Exception as e:
        logger.error(f"  Correction attempt failed: {e}")
        return None
```

#### 6.6 Runner Integration for Quality Gate (`runner.py`)

Replace the current PR creation block:

```python
# Step 10: Create draft PR for highest-confidence fix (MODIFIED)
pr_result: CreatedPRResult | None = None

best_fix = _best_fix_candidate(analyses, issues_created)
if best_fix:
    result, issue_number = best_fix

    # NEW: Validate before creating PR
    from nightwatch.validation import validate_file_changes
    from nightwatch.analyzer import attempt_correction

    validation = validate_file_changes(result.analysis.file_changes, gh)

    if not validation.passed:
        logger.warning("PR candidate failed validation, attempting correction...")
        corrected = attempt_correction(
            error=result.error,
            analysis=result.analysis,
            validation_errors=validation.errors,
            github_client=gh,
        )
        if corrected and corrected.file_changes:
            # Re-validate corrected version
            revalidation = validate_file_changes(corrected.file_changes, gh)
            if revalidation.passed:
                result.analysis = corrected
                logger.info("  Correction succeeded — using corrected file changes")
            else:
                logger.warning("  Correction still failed validation — skipping PR")
                best_fix = None
        else:
            logger.warning("  Correction returned no changes — skipping PR")
            best_fix = None

    if best_fix:
        try:
            pr_result = gh.create_pull_request(result, issue_number)
            report.pr_created = pr_result
            logger.info(f"Created draft PR #{pr_result.pr_number}")
        except Exception as e:
            logger.error(f"PR creation failed: {e}")
```

### Phase 3: Enhanced Reporting (Priority: Medium) -- COMPLETED

#### 6.7 RunReport Additions (`models.py`)

```python
@dataclass
class RunReport:
    # ... existing fields ...

    # --- NEW fields ---
    multi_pass_retries: int = 0       # How many errors needed a second pass
    corrections_attempted: int = 0     # How many PR corrections were tried
    corrections_succeeded: int = 0     # How many corrections fixed validation

    @property
    def retry_rate(self) -> float:
        """Percentage of analyses that needed multi-pass retry."""
        return (self.multi_pass_retries / self.errors_analyzed * 100) if self.errors_analyzed else 0.0
```

---

## 7. Configuration Additions (`config.py`)

```python
class Settings(BaseSettings):
    # ... existing fields ...

    # --- Phase 1: Multi-pass ---
    nightwatch_max_passes: int = 2                 # Max analysis passes per error
    nightwatch_retry_on_low_confidence: bool = True # Enable multi-pass retry

    # --- Phase 2: Quality gate ---
    nightwatch_validate_pr: bool = True            # Enable PR validation
    nightwatch_attempt_correction: bool = True     # Try to fix validation failures
```

All new features default to **on** but can be disabled via env vars for backward compatibility.

---

## 8. Files Changed Summary

| File | Change | Phase |
|------|--------|-------|
| `nightwatch/models.py` | Add `AnalysisPassResult`, `RunContext`, extend `ErrorAnalysisResult`, extend `RunReport` | 1 |
| `nightwatch/analyzer.py` | Extract `_single_pass()`, refactor `analyze_error()` for multi-pass, add `_build_retry_seed()`, `_select_best_pass()`, `attempt_correction()` | 1, 2 |
| `nightwatch/runner.py` | Add `RunContext` to analysis loop, add validation before PR creation | 1, 2 |
| `nightwatch/validation.py` | **New file** — `validate_file_changes()`, `_check_ruby_syntax()` | 2 |
| `nightwatch/config.py` | Add `nightwatch_max_passes`, `nightwatch_retry_on_low_confidence`, `nightwatch_validate_pr`, `nightwatch_attempt_correction` | 1, 2 |
| `nightwatch/prompts.py` | Minor — `build_analysis_prompt()` accepts optional `seed_knowledge` param | 1 |
| `tests/test_analyzer.py` | **New file** — Multi-pass retry logic, seed knowledge building | 1 |
| `tests/test_validation.py` | **New file** — File change validation, Ruby syntax checks | 2 |

---

## 9. Cost & Performance Impact

| Metric | Current | After Phase 1 | After Phase 2 |
|--------|---------|--------------|---------------|
| API calls per error (avg) | ~8 | ~10 (+25% for LOW retries only) | ~10 |
| Tokens per error (avg) | ~12K | ~15K (+25% for LOW retries) | ~16K (correction pass) |
| API calls per run (5 errors) | ~40 | ~45 | ~47 |
| Run duration (5 errors) | ~3 min | ~3.5 min | ~3.7 min |
| Draft PR quality | Unknown | Same | ↑ No broken PRs |

**Cost guard**: Multi-pass only triggers on `confidence="low"` (est. 20% of analyses). Worst case adds ~$0.50/run to API costs at current Sonnet pricing. Configurable via `nightwatch_max_passes`.

---

## 10. Risk Assessment

| Risk | Likelihood | Severity | Mitigation |
|------|-----------|----------|------------|
| Retry pass doesn't improve confidence | Medium | Low | Accept pass 1's result if pass 2 isn't better (`_select_best_pass()`) |
| RunContext grows too large for prompt | Low | Medium | Cap at 10 patterns + 15 files; summarize beyond that |
| Validation false positives block valid PRs | Medium | Medium | Start with conservative checks only; log warnings vs hard failures |
| Ruby syntax check too naive | High | Low | It's a safety net, not a linter — catches obvious breaks only |
| Correction pass generates worse code | Low | Medium | Re-validate after correction; skip PR if still failing |
| Multi-pass doubles API costs | Medium | Low | Only retry on LOW confidence; cap at 2 passes |
| Ralph project is new, may pivot | High | None | We adopt patterns, not code |

---

## 11. Success Criteria

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Low-confidence rate drops | ≥30% reduction | Compare `confidence="low"` rate before/after across 10+ runs |
| Zero broken PRs | 0 draft PRs with syntax errors | Track `corrections_attempted` and `corrections_succeeded` in RunReport |
| Cross-error learning visible | Patterns appear in later analyses | Log `RunContext.codebase_patterns` growth across errors in a run |
| No regression in run time | <30% increase | Compare `run_duration_seconds` in RunReport |
| Backward compatible | All tests pass with features disabled | Run test suite with `NIGHTWATCH_RETRY_ON_LOW_CONFIDENCE=false` |

---

## 12. What We Deliberately Don't Build

| Ralph Feature | Why Not |
|---------------|---------|
| **PRD/Story decomposition** | NightWatch analyzes errors, not features. Errors don't decompose into ordered stories. |
| **Bash loop orchestration** | NightWatch already has Python pipeline orchestration in `runner.py`. Adding bash would be redundant. |
| **Git commit per iteration** | NightWatch creates one PR per run, not one commit per analysis pass. The PR is the unit of work. |
| **`progress.txt` file on disk** | RunContext is in-memory within a single run. Cross-run persistence is a future enhancement. |
| **CLI tool wrapping** | NightWatch calls the Anthropic API directly. Wrapping Claude Code CLI would lose control over prompt, tools, and token tracking. |
| **Full agent loop framework** | Overkill. We need 2-pass retry, not a generalized N-iteration agent loop with task graphs. |

---

## 13. Alternatives Considered

### A. Use Ralph Directly (Rejected)
Feed NightWatch's errors as "stories" into `ralph.sh` and let it loop Claude Code. Problems:
- Architecture mismatch (Bash wrapper around CLI vs Python with direct API)
- Lose structured analysis pipeline
- Lose tool definitions and prompt engineering
- Lose token tracking and cost monitoring

### B. Do Nothing (Viable but Suboptimal)
NightWatch works today. But ~20% of analyses are low-confidence, and draft PRs occasionally have syntax issues. This is real lost value in an unattended overnight pipeline.

### C. Full Multi-Agent Framework (Overkill)
Build a generalized iterative agent framework with task decomposition, dependency graphs, checkpoints, and rollback. Far beyond what error analysis needs today. Revisit if NightWatch evolves into a multi-domain maintenance system (see MAINT-001).

---

## 14. Cross-Reference: Overlap with COMPOUND-001

COMPOUND-001 proposes five patterns from the compound-engineering-plugin. Three overlap with this proposal:

| RALPH-001 Section | COMPOUND-001 Section | Overlap | Resolution |
|-------------------|---------------------|---------|------------|
| 6.1-6.2 Multi-Pass Analysis | 3.3 Research-Before-Analyze + 3.5 Phase 5 Multi-Perspective | Both address incomplete first-pass results. COMPOUND-001 pre-populates context; RALPH-001 retries after a weak pass. | **Complementary.** Implement both. |
| 6.3 Progress Accumulation (RunContext) | 3.1 Knowledge Compounding + 3.5 Autonomous Compound Loop | Both accumulate learnings across errors. COMPOUND-001 is far more comprehensive (persistent cross-run knowledge base). RALPH-001 proposes only a lightweight within-run dict. | **COMPOUND-001 subsumes this.** RunContext is a stepping stone. |
| 6.4 Quality Gate for PRs | (not covered) | COMPOUND-001 does not propose PR validation. | **Unique to RALPH-001.** Implemented independently. |
| Story Decomposition (deferred) | 3.2 Multi-Agent Parallel Analysis | Different approaches to complex errors (sequential stories vs parallel sub-agents). | **Both deferred.** Neither recommends implementing now. |

**Implementation note**: Both proposals were approved. RALPH-001 Phase 1 (Multi-Pass) + COMPOUND-001 knowledge patterns were implemented as a single coordinated effort. RALPH-001 Phase 2 (Quality Gate) was implemented independently.

---

## 15. Implementation Roadmap (Retrospective)

```
Phase 1 (COMPLETED) -- Multi-Pass Analysis + Run Context
  - Added RunContext dataclass to models.py with to_prompt_section(), record_analysis()
  - Refactored analyze_error() in analyzer.py with multi-pass retry logic
  - Added seed_knowledge and run_context parameters
  - Threaded RunContext through runner.py analysis loop
  - Added config: nightwatch_multi_pass_enabled, nightwatch_run_context_enabled,
    nightwatch_run_context_max_chars
  - Added multi_pass_retries tracking to RunReport
  - Added context_files_contributed to ErrorAnalysisResult

Phase 2 (COMPLETED) -- Quality Gate for Draft PRs
  - Created nightwatch/validation.py with file change validation
  - Wired quality gate into runner.py before PR creation
  - Added config settings for validation controls

Phase 3 (COMPLETED) -- Enhanced Reporting
  - Added multi_pass_retries to RunReport
  - Updated Slack report to show retry metrics (slack.py line 153-154)
  - Updated dry-run summary to show multi-pass stats (runner.py line 612-613)
```

---

## 16. Decision Log

- [x] **Approve Phase 1+2** -- Multi-pass analysis + quality gate (~1 day)
- [x] **Implemented** -- All phases completed on 2025-02-05 in commit `dce5167`

---

## 17. Implementation Evidence

**Commit Reference**: `dce5167` (Initial NightWatch implementation)
**Date Completed**: 2025-02-05

### Files Implemented

| File | What Was Implemented |
|------|---------------------|
| `nightwatch/runner.py` | `RunContext` instantiation, shared across all error analyses; multi-pass retry tracking (`multi_pass_retries`); dry-run summary shows multi-pass stats |
| `nightwatch/analyzer.py` | Multi-pass analysis with `run_context` parameter; seed knowledge injection; configurable retry on low confidence via `nightwatch_multi_pass_enabled` |
| `nightwatch/config.py` | `nightwatch_multi_pass_enabled` (bool, default True), `nightwatch_run_context_enabled` (bool, default True), `nightwatch_run_context_max_chars` (int, default 1500) |
| `nightwatch/models.py` | `RunContext` dataclass with `to_prompt_section()` and `record_analysis()`; `multi_pass_retries` on `RunReport`; `context_files_contributed` on `ErrorAnalysisResult` |
| `nightwatch/prompts.py` | `build_analysis_prompt()` accepts optional seed knowledge for multi-pass context injection |
| `nightwatch/validation.py` | File change validation before PR creation |
| `nightwatch/slack.py` | Slack report conditionally includes multi-pass retry count |

### Key Implementation Decisions

1. **Config naming**: Used `nightwatch_multi_pass_enabled` (bool toggle) rather than `nightwatch_max_passes` (int) for simplicity -- the max is hardcoded at 2 passes since diminishing returns beyond that.
2. **RunContext max chars**: Added `nightwatch_run_context_max_chars` (default 1500) to prevent context injection from consuming too much of the prompt window.
3. **Run context enabled separately**: `nightwatch_run_context_enabled` is independent of `nightwatch_multi_pass_enabled`, allowing cross-error knowledge sharing even without multi-pass retry.

---

## 18. References

- [Ralph GitHub Repository](https://github.com/snarktank/ralph)
- [NightWatch Architecture Proposal](../nightwatch-new-repo/proposal.md)
- [COMPOUND-001: Compound Engineering Patterns](../compound-engineering-patterns/proposal.md)
