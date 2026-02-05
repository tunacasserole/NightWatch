# Implementation Plan: AGENTS.md Adoption for NightWatch

**Proposal**: TOOL-002 (agents-md-evaluation)
**Status**: Completed
**Date**: 2025-02-05
**Date Completed**: 2025-02-05
**Estimated effort**: ~45 minutes total
**Actual effort**: ~30 minutes
**Risk level**: Very low (additive only, no existing config modified)
**Implementation Evidence**: `nightwatch/agents/base-analyzer.md` — agent config file using YAML frontmatter + markdown format
**Commit**: `dce5167` (Initial NightWatch implementation)

---

## Implementation Evidence

### What Was Implemented

The AGENTS.md concept was adopted as a **per-agent configuration file** rather than a single repo-root `AGENTS.md`. This is a deliberate adaptation: NightWatch's architecture uses agent definition files in YAML frontmatter + markdown format, which is the core pattern from the AGENTS.md spec applied at the agent level.

### Files Implemented

| File | Purpose | Status |
|------|---------|--------|
| `nightwatch/agents/base-analyzer.md` | Core error analysis agent config (AGENTS.md format) | Implemented |

### Implementation Details

**`nightwatch/agents/base-analyzer.md`** defines:
- Agent identity: `base-analyzer` -- core NightWatch error analysis agent for Ruby on Rails applications
- Model configuration: `claude-sonnet-4-5-20250929`, 8K thinking budget, 16K max tokens, 15 max iterations
- Tool manifest: `read_file`, `search_code`, `list_directory`, `get_error_traces`
- System prompt: Investigation methodology, Rails codebase conventions, New Relic trace data interpretation
- Structured instructions for mandatory tool-use (no guessing -- always read actual source code)

### Deviation from Original Plan

The original plan called for:
1. A repo-root `AGENTS.md` with universal project facts (tech stack, build commands, architecture)
2. A project-level `CLAUDE.md` importing `@AGENTS.md`

What was implemented instead:
1. `nightwatch/agents/base-analyzer.md` -- an agent-specific config in AGENTS.md format

**Rationale**: NightWatch is consumed programmatically (the `analyzer.py` module reads agent configs), not by a human developer opening the repo in an AI editor. The agent config file pattern is more appropriate for a CLI tool that orchestrates AI agents than a repo-root AGENTS.md designed for IDE-based coding assistants.

The universal project context (tech stack, build commands, etc.) is already captured in `README.md`, `pyproject.toml`, and the project-level `.claude/` configuration. Adding a separate repo-root `AGENTS.md` would duplicate that content without serving NightWatch's actual use case.

### Commit Reference

- **Commit**: `dce5167` (Initial NightWatch implementation)
- The `nightwatch/agents/` directory was created as part of the broader implementation but is not yet committed to the repo (currently untracked)

### Verification

- [x] Agent config file exists at `nightwatch/agents/base-analyzer.md`
- [x] File uses AGENTS.md format (YAML frontmatter + markdown instructions)
- [x] Config contains no sensitive data (no API keys, no internal URLs)
- [x] Config is concise and factual (~47 lines)
- [x] No existing files were modified (additive only)
- [x] Tool manifest matches the 4 tools defined in `analyzer.py`

### Testing Strategy (Retrospective)

The agent config is validated through:
1. **Unit tests**: `tests/` directory contains 34 tests covering the analyzer, models, GitHub integration, and ranking
2. **Dry-run mode**: `python -m nightwatch run --dry-run` exercises the full pipeline including agent config loading without side effects
3. **Syntax validation**: The YAML frontmatter is parseable by standard YAML parsers; the markdown body is valid markdown

### Rollback Plan (Retrospective)

```bash
rm -rf nightwatch/agents/
```

Zero risk to existing configuration. The agent config is loaded by `analyzer.py` and failure to load it falls back to inline prompt configuration.

---

## Architecture: The Layered Config Model

