# OpenSpec Proposal: Ralph Integration for Multi-Iteration Autonomous Analysis

**ID**: RALPH-001
**Status**: Draft / Awaiting Approval
**Author**: Claude (AI Assistant)
**Date**: 2026-02-05
**Scope**: NightWatch pipeline enhancement -- adopt Ralph iterative loop patterns
**Related**: [COMPOUND-001](../compound-engineering-patterns/proposal.md) (overlapping concerns -- see Section 10)

---

## 1. Problem Statement

NightWatch runs as a single-shot batch job: fetch errors, analyze, create issues, open one draft PR, notify Slack, exit. Five limitations:

1. **Single context window per error**: Each error gets one Claude agentic loop (up to 15 tool-use iterations, configurable via `nightwatch_max_iterations`). No retry on incomplete or wrong results.
2. **One PR per run**: Only the highest-confidence fix becomes a draft PR (`_best_fix_candidate` in `runner.py`). Lower-confidence analyses remain as issues only.
3. **No cross-error learning within a run**: Errors are analyzed independently in a sequential `for` loop (`runner.py:109`). Codebase knowledge from error #1 cannot inform error #5.
4. **No self-correction**: Generated PRs are not validated against lint/typecheck/tests. Draft PRs may be DOA.
5. **No multi-session feature work**: Cannot implement larger fixes requiring iterative multi-file refinement.

---

## 2. What is Ralph?

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

## 3. Fit Assessment

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

## 4. Proposed Integration: Ralph Pattern for NightWatch

Implement Ralph's key patterns natively in Python within NightWatch's existing architecture.

### 4.1 Multi-Pass Analysis (Priority: High)

> **Cross-ref**: COMPOUND-001 Section 3.3 (Research-Before-Analyze) proposes a complementary approach -- pre-populating context *before* the first pass to reduce weak results. This section focuses on *retrying after* a weak first pass. The two are additive.

**Current**: One Claude loop per error (up to 15 tool-use iterations).
**Proposed**: If the first pass produces a low-confidence result, spawn a second pass with fresh context + the first pass's findings as seed knowledge.

```python
# Conceptual flow (modifies runner.py analysis loop)
result = analyze_error(error, traces, github_client=gh, newrelic_client=nr)

if result.analysis.confidence == Confidence.LOW and not dry_run:
    seed = f"Previous analysis found: {result.analysis.reasoning}\n"
    seed += f"Root cause hypothesis: {result.analysis.root_cause}"
    result = analyze_error(error, traces, github_client=gh, newrelic_client=nr,
                           seed_knowledge=seed)
```

**Effort**: Small. Add optional `seed_knowledge` param to `analyze_error()`. Retry low-confidence results in `runner.py`. Cap at 2 passes.

### 4.2 Quality Gate for PRs (Priority: High)

**Current**: Draft PR is created via `GitHubClient.create_pull_request()` with no validation.
**Proposed**: After creating the PR branch, run lint/typecheck/test. On failure, feed errors back to Claude for a correction pass.

```python
# Conceptual flow (extends runner.py Step 10)
pr_result = gh.create_pull_request(result, issue_number)
check_result = run_quality_checks(pr_result.branch_name)

if not check_result.passed:
    correction = analyze_error(error, traces, github_client=gh, newrelic_client=nr,
                               seed_knowledge=f"Fix failed checks:\n{check_result.errors}")
    gh.update_pr(pr_result, correction.analysis.file_changes)
```

**Effort**: Medium. Requires a mechanism to run checks against the target repo (clone + run, or poll GitHub Actions status checks).

### 4.3 Progress Accumulation Within a Run (Priority: Medium)

> **Cross-ref**: COMPOUND-001 Section 3.1 (Knowledge Compounding) proposes a much more comprehensive version -- persistent cross-run knowledge with YAML-frontmatter solution documents and grep-first search. This section covers only the lightweight within-run variant. If COMPOUND-001 is approved, this becomes a stepping stone toward that system.

**Current**: Each error analyzed independently (`runner.py:109-129`).
**Proposed**: Maintain a `run_context` dict that accumulates codebase patterns discovered during analysis. Feed as additional context to subsequent errors.

```python
# Conceptual flow (modifies runner.py analysis loop)
run_context = {"patterns_discovered": [], "files_examined": set()}

for error in top_errors:
    result = analyze_error(error, traces, github_client=gh, newrelic_client=nr,
                           run_context=run_context)
    run_context["patterns_discovered"].extend(result.learnings)
    run_context["files_examined"].update(result.files_read)
```

**Effort**: Small. Add optional `run_context` parameter to `analyze_error()`. Inject into system prompt.

