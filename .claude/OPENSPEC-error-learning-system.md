# OpenSpec Proposal: Persistent Error Learning System

**ID**: LEARN-001
**Status**: Draft / Awaiting Approval
**Author**: Claude (AI Assistant)
**Date**: 2026-02-05
**Scope**: Local `.claude` configuration (git-ignored)

---

## 1. Problem Statement

When Claude encounters, debugs, or analyzes errors during development sessions, the diagnosis, root cause, and resolution are lost when the conversation ends. This means:

- The same errors get re-investigated from scratch across sessions
- Patterns in recurring failures are never surfaced
- Project-specific gotchas aren't accumulated anywhere
- No institutional memory builds over time

## 2. Proposal

Create a **git-ignored** local directory at `.claude/errors/` within each project's `.claude` directory. Each error encounter produces a structured `.md` report that persists across sessions and becomes a searchable knowledge base.

### Directory Structure

```
<project-root>/
└── .claude/
    ├── settings.local.json          # (existing)
    └── errors/                      # NEW - git-ignored
        ├── README.md                # Index of all error reports
        ├── 2026-02-05_001_import-resolution-failure.md
        ├── 2026-02-05_002_type-mismatch-config-loader.md
        └── ...
```

### Git Ignore Rule

Add to project `.gitignore`:

```
# Claude local error learning (machine-generated, session-specific)
.claude/errors/
```

This keeps error reports **local-only** — they contain machine-specific paths, environment details, and potentially sensitive stack traces that shouldn't be committed.

## 3. Error Report Schema

Each `.md` file follows this structure:

```markdown
# Error Report: <Short Title>

**ID**: YYYY-MM-DD_NNN
**Date**: YYYY-MM-DD HH:MM
**Severity**: critical | high | medium | low
**Category**: <see categories below>
**Status**: resolved | mitigated | recurring | open

---

## Trigger

What action or command caused the error to surface.

## Error Output

The raw error message, traceback, or failure output (truncated if excessive).

## Root Cause

The underlying reason the error occurred. Evidence-based — what was actually wrong.

## Resolution

What fixed it, or what workaround was applied.

## Prevention

How to avoid this error in the future. Could include:
- Configuration changes
- Code patterns to avoid
- Dependencies to watch
- Pre-flight checks

## Fix Commit

Git commit SHA that resolved this error (added after commit):
- `abc1234` — <commit message summary>

## Related

- Links to other error reports with similar root causes
- Relevant files/modules
- External references (docs, issues, etc.)

## Tags

Freeform tags for searchability, e.g.: `python`, `import`, `config`, `runtime`, `build`, `test`
```

### Error Categories

| Category | Description |
|----------|-------------|
| `build` | Compilation, bundling, packaging failures |
| `runtime` | Errors during execution |
| `import` | Module resolution, dependency issues |
| `config` | Configuration parsing, env vars, settings |
| `type` | Type mismatches, schema violations |
| `test` | Test failures, assertion errors |
| `network` | API calls, connectivity, timeouts |
| `permission` | File system, auth, access control |
| `environment` | Python version, OS, toolchain issues |
| `logic` | Incorrect behavior, wrong output |
| `integration` | Cross-module or cross-service failures |

## 4. Operational Behavior

### When Claude Should Write an Error Report

1. **During `/troubleshoot`** — Every troubleshooting session produces a report
2. **During `/build` failures** — All build errors, including trivial ones
3. **During `/test` failures** — All test failures regardless of severity
4. **During `/analyze` with errors** — When analysis uncovers error-prone code
5. **Any ad-hoc debugging** — When the user asks to fix a bug or investigate an issue
6. **Trivial errors too** — Typos, missing commas, wrong imports — everything gets captured. Small errors reveal patterns at scale
6. **Recurring patterns** — When Claude recognizes it has seen this error before (from reading existing reports)

### When Claude Should Read Error Reports

1. **Session start** — Scan `errors/README.md` index for awareness (lightweight)
2. **Before debugging** — Search existing reports for matching symptoms
3. **Before `/troubleshoot`** — Check if this error category has prior reports
4. **When stuck** — Review related reports for alternative approaches

### Index Maintenance (`README.md`)

The `errors/README.md` serves as a quick-scan index:

```markdown
# Error Knowledge Base

## Summary
- Total reports: 12
- Last updated: 2026-02-05

## Recent (Last 5)
| ID | Title | Category | Status |
|----|-------|----------|--------|
| 2026-02-05_002 | Type mismatch in config loader | type | resolved |
| 2026-02-05_001 | Import resolution failure | import | resolved |

## By Category
### build (3)
- [2026-01-20_001](./2026-01-20_001_webpack-chunk-error.md) - resolved
...

### Recurring Issues
- **Config path resolution** — seen 3 times (reports: 001, 005, 009)
```

## 5. File Naming Convention

```
YYYY-MM-DD_NNN_<slug>.md
```

- `YYYY-MM-DD` — Date of occurrence
- `NNN` — Sequential counter for that day (001, 002, ...)
- `<slug>` — Lowercase, hyphenated short description (max 50 chars)

Examples:
- `2026-02-05_001_import-resolution-failure.md`
- `2026-02-05_002_type-mismatch-config-loader.md`
- `2026-02-06_001_pytest-fixture-scope-error.md`

## 6. Integration with Existing Systems

### MEMORY.md Integration

The project's `MEMORY.md` (in Claude's auto memory) should reference the error system:

```markdown
## Error Learning System
- Error reports are stored in `<project>/.claude/errors/`
- Always check existing reports before debugging
- Write a report after every non-trivial error resolution
- See .claude/OPENSPEC-error-learning-system.md for schema
```

### SuperClaude Integration

- **`/troubleshoot`** — Auto-generates error report on resolution
- **`/analyze`** — References error reports for context
- **`/load`** — Includes error index in project context loading
- **`--persona-analyzer`** — Reads error history for pattern recognition

### CONTEXT_MANAGEMENT.md Integration

Error reports are lightweight enough to survive context limits. When creating feature specs at context boundaries, reference relevant error report IDs rather than duplicating content.

## 7. Privacy & Security Considerations

- Reports are **git-ignored** — never committed to shared repos
- May contain **local paths**, **env var names**, **stack traces** — all local-only
- No secrets should be included (API keys, passwords) — sanitize if present in error output
- Reports are **per-machine, per-developer** — not shared across team

## 8. Implementation Steps

1. Create `.claude/errors/` directory in project
2. Add `.claude/errors/` to `.gitignore`
3. Create initial `errors/README.md` index
4. Update project `MEMORY.md` with error system reference
5. Begin writing reports on next error encounter

## 9. Success Criteria

- Reduced time-to-resolution for recurring errors
- Pattern detection across sessions (e.g., "this is the 3rd config path issue")
- Searchable local knowledge base that grows with project maturity
- No impact on git history or repo size

## 10. Resolved Decisions

1. **Cross-project errors**: **No** — errors stay project-local only. No global `~/.claude/errors/`.
2. **Archival policy**: **No archival** — reports are kept indefinitely. The knowledge compounds.
3. **Auto-linking**: **Yes** — reports should reference the git commit SHA that introduced the fix when available.
4. **Severity threshold**: **All errors** — capture everything, including trivial ones. Small errors reveal patterns at scale.

---

**Status**: APPROVED (2026-02-05)
