# OpenSpec Proposal: compound-product Integration

**ID**: CP-001
**Status**: Approved
**Author**: Claude (AI Assistant)
**Date**: 2026-02-05
**Scope**: Development workflow tooling / autonomous improvement loop
**Repository Under Review**: https://github.com/snarktank/compound-product
**Related**: [COMPOUND-001](../changes/compound-engineering-patterns/proposal.md) (complementary — see Section 10)

---

## 1. Executive Summary

**compound-product** is a shell-based autonomous improvement pipeline that reads daily reports, identifies the #1 actionable priority via LLM analysis, generates a PRD with granular tasks, and iteratively implements fixes through an AI coding agent — producing a GitHub PR for human review.

NightWatch is a batch CLI tool that analyzes production errors and creates GitHub issues + draft PRs. The two tools share a philosophical ancestor (Ryan Carson's "compound engineering") and a common goal: **autonomous nightly improvement with human review in the morning.**

This proposal evaluates whether compound-product should be adopted to wrap or augment NightWatch's own development workflow.

---

## 2. Problem Statement

NightWatch improves *other* codebases by analyzing their production errors, but has no automated self-improvement loop:

1. **No operational triage** — Run failures (API timeouts, token limits, bad analyses) aren't triaged systematically
2. **No health metrics** — Run success rates, token costs, analysis quality, PR acceptance rates are not tracked
3. **Ad-hoc prioritization** — Deciding what to improve next in NightWatch is manual
4. **No autonomous fix pipeline** — Known issues require a human to start an implementation session

compound-product closes this loop: NightWatch emits a daily self-report, compound-product reads it, picks the highest-impact issue, and ships a PR to fix it.

---

## 3. What compound-product Does

### Architecture
```
Daily Report (.md)
    │
    ▼
analyze-report.sh ──→ LLM API ──→ Priority JSON (single highest-impact item)
    │
    ▼
AI Agent + PRD Skill ──→ PRD Markdown (requirements, acceptance criteria)
    │
    ▼
AI Agent + Tasks Skill ──→ prd.json (8-15 granular, verifiable tasks)
    │
    ▼
loop.sh ──→ AI Agent iterates (implement → typecheck → test → commit)
    │         up to 25 iterations, stateless between each
    ▼
auto-compound.sh ──→ git branch + GitHub PR for human review
```

### Key Properties
- **Pure shell scripts** — No runtime dependencies beyond bash, jq, gh, curl
- **Agent-agnostic** — Supports Amp CLI, Claude Code, Codex CLI, VS Code Copilot
- **LLM-provider-agnostic** — Vercel AI Gateway, Anthropic, OpenAI, OpenRouter for analysis
- **Skills as prompts** — PRD and task decomposition are markdown instruction files, not code
- **Safety by design** — All changes go through PRs; quality checks run before commits; iteration limits prevent runaway loops
- **Deduplication** — Scans recent PRDs to avoid re-picking already-addressed items

---

## 4. Fitness Assessment for NightWatch

### 4.1 Strong Alignment

| Factor | Assessment |
|--------|------------|
| **Shared philosophy** | Both tools embody "nightly autonomous loop + morning human review" |
| **Compatible stack** | compound-product wraps Claude Code, which NightWatch already uses for development |
| **PR-based safety** | Both produce PRs for human review — no autonomous merging |
| **Batch-oriented** | Both are cron/launchd tools, not servers |
| **Low coupling** | compound-product reads a markdown report and produces a PR — zero integration with NightWatch internals |

### 4.2 Natural Integration Point

NightWatch could generate a **self-health report** as part of its nightly run. The report would mirror data already available in `RunReport` (`runner.py:138-148`): `total_errors_found`, `errors_analyzed`, `total_tokens_used`, `run_duration_seconds`, plus failure/exception details logged during the run. This is ~200 LOC to serialize `RunReport` to structured markdown.

compound-product reads this report, picks the highest-impact item, generates a PRD, implements a fix, and opens a PR.

> **Note**: COMPOUND-001 Phase 1 (Knowledge Foundation) proposes persisting analysis results as solution documents. The self-health report proposed here is complementary — it reports on NightWatch's *operational health* (run metrics, failures), not its *analysis outputs*.

---

## 5. Risk Assessment

### 5.1 Critical Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **No license** | **CRITICAL** | The repo has no license file. Legally, the code is "all rights reserved." Cannot use without explicit permission from snarktank. **Blocker until resolved.** |
| **Bus factor = 1** | High | Single contributor (snarktank), 33 commits, 13 days old. If abandoned, we're on our own. Mitigation: fork and maintain locally. |
| **No releases/versioning** | High | No semantic versioning, no changelog. Breaking changes could land at any time. Mitigation: pin to a specific commit SHA. |
| **No test suite** | Medium | The compound-product scripts themselves have zero tests. Failures are discovered at runtime. Mitigation: add our own integration tests around the scripts. |

### 5.2 Moderate Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Shell fragility** | Medium | Pure bash can be brittle across environments. Mitigation: run in a controlled Docker container or fixed macOS environment. |
| **LLM cost opacity** | Medium | Each run = analysis API call + N agent iterations (each with multiple LLM calls). No built-in cost tracking. Mitigation: add token/cost logging wrapper. |
| **Recursive self-improvement** | Medium | An AI tool improving an AI tool could introduce subtle bugs that compound. Mitigation: strict human review of all compound-product PRs; never auto-merge. |
| **Security surface** | Medium | AI agents run with full file system access. Mitigation: run in isolated environment; PR review catches malicious changes. |

### 5.3 Low Risks

| Risk | Severity | Notes |
|------|----------|-------|
| **macOS-centric scheduling** | Low | launchd examples only. We already use launchd for NightWatch. |
| **Agent lock-in** | Low | Supports 4 agents. We use Claude Code, which is supported. |

---

## 6. Recommendation

### Verdict: **CONDITIONAL YES** — Adopt with Prerequisites

compound-product directly addresses NightWatch's lack of a self-improvement loop. The integration surface is minimal (a markdown report in, a PR out), and the safety model (PR-based review) matches NightWatch's existing workflow.

However, adoption is **blocked** until:

### Prerequisites (Must-Have)

1. **License resolution** — Contact snarktank or wait for a license to be added. Cannot legally use unlicensed code. This is a hard blocker.
2. **Pin to commit SHA** — Do not track `main`. Pin to a known-good commit and update deliberately.
3. **Self-health report generation** — NightWatch must emit a structured daily report about its own runs (new feature, ~200 LOC).

### Implementation Plan (Once Prerequisites Met)

**Phase 1: Report Generation** (1-2 hours)
- Add `--self-report` flag to NightWatch CLI
- Emit structured markdown report after each run
- Include: metrics, failures, quality signals, token costs
- Store in `reports/` directory (gitignored, last 30 days retained)

**Phase 2: compound-product Installation** (30 minutes)
- Install compound-product into NightWatch repo via `install.sh`
- Configure `compound.config.json`:
  - `report_dir`: `reports/`
  - `quality_checks`: `["uv run ruff check", "uv run pytest"]`
  - `max_iterations`: 15 (conservative start)
  - `agent`: `claude-code`
- Pin to specific commit SHA in install script

**Phase 3: Scheduling** (15 minutes)
- NightWatch runs at 2:00 AM (analyzes other repos' errors)
- compound-product runs at 4:00 AM (analyzes NightWatch's self-report)
- Morning: review compound-product's PR alongside NightWatch's PRs

**Phase 4: Validation** (1 week)
- Run for 7 days with mandatory human review of every PR
- Track: PR quality, false positives, token cost per run, duplicate suggestions
- Decide: continue, tune, or abandon

### What NOT to Do

- **Do not auto-merge** compound-product PRs. Ever. Human review is non-negotiable.
- **Do not let compound-product modify its own configuration** — scope it to NightWatch source only.
- **Do not run compound-product on production NightWatch** until Phase 4 validation passes.
- **Do not adopt if license is not resolved** — fork risk is acceptable, legal risk is not.

---

## 7. Alternatives Considered

| Alternative | Pros | Cons | Verdict |
|-------------|------|------|---------|
| **Manual improvement** | Full control, no new tooling | Slow, ad-hoc, no systematic triage | Current state, insufficient |
| **GitHub Copilot Workspace** | Integrated, no setup | Less autonomous, no report-driven triage | Viable but less targeted |
| **Custom Python script** | Full control, native to NightWatch stack | Reinventing compound-product's pipeline | Only if license blocks adoption |
| **Claude Code with custom CLAUDE.md** | Minimal setup, already available | No structured pipeline, no dedup, no iteration loop | Too unstructured for autonomous operation |

---

## 8. Success Metrics

After 30 days of operation:

| Metric | Target | Measurement |
|--------|--------|-------------|
| PRs generated | 15-25 (≈1/day) | GitHub API |
| PRs merged (useful) | >50% of generated | GitHub API |
| PRs rejected (bad) | <20% of generated | GitHub API |
| False positive rate | <30% | Manual tracking |
| Token cost per run | <$5 avg | Wrapper logging |
| Human review time | <10 min/PR avg | Self-report |
| NightWatch reliability improvement | Measurable reduction in run failures | Self-report comparison |

---

## 9. Decision Required

- [ ] **Approve**: Proceed with prerequisite checks (license inquiry first)
- [ ] **Reject**: NightWatch's self-improvement remains manual
- [ ] **Defer**: Revisit when compound-product reaches v1.0 or adds a license
- [ ] **Fork**: Fork compound-product now, add our own license, maintain independently

---

*This proposal will be updated when the license status of snarktank/compound-product is clarified.*

---

## 10. Cross-Reference: Relationship to COMPOUND-001 and RALPH-001

This proposal (CP-001) is complementary to, not in conflict with, the other two proposals:

| Concern | CP-001 (this) | COMPOUND-001 | RALPH-001 |
|---------|---------------|--------------|-----------|
| **Scope** | NightWatch improving *itself* | NightWatch improving *analysis quality* | NightWatch improving *analysis reliability* |
| **Mechanism** | External tool (compound-product) wraps NightWatch | Native Python knowledge system inside NightWatch | Native Python retry/quality patterns inside NightWatch |
| **Output** | PRs to NightWatch's own codebase | Better error analyses for target repos | Higher-confidence analyses + validated PRs |
| **Dependency** | License resolution on compound-product | None (pure pattern adoption) | None (pure pattern adoption) |

**If all three are approved**: COMPOUND-001 and RALPH-001 improve NightWatch's analysis pipeline. CP-001 then uses compound-product to improve NightWatch's *code* based on self-health reports. They operate at different layers and can coexist.

---

## 11. Path Inconsistency Note

> This proposal is located at `openspec/compound-product-integration/` while other proposals use `openspec/changes/*/`. This should be normalized to `openspec/changes/compound-product-integration/` for consistency. Deferring the move to avoid merge conflicts with this PR.
