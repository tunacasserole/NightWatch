# OpenSpec Proposal: Ralph Integration for Multi-Iteration Autonomous Analysis

**ID**: RALPH-001
**Status**: Draft / Awaiting Approval
**Author**: Claude (AI Assistant)
**Date**: 2026-02-05
**Scope**: NightWatch pipeline enhancement — optional autonomous loop wrapper

---

## 1. Problem Statement

NightWatch currently runs as a single-shot batch job: one invocation analyzes N errors, creates issues, opens one draft PR, sends a Slack summary, and exits. This works well for its design goal ("run once, analyze everything, report, done"), but has inherent limitations:

1. **Single context window per error**: Each error analysis gets one Claude agentic loop (up to 15 iterations of tool use). If the analysis is incomplete or the fix is wrong, there's no retry mechanism — the result ships as-is.

2. **One PR per run**: Only the highest-confidence fix becomes a draft PR. Lower-confidence analyses that *could* become fixes with more investigation are left as issues.

3. **No cross-error learning within a run**: Each error is analyzed independently. Claude doesn't accumulate codebase knowledge from error #1 that could help with error #5.

4. **No self-correction**: If a generated PR has lint/typecheck/test failures, NightWatch doesn't detect or fix them. The draft PR may be DOA.

5. **No multi-session feature work**: NightWatch can't autonomously implement larger fixes that span multiple files and require iterative refinement.

---

## 2. What is Ralph?

