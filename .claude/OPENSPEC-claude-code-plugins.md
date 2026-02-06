# OpenSpec Proposal: Claude Code Plugin Adoption Strategy

**ID**: PLUGIN-001
**Status**: Draft / Awaiting Approval
**Author**: Claude (AI Assistant)
**Date**: 2026-02-05
**Scope**: Claude Code plugin configuration (user + project scope)

---

## 1. Problem Statement

NightWatch development currently relies on manual tool invocations, grep-based code navigation, and ad-hoc workflows for common operations like commits, PR reviews, and security checks. Claude Code's official plugin marketplace offers pre-built extensions that address these gaps:

- **No LSP intelligence**: Claude edits Python files without real-time type error detection — Pydantic model errors, missing imports, and type mismatches are only caught at runtime or via manual `ruff`/`pyright` invocation
- **No automated security scanning**: NightWatch processes untrusted production error data (stack traces, exception messages) but has no automatic guardrails against introducing `eval()`, `pickle.loads()`, `os.system()`, or injection patterns during development
- **No structured PR review**: Code reviews rely on single-pass human review — no parallel multi-agent analysis for type design, silent failures, or test coverage gaps
- **Manual git workflows**: Commit message generation, PR creation, and branch cleanup are manual operations that break development flow
- **No external service MCP integration**: NightWatch integrates with GitHub, Slack, and Sentry but Claude has no direct MCP access to these services during development

## 2. Proposal

Adopt a tiered set of Claude Code plugins from the **official Anthropic marketplace** (`claude-plugins-official`) and the **demo marketplace** (`anthropics/claude-code`) to enhance NightWatch development.

### Plugin Selection Criteria

Each plugin was evaluated against:

| Criterion | Weight | Description |
|-----------|--------|-------------|
| **NightWatch Relevance** | 40% | Direct alignment with project tech stack, architecture, and workflows |
| **Development Impact** | 25% | Measurable improvement to development speed, quality, or safety |
| **Maintenance Burden** | 20% | Dependencies required, configuration complexity, update frequency |
| **Risk** | 15% | Potential for interference, memory usage, false positives |

## 3. Tier 1 — Install Immediately (Critical)

These plugins address immediate gaps in the development workflow.

---

### 3.1 `pyright-lsp` — Python Code Intelligence

**Source**: `claude-plugins-official`
**Install**: `/plugin install pyright-lsp@claude-plugins-official`
**Scope**: User (applies to all Python projects)

#### What It Does