### 4.4 Story Decomposition for Complex Fixes (Priority: Low)

**Current**: One analysis produces one PR with all changes.
**Proposed**: For complex fixes, decompose into ordered sub-tasks and implement each in sequence with fresh context.

**Effort**: Large. Requires planning step, task tracking, multi-commit workflow. Overkill for NightWatch's current scope.

---

## 5. Recommendation

### Adopt the Pattern (not the package)

| Option | Decision | Rationale |
|--------|----------|-----------|
| Add Ralph as dependency | **No** | Ralph is a Bash script, not a library |
| Copy `ralph.sh` into NightWatch | **No** | Redundant; NightWatch already has Python orchestration |
| Implement Ralph's *patterns* natively | **Yes** | Multi-pass, quality gates, and progress accumulation fit naturally into the existing pipeline |
| Full story decomposition | **Not yet** | Overkill for error analysis |

### Implementation Priority

| Phase | Enhancement | Effort | Value |
|-------|------------|--------|-------|
| **Phase 1** | Multi-pass analysis for low-confidence results | 2-4 hours | High |
| **Phase 1** | Run context accumulation across errors | 1-2 hours | Medium |
| **Phase 2** | Quality gate for generated PRs | 4-8 hours | High |
| **Phase 3** | Story decomposition (if needed) | 2-3 days | Low |

Phases 1-2: **~1 day** of implementation.

---

## 6. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Multi-pass doubles API costs | Medium | Low | Only retry on LOW confidence; cap at 2 passes |
| Run context grows too large for prompt | Low | Medium | Truncate to most recent N patterns; summarize |
| Quality gate requires target repo clone | Medium | Medium | Start with GitHub Actions status checks; clone later |
| Ralph project is new, may pivot | High | None | We adopt patterns, not code |

---

## 7. Alternatives Considered

**A. Use Ralph Directly (Rejected)**: Would require Claude Code CLI instead of Anthropic API, adding Bash orchestration on top of Python, and giving up control over the analysis loop.

**B. Do Nothing (Viable but Suboptimal)**: Single-shot analysis covers ~80% of cases, but the 20% of low-confidence results and broken PRs represent real lost value.

**C. Build Full Agent Loop Framework (Overkill)**: Generalized iterative agent framework with task decomposition, dependency graphs, and multi-agent coordination. Far beyond what error analysis needs.

---

## 8. Success Criteria

- Low-confidence analyses decrease by >30% after multi-pass retry
- Zero draft PRs with lint/typecheck failures (quality gate)
- Measurable in `RunReport` metrics (confidence distribution, PR pass rate)

---

## 9. References

- [Ralph GitHub Repository](https://github.com/snarktank/ralph)
- [NightWatch Architecture Proposal](../nightwatch-new-repo/proposal.md)
- [COMPOUND-001: Compound Engineering Patterns](../compound-engineering-patterns/proposal.md)

---

## 10. Cross-Reference: Overlap with COMPOUND-001

COMPOUND-001 (PR #1) proposes five patterns from the compound-engineering-plugin. Three overlap with this proposal:

| RALPH-001 Section | COMPOUND-001 Section | Overlap | Resolution |
|-------------------|---------------------|---------|------------|
| 4.1 Multi-Pass Analysis | 3.3 Research-Before-Analyze + 3.5 Phase 5 Multi-Perspective | Both address incomplete first-pass results. COMPOUND-001 pre-populates context; RALPH-001 retries after a weak pass. | **Complementary.** Implement both. |
| 4.3 Progress Accumulation | 3.1 Knowledge Compounding + 3.5 Autonomous Compound Loop | Both accumulate learnings across errors. COMPOUND-001 is far more comprehensive (persistent cross-run knowledge base). RALPH-001 proposes only a lightweight within-run dict. | **COMPOUND-001 subsumes this.** If approved, 4.3 becomes a stepping stone. If not, 4.3 stands alone. |
| 4.2 Quality Gate for PRs | (not covered) | COMPOUND-001 does not propose PR validation. | **Unique to RALPH-001.** Implement regardless. |
| 4.4 Story Decomposition | 3.2 Multi-Agent Parallel Analysis | Different approaches to complex errors (sequential stories vs parallel sub-agents). | **Both deferred.** Neither recommends implementing now. |

**If both proposals are approved**, unify the implementation plan:
- COMPOUND-001 Phase 1 (Knowledge Foundation) + RALPH-001 Phase 1 (Multi-Pass) should be a single effort.
- RALPH-001 Phase 2 (Quality Gate) is independent and should proceed regardless.