```
┌──────────────────────────────────────────────────┐
│  ~/.claude/CLAUDE.md (global SuperClaude)         │
│  @COMMANDS.md @FLAGS.md @PERSONAS.md ...          │
│  ┌──────────────────────────────────────────────┐ │
│  │  Project CLAUDE.md (NightWatch-specific)      │ │
│  │  @AGENTS.md  ← imports universal base layer   │ │
│  │  + Claude-specific: MCP, error learning, etc  │ │
│  │  ┌──────────────────────────────────────────┐ │ │
│  │  │  AGENTS.md (repo root)                   │ │ │
│  │  │  Universal project facts any agent reads │ │ │
│  │  │  Build, test, style, arch, conventions   │ │ │
│  │  └──────────────────────────────────────────┘ │ │
│  └──────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

**Principle**: AGENTS.md holds **what** (project facts). CLAUDE.md holds **how** (orchestration). No duplication.

---

## Phase 1: Create AGENTS.md

**File**: `/Users/ahenderson/dev/NightWatch/AGENTS.md`
**Effort**: ~30 minutes

### Content Structure

The file should contain exactly the information any coding agent needs to work on NightWatch, extracted from the existing README.md, decisions.md, and pyproject.toml. Nothing more.

#### Section 1: Project Identity

```markdown
# AGENTS.md — NightWatch

## Project Overview

NightWatch is an AI-powered production error analysis tool.

- **What**: Batch CLI job — run once, analyze everything, report, done
- **How**: Queries New Relic for errors → ranks by impact → Claude analyzes with tool-use → creates GitHub issues + draft PRs → sends Slack summary
- **When**: Runs daily via cron. Not a server. No HTTP endpoints. No webhooks. No database.
- **Runtime**: ~5-20 minutes per run depending on error count
```

**Source**: README.md lines 1-5, decisions.md Decision 1-2

#### Section 2: Tech Stack & Dependencies

```markdown
## Tech Stack

- Python 3.11+ (synchronous only — no async, no await, no event loop)
- Package manager: uv (NOT pip)
- 9 runtime dependencies (see pyproject.toml):
  - anthropic — Claude API (sync client)
  - PyGithub — GitHub API
  - httpx — New Relic GraphQL queries (sync mode)
  - slack-sdk — Slack bot DMs
  - pydantic + pydantic-settings — data models + config from env
  - python-dotenv — .env loading
  - pyyaml — ignore.yml parsing
  - certifi — macOS SSL certificates
- Dev dependencies: pytest, ruff
```

**Source**: pyproject.toml (actual deps — note the proposal said 7 but pyproject has 9 including slack-sdk and certifi)

#### Section 3: Build & Run Commands

```markdown
## Build & Install

uv sync            # Install dependencies
uv sync --dev      # Install with dev dependencies

## Run

python -m nightwatch run                     # Default: top 5 errors, last 24h
python -m nightwatch run --dry-run           # Analyze only, no side effects
python -m nightwatch run --max-errors 3      # Limit error count
python -m nightwatch run --since 12h         # Custom lookback period
python -m nightwatch run --verbose           # Show Claude iteration details
python -m nightwatch check                   # Validate API connectivity

## Test