Connects Claude to the [Pyright](https://github.com/microsoft/pyright) language server via LSP (Language Server Protocol). After every file edit Claude makes, Pyright analyzes the changes and reports type errors, missing imports, unresolved references, and schema violations back to Claude automatically.

#### Why NightWatch Needs This

| Problem | How pyright-lsp Solves It |
|---------|--------------------------|
| Pydantic v2 model errors only caught at runtime | Real-time type validation on every edit across all 8 type modules (`nightwatch/types/*.py`) |
| Missing imports in 56+ Python files across 7 subpackages | Instant unresolved import detection without running the code |
| Agent base class protocol violations | Go-to-definition + find-references for `BaseAgent` hierarchy |
| Cross-module type mismatches (e.g., `AnalysisResult` used in `orchestration/pipeline.py`) | Hover type info + call hierarchy tracing |

#### Capabilities Gained

1. **Automatic diagnostics**: After every file edit, Claude sees type errors, missing imports, and syntax issues without running `ruff` or `pytest`. Self-corrects in the same turn.
2. **Code navigation**: Jump to definitions, find references, get type info on hover, list symbols, find implementations, trace call hierarchies — more precise than grep.

#### Dependency

```bash
pip install pyright
# or
npm install -g pyright
```

Verify: `pyright-langserver --version` must be in `$PATH`.

#### Risk Assessment

- **Memory**: Pyright can be memory-intensive on large projects. NightWatch (~8K LOC, 56 files) is well within safe bounds.
- **False positives**: Possible in monorepo/workspace configurations. NightWatch is a single-package project — minimal risk.

#### Score: 95/100

---

### 3.2 `security-guidance` — Security Pattern Detection

**Source**: `anthropics/claude-code` (demo marketplace)
**Install**: `/plugin install security-guidance@anthropics-claude-code`
**Scope**: Project (shared via `.claude/settings.json`)

#### What It Does

A hook-based plugin that monitors file edits for 9 dangerous code patterns:

| Pattern | Detection | NightWatch Relevance |
|---------|-----------|---------------------|
| Command injection | Shell commands with user input | **HIGH** — NightWatch builds shell-adjacent commands for analysis |
| `eval()` usage | Dynamic code execution | **HIGH** — Error analysis could tempt eval patterns |
| Pickle deserialization | `pickle.loads()` / `pickle.load()` | **HIGH** — Data persistence layer must avoid pickle |
| `os.system()` calls | Direct OS command execution | **HIGH** — subprocess patterns must use `subprocess.run()` |
| XSS attacks | Unescaped HTML output | LOW — no web UI |
| Dangerous HTML | Raw HTML generation | LOW — no web UI |
| SQL injection | Unsanitized query construction | MEDIUM — no direct SQL but possible future DB layer |
| Path traversal | `../` patterns in file operations | **HIGH** — validation layer already has `path_safety.py` |
| Hardcoded secrets | API keys, passwords in source | **HIGH** — project uses 8+ environment variables |

#### Why NightWatch Needs This

NightWatch processes untrusted production data (error messages, stack traces, exception payloads) and generates code patches. The security-guidance plugin creates a **defense-in-depth layer** that catches dangerous patterns at edit-time, complementing the existing `validation/layers/path_safety.py` runtime layer.

#### Implementation

Plugin activates as a `PostToolUse` hook on file edits. No configuration required — zero-maintenance.

#### Score: 92/100

---

### 3.3 `github` — GitHub MCP Integration

**Source**: `claude-plugins-official`
**Install**: `/plugin install github@claude-plugins-official`
**Scope**: User

#### What It Does

Bundles a pre-configured GitHub MCP server giving Claude direct API access to:
- Repository management (files, branches, commits)
- Issues (create, read, update, search, comment)
- Pull requests (create, review, merge, list reviews)
- Actions/CI (list workflows, view run logs)
- Search (code search, issue search across repos)

#### Why NightWatch Needs This

NightWatch already has deep GitHub integration:
- `nightwatch/github.py` — GitHub API client for creating issues and draft PRs
- `PyGithub>=2.1.0` dependency
- `GITHUB_TOKEN` + `GITHUB_REPO` environment variables
- Issue/PR creation is a core output of the analysis pipeline

This plugin gives Claude **development-time** GitHub access to:
1. Investigate existing issues before creating duplicates during NightWatch testing
2. Review PR history and comments for context when modifying `github.py`
3. Search code across the target repo (`g2crowd/ue`) to understand patterns NightWatch analyzes
4. List CI workflow results to debug NightWatch's correlation engine (`nightwatch/correlation.py`)

#### Score: 90/100

---

### 3.4 `commit-commands` — Git Workflow Automation

**Source**: `claude-plugins-official`
**Install**: `/plugin install commit-commands@claude-plugins-official`
**Scope**: User

#### What It Does

Provides three slash commands:
- `/commit-commands:commit` — Stage changes, generate AI commit message, create commit
- `/commit-commands:push-pr` — Commit + push + create PR in one step
- `/commit-commands:clean-gone` — Clean up local branches whose remotes have been deleted

#### Why NightWatch Needs This

NightWatch follows a feature-branch workflow with 6 planned feature branches:

| Branch | Feature |
|--------|---------|
| `feature/knowledge-foundation` | Phase 1: Knowledge Base |
| `feature/analysis-enhancement` | Phase 2: Analysis |
| `feature/quality-gates` | Phase 3: Validation |
| `feature/compound-intelligence` | Phase 4: Compound |
| `feature/health-report` | Phase 5: Self-Health |

Automated commit + PR creation accelerates the multi-phase development plan. Branch cleanup keeps the workspace clean between phases.

#### Score: 85/100

---

## 4. Tier 2 — Install for Active Development (High Value)

These plugins provide significant value during active feature development and code review cycles.

---

### 4.1 `pr-review-toolkit` — Multi-Agent PR Review

**Source**: `claude-plugins-official`
**Install**: `/plugin install pr-review-toolkit@claude-plugins-official`
**Scope**: User

#### What It Does

Runs **6 specialized parallel Sonnet agents** for comprehensive PR review:

| Agent | Focus | NightWatch Value |
|-------|-------|-----------------|
| `comment-analyzer` | Code comment quality | MEDIUM — ensures docstrings on agents and workflows |
| `pr-test-analyzer` | Test coverage gaps | **HIGH** — enforces 85% coverage requirement |
| `silent-failure-hunter` | Error handling issues | **CRITICAL** — NightWatch must handle API failures gracefully |
| `type-design-analyzer` | Type system review | **CRITICAL** — 8 Pydantic type modules require correct design |
| `code-reviewer` | General quality | HIGH — catches SOLID violations |
| `code-simplifier` | Complexity reduction | HIGH — keeps agent code maintainable |

#### Why NightWatch Needs This

The `silent-failure-hunter` and `type-design-analyzer` agents are especially valuable:

- **Silent failures**: NightWatch makes API calls to New Relic, GitHub, Slack, and Anthropic. Silent failure in any of these paths means errors go undetected in production. The hunter agent specifically looks for swallowed exceptions, missing error handling, and unvalidated API responses.
- **Type design**: The `nightwatch/types/` directory contains 8 Pydantic model modules that define the entire data contract layer. Incorrect type design propagates through the orchestration pipeline.

#### Usage

```
/pr-review-toolkit:review-pr              # Run all agents
/pr-review-toolkit:review-pr --types      # Type design only
/pr-review-toolkit:review-pr --errors     # Silent failure hunting only
```

#### Score: 88/100

---

### 4.2 `slack` — Slack MCP Integration

**Source**: `claude-plugins-official`
**Install**: `/plugin install slack@claude-plugins-official`
**Scope**: User

#### What It Does

Bundles a pre-configured Slack MCP server for channel messaging, user lookup, and workspace interaction.

#### Why NightWatch Needs This

NightWatch has a Slack integration layer:
- `nightwatch/slack.py` — Slack bot client for daily DM reports
- `slack-sdk>=3.27.0` dependency
- `SLACK_BOT_TOKEN` + `SLACK_NOTIFY_USER` environment variables

Direct MCP access allows Claude to:
1. Test Slack message formatting during `slack.py` development
2. Verify bot token permissions and scopes
3. Preview DM report output formatting
4. Debug Slack API responses during `/troubleshoot` sessions

#### Score: 82/100

---

### 4.3 `sentry` — Error Monitoring Integration

**Source**: `claude-plugins-official`
**Install**: `/plugin install sentry@claude-plugins-official`
**Scope**: User

#### What It Does

Bundles a pre-configured Sentry MCP server for error tracking, issue management, and performance monitoring.

#### Why NightWatch Needs This

NightWatch is an "AI-powered production error analysis" system. Sentry is a direct peer in the monitoring ecosystem. MCP access enables:

1. **Cross-reference**: Compare Sentry error groups with NightWatch's New Relic-sourced errors to validate coverage
2. **Pattern validation**: Check if NightWatch's `pattern_detector` agent identifies the same patterns Sentry surfaces
3. **Integration opportunity**: Future `nightwatch/sentry.py` integration module for multi-source error ingestion
4. **Testing**: Use real Sentry error data to validate NightWatch's analysis quality

#### Score: 80/100

---

### 4.4 `code-review` — Confidence-Scored Code Review (Demo Marketplace)

**Source**: `anthropics/claude-code` (demo marketplace)
**Install**: `/plugin install code-review@anthropics-claude-code`
**Scope**: User

#### What It Does

Automated PR code review using **5 parallel Sonnet agents** with confidence-based scoring to filter false positives:

| Agent | Focus |
|-------|-------|
| CLAUDE.md compliance | Adherence to project conventions |
| Bug detection | Logical errors and regressions |
| Historical context | Git history analysis |
| PR history | Review pattern consistency |
| Code comments | Documentation quality |

**Key differentiator**: Confidence scoring filters out low-confidence findings, reducing review noise.

#### Why NightWatch Needs This

Complements `pr-review-toolkit` with a different review philosophy:
- `pr-review-toolkit`: 6 specialized agents focused on code aspects (types, errors, tests)
- `code-review`: 5 agents focused on project context (CLAUDE.md compliance, git history, bug patterns)

Together they provide comprehensive review coverage.

#### Score: 78/100

---

## 5. Tier 3 — Install When Needed (Situational)

These plugins provide value in specific scenarios.

---

### 5.1 `agent-sdk-dev` — Anthropic SDK Development Tools

**Source**: `claude-plugins-official`
**Install**: `/plugin install agent-sdk-dev@claude-plugins-official`
**Scope**: User

**When to install**: When modifying `nightwatch/agents/`, `nightwatch/analyzer.py`, or `nightwatch/prompts.py`

Includes `agent-sdk-verifier-py` — validates Python applications against Anthropic SDK best practices. NightWatch depends on `anthropic>=0.77.0` and has its own agent system. The verifier can validate API usage patterns, tool definition correctness, and conversation management.

#### Score: 70/100

---

### 5.2 `hookify` — Custom Hook Generator

**Source**: `anthropics/claude-code` (demo marketplace)
**Install**: `/plugin install hookify@anthropics-claude-code`
**Scope**: User

**When to install**: When establishing NightWatch-specific development guardrails

Use cases:
- Prevent commits without corresponding test files
- Enforce Pydantic model conventions in `nightwatch/types/`
- Auto-run `ruff check` after Python file edits
- Block edits to `nightwatch/validation/layers/path_safety.py` without security review

#### Score: 68/100

---

### 5.3 `feature-dev` — Structured Feature Development

**Source**: `anthropics/claude-code` (demo marketplace)
**Install**: `/plugin install feature-dev@anthropics-claude-code`
**Scope**: User

**When to install**: When beginning a new major NightWatch feature (new agent type, new workflow, new integration)

Provides a 7-phase development workflow with `code-explorer`, `code-architect`, and `code-reviewer` agents. Useful for the 6 planned implementation phases in `docs/features/README.md`.

#### Score: 65/100

---

### 5.4 `plugin-dev` — Plugin Development Toolkit

**Source**: `claude-plugins-official`
**Install**: `/plugin install plugin-dev@claude-plugins-official`
**Scope**: User

**When to install**: Only if creating a custom `nightwatch-dev` plugin (see Section 8)

Provides an 8-phase guided workflow for building plugins with agents for creation, validation, and review.

#### Score: 55/100

---

## 6. Not Recommended

These plugins were evaluated and excluded.

| Plugin | Source | Reason for Exclusion |
|--------|--------|---------------------|
| `clangd-lsp`, `gopls-lsp`, `rust-analyzer-lsp`, etc. | Official | NightWatch is Python-only |
| `typescript-lsp` | Official | No TypeScript in project |
| `figma` | Official | No UI/design work — NightWatch is a CLI/agent system |
| `frontend-design` | Demo | No frontend |
| `vercel`, `firebase`, `supabase` | Official | Not NightWatch's deployment stack |
| `learning-output-style` | Official | Educational tool — not a productivity tool for active development |
| `explanatory-output-style` | Official | Educational — adds overhead to every response |
| `ralph-wiggum` | Demo | Niche iterative loop tool — SuperClaude `--loop` flag covers this |
| `claude-opus-4-5-migration` | Demo | Only relevant during model version migration — install ad-hoc if needed |
| `atlassian`, `asana`, `linear`, `notion` | Official | No evidence NightWatch uses these PM tools |
| `gitlab` | Official | NightWatch uses GitHub, not GitLab |

## 7. Implementation Plan

### Phase 1: Marketplace Setup (5 minutes)

```bash
# Add the demo marketplace (official marketplace is auto-available)
/plugin marketplace add anthropics/claude-code
```

### Phase 2: Tier 1 Installation (10 minutes)

```bash
# Prerequisites
pip install pyright  # or: npm install -g pyright

# Install Tier 1 plugins
/plugin install pyright-lsp@claude-plugins-official
/plugin install security-guidance@anthropics-claude-code
/plugin install github@claude-plugins-official
/plugin install commit-commands@claude-plugins-official
```

**Post-install verification**:
1. Open a NightWatch Python file — pyright diagnostics should appear on edit
2. Check `/plugin` Errors tab for any "Executable not found" warnings
3. Verify `pyright-langserver --version` is accessible

### Phase 3: Tier 2 Installation (5 minutes)

```bash
/plugin install pr-review-toolkit@claude-plugins-official
/plugin install slack@claude-plugins-official
/plugin install sentry@claude-plugins-official
/plugin install code-review@anthropics-claude-code
```

### Phase 4: Configuration

#### Project-Scope Plugin (`.claude/settings.json`)

Install `security-guidance` at project scope so all NightWatch developers get security pattern detection:

```bash
/plugin install security-guidance@anthropics-claude-code --scope project
```

#### CLAUDE.md Updates

Add to project `CLAUDE.md`:

```markdown
## Plugins
- pyright-lsp: Python type intelligence — diagnostics auto-run after edits
- security-guidance: Monitors for dangerous patterns (eval, pickle, os.system, injection)
- pr-review-toolkit: Use `/pr-review-toolkit:review-pr` before merging PRs
- commit-commands: Use `/commit-commands:commit` for AI-generated commit messages
```

## 8. Future Opportunity: Custom `nightwatch-dev` Plugin

Based on NightWatch's architecture, a project-specific plugin could bundle:

### Skills
- `nightwatch-agent-pattern` — Documents the `BaseAgent` → `@register_agent` → `AgentConfig` pattern
- `nightwatch-validation-layer` — Documents the 5-layer validation orchestrator pattern
- `nightwatch-workflow-pattern` — Documents `BaseWorkflow` → `@register_workflow` → pipeline integration

### Hooks
- `PostToolUse` on Write/Edit → Auto-run `ruff check --fix` on modified Python files
- `PostToolUse` on Write/Edit → Auto-run `pyright` on modified files (if pyright-lsp not installed)
- `PreToolUse` on Write to `nightwatch/validation/layers/` → Require explicit confirmation

### Agents
- `nightwatch-type-reviewer` — Validates Pydantic models follow project conventions
- `nightwatch-agent-verifier` — Checks new agents implement required `BaseAgent` interface

### Implementation

Use `plugin-dev` toolkit (Tier 3) to scaffold, then customize:
```bash
/plugin install plugin-dev@claude-plugins-official
/plugin-dev:create-plugin
```

**Scope**: Project (committed to `.claude/settings.json`)
**Estimated effort**: 2-3 hours

---

## 9. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Pyright high memory usage | Low (8K LOC project) | Medium | `/plugin disable pyright-lsp` if memory issues |
| Security-guidance false positives | Medium | Low | Review flagged patterns — false positives are educational |
| Plugin conflicts with SuperClaude | Low | Medium | Plugins and SuperClaude operate at different layers (hooks vs. prompts) |
| Marketplace plugins change/break | Low | Medium | Pin to specific versions; test after auto-updates |
| Too many plugins slow session start | Low | Low | Tier 1 only = 4 plugins — well within safe bounds |

## 10. Success Criteria

| Metric | Baseline (Current) | Target (Post-Plugin) |
|--------|-------------------|---------------------|
| Type errors caught before runtime | Manual (`ruff` invocation) | Automatic on every edit |
| Security pattern detection | None (manual review) | Automatic on every edit |
| PR review depth | Single-pass human review | 6-11 parallel agent review |
| Commit workflow steps | 3-5 manual commands | 1 slash command |
| GitHub context during development | `gh` CLI only | Full MCP API access |

## 11. Resolved Decisions

1. **Plugin scope**: User scope for most plugins, project scope for `security-guidance` (shared safety)
2. **Demo marketplace**: Yes — add `anthropics/claude-code` for `security-guidance` and `code-review`
3. **Auto-updates**: Enable for official marketplace, disable for demo marketplace (review changes manually)
4. **Tier approach**: Phased adoption prevents overwhelm — Tier 1 first, Tier 2 after validation
5. **Custom plugin**: Deferred — evaluate after Tier 1+2 adoption proves value

---

**Status**: Draft / Awaiting Approval