[Ralph](https://github.com/snarktank/ralph) is an autonomous AI agent loop system by Ryan Carson (`snarktank`). Key facts:

| Attribute | Value |
|-----------|-------|
| **Core** | ~120-line Bash script (`ralph.sh`) |
| **License** | MIT |
| **Stars** | 9,500+ (1 month old, viral) |
| **Dependencies** | bash, jq, git + AI CLI (Claude Code or Amp) |
| **Mechanism** | Spawns fresh AI instances in a loop, each picks up the next incomplete "story" from a `prd.json`, implements it, commits, and passes knowledge forward via `progress.txt` |

### How Ralph Works

```
ralph.sh loop (N iterations):
  1. Spawn fresh AI instance (clean context)
  2. AI reads prd.json → picks next incomplete story
  3. AI reads progress.txt → absorbs prior iteration learnings
  4. AI implements the story
  5. AI runs typecheck/tests → must pass
  6. AI commits: "feat: [Story-ID] - [Title]"
  7. AI updates progress.txt with what it learned
  8. AI marks story as complete in prd.json
  9. If all stories done → signal COMPLETE → exit
  10. Otherwise → next iteration with fresh context
```

### Ralph's Key Innovation

**Fresh context per iteration with persistent memory.** Rather than one long conversation that exhausts the context window, each iteration is a brand-new AI instance that reads accumulated state (git history + `progress.txt` + `prd.json`). This prevents context window overflow while maintaining continuity.

---

## 3. Fit Assessment: Does NightWatch Need Ralph?

### Where Ralph's Pattern Could Help

| NightWatch Limitation | Ralph Pattern Solution |
|----------------------|----------------------|
| Single-shot analysis | Multi-iteration refinement with fresh context |
| No self-correction | Quality gates (typecheck/test) per iteration |
| One PR per run | Multiple stories → multiple PRs |
| No cross-error learning | `progress.txt` accumulates codebase patterns |
| Complex fixes abandoned | Break into stories, iterate until done |

### Where Ralph's Pattern Does NOT Fit

| Ralph Assumption | NightWatch Reality |
|-----------------|-------------------|
| Feature development (greenfield) | Error investigation (forensic) |
| PRD with user stories | Error groups with traces |
| Human writes the PRD | Errors come from New Relic automatically |
| Claude Code/Amp CLI required | NightWatch uses Anthropic API directly |
| Bash script orchestration | Python pipeline orchestration |
| Git branch per feature | Branch per fix |
| Fresh AI instance per iteration | NightWatch controls the Claude loop itself |

### Honest Verdict

**Ralph is inspiring but not directly usable.** The core *pattern* — iterative AI execution with fresh context and persistent memory — is valuable. But Ralph itself is a Bash wrapper around CLI tools, while NightWatch is a Python application that calls the Anthropic API directly. You can't `pip install ralph` or import it.

What we'd actually adopt is **Ralph's architecture pattern**, not Ralph's code.

---

## 4. Proposed Integration: "Ralph Pattern" for NightWatch

Rather than depending on Ralph as a package, we implement its key patterns natively in Python within NightWatch's existing architecture.

### 4.1 Multi-Pass Analysis (Priority: High)

**Current**: One Claude loop per error (up to 15 tool-use iterations).
**Proposed**: If the first pass produces a low-confidence result, spawn a second pass with fresh context + the first pass's findings as seed knowledge.

```python
# Conceptual flow
result = analyzer.analyze(error, traces)

if result.confidence == Confidence.LOW and not dry_run:
    # Second pass with enriched context
    seed = f"Previous analysis found: {result.reasoning}\nFiles examined: {result.files_read}"
    result = analyzer.analyze(error, traces, seed_knowledge=seed)
```

**Effort**: Small. Modify `analyzer.py` to accept optional seed knowledge. Modify `runner.py` to retry low-confidence results.

### 4.2 Quality Gate for PRs (Priority: High)

**Current**: Draft PR is created with proposed file changes, no validation.
**Proposed**: After creating a PR branch, run lint/typecheck/test against it. If it fails, feed the errors back to Claude for a correction pass.

```python
# Conceptual flow
pr = github.create_pr(analysis)
check_result = run_quality_checks(pr.branch)

if not check_result.passed:
    correction = analyzer.correct(analysis, check_result.errors)
    github.update_pr(pr, correction.file_changes)
```

**Effort**: Medium. Requires a way to run checks against the target repo (clone + run, or GitHub Actions).

### 4.3 Progress Accumulation Within a Run (Priority: Medium)

**Current**: Each error analyzed independently.
**Proposed**: Maintain a `run_context` dict that accumulates codebase patterns discovered during analysis. Feed this as additional context to subsequent error analyses.

```python
run_context = {"patterns_discovered": [], "files_examined": set()}

for error in errors:
    result = analyzer.analyze(error, traces, run_context=run_context)
    run_context["patterns_discovered"].extend(result.learnings)
    run_context["files_examined"].update(result.files_read)
```

**Effort**: Small. Add optional `run_context` parameter to analyzer. Append to system prompt.

### 4.4 Story Decomposition for Complex Fixes (Priority: Low)

**Current**: One analysis → one PR with all changes.
**Proposed**: For complex fixes (many files, high uncertainty), decompose into ordered sub-tasks and implement each in sequence with fresh context.

**Effort**: Large. Requires a planning step, task tracking, multi-commit workflow. This is where the full Ralph pattern would live, but it's overkill for NightWatch's current scope.

---

## 5. Recommendation

### Adopt: The Pattern (not the package)

| What | Decision | Rationale |
|------|----------|-----------|
| `pip install ralph` / add as dependency | **No** | Ralph is a Bash script, not a library. No package to install. |
| Copy `ralph.sh` into NightWatch | **No** | NightWatch already has its own Python orchestration. Adding a Bash wrapper would be redundant and architecturally inconsistent. |
| Implement Ralph's *patterns* natively | **Yes** | Multi-pass analysis, quality gates, and progress accumulation are valuable patterns that fit naturally into the existing Python pipeline. |
| Full story decomposition system | **Not yet** | Overkill for error analysis. Revisit if NightWatch expands to feature implementation. |

### Implementation Priority

| Phase | Enhancement | Effort | Value |
|-------|------------|--------|-------|
| **Phase 1** | Multi-pass analysis for low-confidence results | 2-4 hours | High — catches more root causes |
| **Phase 1** | Run context accumulation across errors | 1-2 hours | Medium — smarter analysis over time |
| **Phase 2** | Quality gate for generated PRs | 4-8 hours | High — no more broken draft PRs |
| **Phase 3** | Story decomposition (if needed) | 2-3 days | Low — only if scope expands |

### Total Estimated Effort

Phases 1-2: **~1 day** of implementation for meaningful improvement.

---

## 6. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Multi-pass doubles API costs | Medium | Low | Only retry on LOW confidence; cap at 2 passes |
| Run context grows too large for prompt | Low | Medium | Truncate to most recent N patterns; summarize |
| Quality gate requires target repo clone | Medium | Medium | Start with GitHub Actions status checks; clone later |
| Ralph project is 1 month old, may pivot | High | None | We're adopting patterns, not depending on the code |

---

## 7. Alternatives Considered

### A. Use Ralph Directly (Rejected)
Wrap NightWatch's output as a "PRD" and feed it to `ralph.sh`. This would mean:
- Running Claude Code CLI instead of Anthropic API (architecture mismatch)
- Losing NightWatch's structured analysis pipeline
- Adding Bash orchestration on top of Python orchestration
- Giving up control over the analysis loop

### B. Do Nothing (Viable but Suboptimal)
NightWatch works as-is. Single-shot analysis covers ~80% of cases. But the 20% of low-confidence results and broken PRs represent real lost value.

### C. Build Full Agent Loop Framework (Overkill)
Build a generalized iterative agent framework with task decomposition, dependency graphs, and multi-agent coordination. Far beyond what error analysis needs.

---

## 8. Success Criteria

- Low-confidence analyses decrease by >30% after multi-pass retry
- Zero draft PRs with lint/typecheck failures (quality gate)
- Measurable in `RunReport` metrics (confidence distribution, PR pass rate)

---

## 9. References

- [Ralph GitHub Repository](https://github.com/snarktank/ralph)
- [NightWatch Architecture Proposal](../nightwatch-new-repo/proposal.md)
- Ryan Carson's compound engineering approach
- Geoffrey Huntley's original agent loop pattern
