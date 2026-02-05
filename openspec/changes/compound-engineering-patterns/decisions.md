# Decisions Log: Compound Engineering Patterns

**Proposal**: COMPOUND-001
**Date**: 2026-02-05

---

## Open Decisions

### D1: Knowledge Base Location

**Question**: Where should NightWatch store its persistent knowledge?

| Option | Pros | Cons |
|--------|------|------|
| `nightwatch/knowledge/` | Git-trackable, project-local, easy to inspect | Grows repo size over time |
| `~/.nightwatch/knowledge/` | Doesn't pollute repo, persists across clones | Not shareable, not version-controlled |
| `knowledge/` at repo root | Visible, easy to find | Mixes with source code |

**Recommendation**: `nightwatch/knowledge/` — git-tracked, team-shareable. The whole point of compound engineering is that knowledge compounds across the team, not just one machine.

**Status**: PENDING

---

### D2: Git-Track Knowledge Documents?

**Question**: Should solution documents be committed to git?

| Option | Pros | Cons |
|--------|------|------|
| Yes, git-tracked | Team shares learnings, knowledge survives machine changes | Repo growth, potentially sensitive error details |
| No, git-ignored | No repo bloat, error details stay local | Knowledge doesn't compound across team |
| Hybrid: git-track patterns, ignore raw errors | Best of both — patterns shared, raw data local | More complex setup |

**Recommendation**: **Hybrid** — `knowledge/patterns/` is git-tracked (shared team knowledge), `knowledge/errors/` is git-ignored (may contain sensitive error details, stack traces, etc.)

**Status**: PENDING

---

### D3: Phase 5 Multi-Agent Analysis

**Question**: Should we implement multi-perspective analysis now or defer?

**Recommendation**: **Defer** — The current single-agent analysis works. Multi-agent adds API cost and complexity. Implement Phases 1-4 first, measure the impact of knowledge compounding on analysis quality, then decide if additional perspectives are needed.

**Status**: PENDING

---

### D4: Agent Configuration Format

**Question**: What format for configurable agent definitions?

| Option | Pros | Cons |
|--------|------|------|
| Markdown + YAML frontmatter | Human-readable, matches compound-engineering pattern | Custom parser needed |
| Pure YAML | Simple parsing, widely supported | Less readable for long prompts |
| Python files | Full flexibility, type safety | Requires Python knowledge to configure |

**Recommendation**: **Markdown + YAML frontmatter** — This is the pattern proven by compound-engineering. System prompts are naturally prose (Markdown). Configuration metadata is naturally structured (YAML). The combination is elegant and simple to parse with `pyyaml` (already a project dependency).

**Status**: PENDING

---

### D5: Knowledge Search Timing

**Question**: When should NightWatch search its knowledge base?

| Option | Pros | Cons |
|--------|------|------|
| Before analysis (inject in initial prompt) | Cheaper, reduces iterations | Adds to initial prompt size |
| During analysis (as a tool) | Claude decides when to search | Uses tool iterations, more API calls |
| Both | Maximum flexibility | Complexity, potential redundancy |

**Recommendation**: **Before analysis** — inject as context in the initial prompt. This is cheaper (no tool-use iterations spent on knowledge lookup) and ensures Claude always has prior context. The compound-engineering `learnings-researcher` runs as a pre-planning step, not during the main work loop.

**Status**: PENDING

---

### D6: Pattern Detection Frequency

**Question**: When should cross-error patterns be detected?

| Option | Pros | Cons |
|--------|------|------|
| Per-run | Immediate feedback, simple | May not have enough data in single run |
| Periodic batch (weekly) | More data, better patterns | Delayed feedback, needs scheduler |
| Both | Immediate + periodic | Complexity |

**Recommendation**: **Per-run** — detect patterns at the end of each run. Even with 3-5 errors per run, patterns can emerge (e.g., "2 of 5 errors are external API timeouts"). For cross-run patterns, the knowledge base search in Phase 1 naturally surfaces recurring issues.

**Status**: PENDING

---

## Resolved Decisions

*None yet — awaiting proposal approval.*