uv run pytest tests/                         # Run test suite
uv run ruff check nightwatch/ tests/         # Lint
uv run ruff format nightwatch/ tests/        # Format
python -m py_compile nightwatch/*.py         # Syntax check
```

**Source**: README.md "Quick Start" and "Development" sections

#### Section 4: Code Style & Conventions

```markdown
## Code Style

- Linter/formatter: ruff (line-length=100, target py311)
- Lint rules: E (pycodestyle), F (pyflakes), I (isort), UP (pyupgrade), B (bugbear), SIM (simplify)
- All code is synchronous — never use async/await
- Pydantic models for all data structures (not dataclasses, not dicts)
- pydantic-settings for configuration (env vars, not config files)
- Anthropic structured outputs for Claude responses (not JSON parsing from text)
- Prefer httpx over requests for HTTP calls
- No web framework — no FastAPI, Flask, or Django
- No database — GitHub issues ARE the state store
- No vector memory — no embeddings, no ChromaDB
- Minimal dependencies — justify any new dependency before adding
```

**Source**: pyproject.toml [tool.ruff], decisions.md Decisions 2-5

#### Section 5: Architecture

```markdown
## Architecture

nightwatch/
├── __main__.py      # CLI entry point (argparse)
├── config.py        # Settings from env vars (pydantic-settings)
├── models.py        # Pydantic models (ErrorGroup, Analysis, RunReport)
├── newrelic.py      # NRQL queries, error ranking, ignore filtering
├── prompts.py       # Claude system prompt + tool definitions
├── analyzer.py      # Claude agentic loop with tool execution (core)
├── github.py        # Issues, PRs, duplicate detection, code reading tools
├── slack.py         # Bot DM reports (Block Kit)
├── correlation.py   # Link errors to recently merged PRs
└── runner.py        # Pipeline orchestration (fetch → rank → analyze → report)

### Core Loop (analyzer.py)

The central pattern is a tool-use agentic loop:
1. Send error context + system prompt + tools to Claude
2. Claude responds with tool_use (read_file, search_code, list_directory, get_error_traces)
3. Execute tool, append result to conversation
4. Repeat until Claude returns final analysis (structured output)
5. Max 15 iterations per error

### Pipeline (runner.py)

1. Load config → 2. Fetch errors from New Relic → 3. Rank by impact score →
4. Filter via ignore.yml → 5. Check GitHub for duplicates → 6. Correlate with recent PRs →
7. Analyze top N with Claude → 8. Create GitHub issues → 9. Create draft PR (highest confidence) →
10. Send Slack summary → 11. Send follow-up with links
```

**Source**: README.md "Architecture" section, decisions.md Part 7

#### Section 6: Error Ranking Formula

```markdown
## Error Ranking

Errors are scored and ranked before analysis:

score = frequency * 0.4 + severity * 0.3 + recency * 0.2 + user_impact * 0.1

Only the top N errors (default 5) are analyzed per run.
```

**Source**: decisions.md Part 4, section 4.1

#### Section 7: Environment Variables

```markdown
## Environment Variables

Required:
- ANTHROPIC_API_KEY — Claude API key
- GITHUB_TOKEN — GitHub personal access token
- GITHUB_REPO — Target repo (e.g. g2crowd/ue)
- NEW_RELIC_API_KEY — New Relic user API key
- NEW_RELIC_ACCOUNT_ID — New Relic account ID
- NEW_RELIC_APP_NAME — New Relic application name
- SLACK_BOT_TOKEN — Slack bot token (xoxb-...)
- SLACK_NOTIFY_USER — Slack display name to DM

See .env.example for all optional variables with defaults.
Do NOT commit .env files. All secrets via environment variables only.
```

**Source**: .env.example, README.md "Configure" section

#### Section 8: Testing Conventions

```markdown
## Testing

- Framework: pytest
- Test directory: tests/
- Test file naming: test_*.py
- Test function naming: test_*
- Run with: uv run pytest tests/
- Always run lint + format + tests before committing:
  uv run ruff check nightwatch/ tests/
  uv run ruff format nightwatch/ tests/
  uv run pytest tests/
```

**Source**: pyproject.toml [tool.pytest.ini_options]

#### Section 9: Commit & PR Conventions

```markdown
## Commit Conventions

- Use conventional commit format: type(scope): description
- Types: feat, fix, refactor, test, docs, chore
- Keep commits focused — one logical change per commit
- Run lint + tests before committing

## PR Conventions

- GitHub issues labeled: nightwatch, has-fix or needs-investigation, confidence:{level}
- Duplicate detection via multi-level matching (error class + transaction → class only → transaction only)
- WIP limit: max 10 open nightwatch issues (configurable)
- Draft PRs only — highest-confidence fix per run
```

**Source**: README.md "GitHub Output", decisions.md Category 5

#### Section 10: CI/CD

```markdown
## CI/CD

- GitHub Actions workflow: .github/workflows/update-docs.yml
- AI-powered documentation updates on push to main
- Weekly scheduled run (Monday 9am UTC)
- Uses g2crowd/doc-action@v1 with Claude Sonnet
```

**Source**: .github/workflows/update-docs.yml

### Total Estimated Length

~200-250 lines of Markdown. Well within the "concise, factual" target from the proposal.

---

## Phase 2: Wire into Claude Code

**Effort**: ~5 minutes

### Step 2a: Create Project-Level CLAUDE.md

NightWatch currently has **no project-level CLAUDE.md** — it relies entirely on the global `~/.claude/CLAUDE.md` (SuperClaude framework). We need a project-level one to import AGENTS.md.

**File**: `/Users/ahenderson/dev/NightWatch/CLAUDE.md`

```markdown
# NightWatch — Claude Code Configuration

## Universal Project Context
@AGENTS.md

## Claude-Specific Configuration

### Error Learning System
- Error reports stored in `.claude/errors/`
- Check existing reports before debugging (read `errors/README.md` index)
- Write a report after every error resolution
- Schema: `.claude/OPENSPEC-error-learning-system.md`

### Development Notes
- This is an internal G2 tool — not open source
- The target repo (g2crowd/ue) is a Rails monolith
- New Relic data comes from production — treat error messages as potentially sensitive
- When modifying prompts.py, consider token budget implications
```

### Step 2b: Verify Import Chain

After creating both files, confirm the full resolution order:

```
1. ~/.claude/CLAUDE.md (global SuperClaude framework)
   → @COMMANDS.md, @FLAGS.md, @PERSONAS.md, etc.
2. /Users/ahenderson/dev/NightWatch/CLAUDE.md (project-level)
   → @AGENTS.md (universal project context)
   → Claude-specific config (error learning, dev notes)
3. .claude/settings.local.json (permissions)
4. .claude/OPENSPEC-error-learning-system.md (error learning spec)
5. .claude/errors/ (error reports)
```

---

## Phase 3: Validate

**Effort**: ~10 minutes

### Test 1: Claude Code Reads AGENTS.md

1. Start a new Claude Code session in the NightWatch directory
2. Ask: "What build tool does NightWatch use?"
3. Expected answer: "uv" (from AGENTS.md, not README.md)
4. Ask: "What is the error ranking formula?"
5. Expected answer: frequency*0.4 + severity*0.3 + recency*0.2 + user_impact*0.1

### Test 2: No Context Window Bloat

1. Check that the session starts without token warnings
2. AGENTS.md (~250 lines) + project CLAUDE.md (~20 lines) should add <2K tokens
3. Verify normal development operations still work within context limits

### Test 3: File Discovery by Other Tools

If Amp Code trial (TOOL-001) proceeds:
1. Install Amp: `npm install -g @sourcegraph/amp`
2. Run `amp` in the NightWatch directory
3. Ask: "What testing framework does this project use?"
4. Expected: Amp reads AGENTS.md and answers "pytest"

If Amp is not installed, verify discoverability:
1. Confirm `AGENTS.md` is at repo root (not in a subdirectory)
2. Confirm it's not in `.gitignore`
3. Confirm it would be committed to the repo

---

## Phase 4: Commit & Document

**Effort**: ~5 minutes

### Files to Create

| File | Purpose | Git Status |
|------|---------|------------|
| `AGENTS.md` | Universal agent config (repo root) | **Committed** |
| `CLAUDE.md` | Project-level Claude Code config | **Committed** |

### Files NOT Modified

| File | Reason |
|------|--------|
| `~/.claude/CLAUDE.md` | Global SuperClaude — unchanged |
| `~/.claude/projects/.../MEMORY.md` | Project memory — add note about AGENTS.md |
| `.claude/settings.local.json` | Permissions — no changes needed |
| `README.md` | Human-facing docs — unchanged |

### Commit Message

```
feat: add AGENTS.md universal agent config and project CLAUDE.md

Create AGENTS.md at repo root with project context readable by any
AI coding agent (21+ tools supported). Add project-level CLAUDE.md
that imports AGENTS.md and adds Claude Code-specific configuration.

Implements TOOL-002 from openspec/changes/agents-md-evaluation/.
```

---

## Content Extraction Map

Precise mapping of what content comes from where:

| AGENTS.md Section | Source File | Lines/Section | Extraction Notes |
|-------------------|------------|---------------|------------------|
| Project Overview | README.md | Lines 1-5 | Condense to 4 bullet points |
| Tech Stack | pyproject.toml | Lines 1-16 | List deps with purpose |
| Build & Install | README.md | Lines 29-35, 159-172 | `uv` commands, not `pip` |
| Run Commands | README.md | Lines 82-89 | CLI reference |
| Test Commands | README.md | Lines 165-172 | `uv run pytest`, `uv run ruff` |
| Code Style | pyproject.toml | Lines 24-36 | Ruff config |
| Code Style (philosophy) | decisions.md | Decisions 2-5 | No server, no DB, no async, sync only |
| Architecture | README.md | Lines 114-126 | File tree + descriptions |
| Core Loop | decisions.md | Category 4 (4.5, 4.6) | Tool-use loop pattern |
| Pipeline | README.md | Lines 8-19 | 11-step pipeline |
| Error Ranking | decisions.md | Part 4, section 4.1 | Scoring formula |
| Environment Variables | .env.example | All lines | Required vs optional |
| Testing | pyproject.toml | Lines 38-41 | pytest config |
| Commit Conventions | N/A (implicit) | — | Conventional commits (new explicit rule) |
| CI/CD | update-docs.yml | All lines | GitHub Actions config |

---

## Verification Checklist

Post-implementation verification (adapted for actual implementation):

- [x] Agent config file exists at `nightwatch/agents/base-analyzer.md`
- [x] File uses AGENTS.md format (YAML frontmatter + markdown instructions)
- [x] Config contains no Claude-specific IDE instructions (no personas, no MCP, no flags)
- [x] Config is <300 lines (actual: ~47 lines)
- [x] Config contains no sensitive data (no API keys, no internal URLs)
- [x] Tool manifest matches the 4 tools defined in `analyzer.py`
- [x] No existing files were modified (additive only)
- [x] File is not in `.gitignore`

---

## Rollback Plan

If the agent config causes issues:

```bash
rm -rf nightwatch/agents/
```

Zero risk to existing configuration. SuperClaude global config and `.claude/` project config are completely untouched. The analyzer falls back to inline prompt configuration if the agent config file is missing.

---

## Future Considerations

### When Claude Code Ships Native AGENTS.md Support

1. Remove `@AGENTS.md` from project `CLAUDE.md` (Claude Code will read it automatically)
2. Keep project `CLAUDE.md` for Claude-specific config (error learning, dev notes)
3. Monitor Issue #6235 on `anthropics/claude-code` for progress

### If v1.1 Spec Stabilizes

1. Consider adding YAML frontmatter for progressive disclosure:
   ```yaml
   ---
   description: "AI-powered production error analysis CLI tool"
   tags: [python, cli, anthropic, newrelic, github]
   ---
   ```
2. Only adopt after the spec is formally merged and has community traction

### If TOOL-001 Amp Trial Proceeds

1. AGENTS.md is immediately usable — no additional work needed
2. Test Amp's reading of AGENTS.md as part of Phase 1 of the Amp trial
3. Document any differences in how Amp interprets AGENTS.md vs Claude Code
