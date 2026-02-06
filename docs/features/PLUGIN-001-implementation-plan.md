# PLUGIN-001: Claude Code Plugin Adoption — Implementation Plan

**OpenSpec**: [OPENSPEC-claude-code-plugins.md](../../.claude/OPENSPEC-claude-code-plugins.md)
**Status**: Ready to Execute
**Estimated Total Time**: 45-60 minutes
**Dependencies**: Active Claude Code session, internet access, NightWatch virtualenv

---

## Execution Phases

### Phase 0: Prerequisites (5 min)

**Objective**: Install the `pyright` language server binary so the LSP plugin can connect.

#### Steps

1. **Install pyright into the NightWatch virtualenv**

   ```bash
   cd /Users/ahenderson/dev/NightWatch
   uv pip install pyright
   ```

   Alternatively, install globally:
   ```bash
   npm install -g pyright
   ```

2. **Verify the binary is available**

   ```bash
   pyright-langserver --version
   ```

   Expected: Version string printed. If "command not found", check that the virtualenv is activated or the npm global bin is in `$PATH`.

3. **Verify Claude Code version supports plugins**

   ```bash
   claude --version
   ```

   Required: `>= 1.0.33`. If older, update:
   ```bash
   brew upgrade claude-code
   # or
   npm update -g @anthropic-ai/claude-code
   ```

#### Validation Gate
- [ ] `pyright-langserver --version` succeeds
- [ ] `claude --version` >= 1.0.33

---

### Phase 1: Marketplace Setup (2 min)

**Objective**: Register the demo marketplace so plugins from both sources are browsable.

#### Steps

1. **The official Anthropic marketplace is auto-available** — no action needed.

2. **Add the demo marketplace**:

   From within Claude Code:
   ```
   /plugin marketplace add anthropics/claude-code
   ```

3. **Verify both marketplaces are registered**:

   ```
   /plugin marketplace list
   ```

   Expected output shows:
   - `claude-plugins-official` (built-in)
   - `anthropics-claude-code` (just added)

#### Validation Gate
- [ ] `/plugin marketplace list` shows both marketplaces
- [ ] `/plugin` → Discover tab shows plugins from both sources

---

### Phase 2: Tier 1 Installation — Core Plugins (10 min)

**Objective**: Install the 4 critical plugins that address immediate development gaps.

#### Step 2.1: Install `pyright-lsp` (User scope)

```
/plugin install pyright-lsp@claude-plugins-official
```

**Verification**:
1. Open any NightWatch Python file (e.g., edit `nightwatch/config.py`)
2. Introduce a deliberate type error (e.g., assign `str` to an `int` field)
3. Pyright should flag it automatically — Claude self-corrects
4. Check `/plugin` → Errors tab for any issues
5. Revert the test change

**What to watch for**:
- "Executable not found in $PATH" → Re-run `uv pip install pyright` and ensure the venv is activated
- High memory → Monitor with `ps aux | grep pyright`. NightWatch at 8K LOC should be fine.

#### Step 2.2: Install `security-guidance` (Project scope)

```
/plugin install security-guidance@anthropics-claude-code --scope project
```

**Why project scope**: This creates an entry in `.claude/settings.json` (not `.local`), meaning it's shared with all NightWatch developers via git.

**Verification**:
1. Edit a Python file and try adding `eval("1+1")`
2. The security hook should flag the `eval()` usage
3. Revert the test change

#### Step 2.3: Install `github` (User scope)

```
/plugin install github@claude-plugins-official
```

**Verification**:
1. Ask Claude: "List open issues on the NightWatch repo"
2. Should return results via the GitHub MCP server
3. If auth fails, the plugin may need `GITHUB_TOKEN` — NightWatch already has this in `.env`

#### Step 2.4: Install `commit-commands` (User scope)

```
/plugin install commit-commands@claude-plugins-official
```

**Verification**:
1. Make a trivial change (e.g., add a comment to any file)
2. Run `/commit-commands:commit`
3. Should stage, generate message, and commit
4. Verify with `git log --oneline -1`
5. If satisfied, keep the commit. Otherwise `git reset HEAD~1` to undo.

#### Validation Gate
- [ ] `pyright-lsp` — diagnostics appear after editing a `.py` file
- [ ] `security-guidance` — flags `eval()` in a test edit
- [ ] `github` — can query NightWatch repo issues
- [ ] `commit-commands` — `/commit-commands:commit` succeeds
- [ ] `/plugin` → Installed tab shows all 4 plugins
- [ ] `/plugin` → Errors tab shows no errors

---

### Phase 3: Tier 2 Installation — Development Plugins (10 min)

**Objective**: Install 4 high-value plugins for active development and code review.

#### Step 3.1: Install `pr-review-toolkit` (User scope)

```
/plugin install pr-review-toolkit@claude-plugins-official
```

**Verification**:
1. If there's an open PR, run: `/pr-review-toolkit:review-pr`
2. If no PR exists, create a test branch with changes and open a PR, then run the review
3. Should see output from 6 parallel review agents

#### Step 3.2: Install `slack` (User scope)

```
/plugin install slack@claude-plugins-official
```

**Verification**:
1. Ask Claude: "What Slack channels am I in?"
2. Should connect using `SLACK_BOT_TOKEN` from `.env`
3. If auth fails, verify the token has the required scopes (channels:read, chat:write, users:read)

**Note**: The Slack plugin may require OAuth setup the first time. Follow any interactive prompts.

#### Step 3.3: Install `sentry` (User scope)

```
/plugin install sentry@claude-plugins-official
```

**Verification**:
1. Ask Claude: "List recent Sentry issues"
2. May require `SENTRY_AUTH_TOKEN` or `SENTRY_DSN` — add to `.env` if needed
3. If NightWatch doesn't currently use Sentry, this plugin can be deferred until a Sentry project is set up

**Note**: This is a forward-looking install. If no Sentry project exists yet, skip and install later.

#### Step 3.4: Install `code-review` (User scope)

```
/plugin install code-review@anthropics-claude-code
```

**Verification**:
1. Same as pr-review-toolkit — test against an open PR
2. Should see confidence-scored findings from 5 parallel agents

#### Validation Gate
- [ ] `pr-review-toolkit` — `/pr-review-toolkit:review-pr` runs successfully
- [ ] `slack` — connects to workspace (or deferred if token issues)
- [ ] `sentry` — connects to Sentry (or deferred if no project exists)
- [ ] `code-review` — review command produces findings
- [ ] `/plugin` → Installed tab shows 8 total plugins

---

### Phase 4: Project Configuration (10 min)

**Objective**: Create shared project configuration so all NightWatch developers benefit.

#### Step 4.1: Create `.claude/settings.json`

The `security-guidance` project-scope install in Phase 2 should have created this file. Verify it exists and add additional configuration:

```json
{
  "enabledPlugins": [
    "security-guidance@anthropics-claude-code"
  ]
}
```

**Important**: This file is committed to git (unlike `settings.local.json` which is gitignored). Only include plugins that ALL developers should have.

#### Step 4.2: Create project-level `CLAUDE.md`

Create `/Users/ahenderson/dev/NightWatch/CLAUDE.md` with plugin documentation:

```markdown
# NightWatch — Claude Code Configuration

## Build & Test
- Package manager: `uv`
- Run tests: `python -m pytest tests/ -v`
- Run single test: `python -m pytest tests/path/to/test.py -v`
- Lint: `ruff check nightwatch/ tests/`
- Format: `ruff format nightwatch/ tests/`
- Type check: `pyright nightwatch/`
- Coverage: `python -m pytest tests/ --cov=nightwatch --cov-report=term-missing`
- Minimum coverage: 85%

## Code Style
- Line length: 100 characters
- Python target: 3.11+
- Ruff rules: E, F, I, UP, B, SIM
- All data models use Pydantic v2 (nightwatch/types/)
- Agent classes inherit from BaseAgent (nightwatch/agents/base.py)
- Workflows inherit from BaseWorkflow (nightwatch/workflows/base.py)

## Architecture
- GANDALF pattern: Types → Agents → MessageBus → Pipeline → Validation
- 5-layer validation: path_safety → content → syntax → semantic → quality
- Agent registration: @register_agent decorator in nightwatch/agents/registry.py
- Workflow registration: @register_workflow decorator in nightwatch/workflows/registry.py

## Plugins (Active)
- **pyright-lsp**: Python type intelligence — diagnostics auto-run after every edit
- **security-guidance**: Monitors for dangerous patterns (eval, pickle, os.system, injection)
- **pr-review-toolkit**: Run `/pr-review-toolkit:review-pr` before merging PRs
- **commit-commands**: Run `/commit-commands:commit` for AI-generated commits

## Environment
- Copy `.env.example` to `.env` and fill in required values
- Required: ANTHROPIC_API_KEY, GITHUB_TOKEN, GITHUB_REPO, NEW_RELIC_API_KEY, NEW_RELIC_ACCOUNT_ID, NEW_RELIC_APP_NAME
- Optional: SLACK_BOT_TOKEN, OPIK_API_KEY

## Error Learning
- Error reports stored in `.claude/errors/`
- Always check existing reports before debugging
- Write a report after every error resolution
- See `.claude/OPENSPEC-error-learning-system.md` for schema
```

#### Step 4.3: Configure marketplace auto-updates

```
/plugin
```
→ Navigate to **Marketplaces** tab
→ Select `claude-plugins-official` → Ensure auto-update is **enabled** (default)
→ Select `anthropics-claude-code` → Set auto-update to **disabled** (review demo marketplace changes manually)

#### Step 4.4: Update `.gitignore`

Verify `.claude/settings.local.json` is already gitignored. If not:

```
# Claude Code local settings (per-developer)
.claude/settings.local.json

# Claude Code plugin cache
.claude/plugins/
```

#### Validation Gate
- [ ] `.claude/settings.json` exists with `security-guidance` in `enabledPlugins`
- [ ] `CLAUDE.md` exists at project root with plugin documentation
- [ ] Official marketplace auto-update: enabled
- [ ] Demo marketplace auto-update: disabled
- [ ] `.gitignore` covers `.claude/settings.local.json` and `.claude/plugins/`

---

### Phase 5: Smoke Test (10 min)

**Objective**: End-to-end validation that all plugins work together without conflicts.

#### Test 1: Edit-time Intelligence

1. Open `nightwatch/types/core.py`
2. Add a field with wrong type: `name: int = "hello"`
3. **Expected**: Pyright flags type mismatch automatically
4. Fix the error → Pyright clears the diagnostic
5. Revert changes

#### Test 2: Security Hook

1. Open `nightwatch/analyzer.py`
2. Add line: `result = eval(user_input)`
3. **Expected**: `security-guidance` hook flags the `eval()` usage
4. Add line: `import pickle; data = pickle.loads(raw)`
5. **Expected**: `security-guidance` hook flags pickle deserialization
6. Revert all changes

#### Test 3: Git Workflow

1. Add a comment to any file
2. Run `/commit-commands:commit`
3. **Expected**: Stages file, generates descriptive commit message, commits
4. Verify: `git log --oneline -1`
5. Reset if desired: `git reset HEAD~1`

#### Test 4: GitHub Integration

1. Ask Claude: "Show me the 3 most recent commits on NightWatch main branch"
2. **Expected**: Returns commit info via GitHub MCP
3. Ask: "Are there any open issues?"
4. **Expected**: Lists issues or confirms none exist

#### Test 5: PR Review (if PR available)

1. If an open PR exists: `/pr-review-toolkit:review-pr`
2. **Expected**: 6 parallel agents analyze the PR
3. Look for: `silent-failure-hunter` and `type-design-analyzer` output specifically

#### Test 6: Plugin Coexistence

1. Run `/plugin` → check **Errors** tab
2. **Expected**: No errors from any installed plugin
3. Make a normal edit to a Python file
4. **Expected**: Pyright diagnostics AND security-guidance both fire without conflict
5. Verify SuperClaude commands still work: try `--think` or `--persona-analyzer`
6. **Expected**: No interference between plugins and SuperClaude

#### Validation Gate
- [ ] Pyright catches type errors on edit
- [ ] Security-guidance catches dangerous patterns on edit
- [ ] commit-commands creates clean commits
- [ ] GitHub MCP returns repo data
- [ ] PR review runs (if applicable)
- [ ] No plugin errors in Errors tab
- [ ] No conflicts with SuperClaude framework

---

### Phase 6: Documentation & Commit (5 min)

**Objective**: Commit all configuration changes.

#### Files to commit

| File | Scope | Description |
|------|-------|-------------|
| `.claude/settings.json` | Project (shared) | security-guidance plugin config |
| `CLAUDE.md` | Project (shared) | Project conventions + plugin documentation |
| `.claude/OPENSPEC-claude-code-plugins.md` | Local reference | Plugin adoption specification |
| `docs/features/PLUGIN-001-implementation-plan.md` | Project (shared) | This implementation plan |
| `docs/features/README.md` | Project (shared) | Updated feature index |
| `.gitignore` | Project (shared) | Updated ignore rules (if changed) |

#### Commit

```bash
git add .claude/settings.json CLAUDE.md .claude/OPENSPEC-claude-code-plugins.md \
       docs/features/PLUGIN-001-implementation-plan.md docs/features/README.md
git commit -m "feat(PLUGIN-001): adopt Claude Code plugins for NightWatch development

Add pyright-lsp (type intelligence), security-guidance (pattern detection),
github (MCP integration), and commit-commands (git workflows) as Tier 1
plugins. Install pr-review-toolkit, slack, sentry, and code-review as
Tier 2. Create project CLAUDE.md with build/test/style conventions.

Ref: PLUGIN-001"
```

---

## Post-Installation: Tier 3 Triggers

These plugins are **not installed now** but should be installed when these conditions are met:

| Plugin | Install When | Command |
|--------|-------------|---------|
| `agent-sdk-dev` | Modifying `nightwatch/agents/` or `nightwatch/prompts.py` | `/plugin install agent-sdk-dev@claude-plugins-official` |
| `hookify` | Creating project-specific guardrails (e.g., enforce test-with-commit) | `/plugin install hookify@anthropics-claude-code` |
| `feature-dev` | Starting a new major feature phase (Phases 1-5 in README.md) | `/plugin install feature-dev@anthropics-claude-code` |
| `plugin-dev` | Building the custom `nightwatch-dev` plugin | `/plugin install plugin-dev@claude-plugins-official` |

---

## Rollback Plan

If any plugin causes issues:

### Disable a single plugin (preserves config, stops execution)
```
/plugin disable <plugin-name>@<marketplace>
```

### Uninstall a single plugin (removes entirely)
```
/plugin uninstall <plugin-name>@<marketplace>
```

### Nuclear option: Remove all plugins and start fresh
```bash
rm -rf ~/.claude/plugins/cache
# Restart Claude Code
# Reinstall selectively
```

### Remove demo marketplace (removes all demo marketplace plugins)
```
/plugin marketplace remove anthropics-claude-code
```

---

## Quick Reference Card

After installation, these commands are available:

| Command | What It Does |
|---------|-------------|
| `/commit-commands:commit` | Stage + AI commit message + commit |
| `/commit-commands:push-pr` | Commit + push + create PR |
| `/commit-commands:clean-gone` | Delete stale local branches |
| `/pr-review-toolkit:review-pr` | 6-agent parallel PR review |
| `/pr-review-toolkit:review-pr --types` | Type design review only |
| `/pr-review-toolkit:review-pr --errors` | Silent failure hunting only |
| `/plugin` | Open plugin manager (Discover/Installed/Marketplaces/Errors) |
| `/plugin disable <name>` | Temporarily disable a plugin |
| `Ctrl+O` | Toggle diagnostics display when "diagnostics found" appears |

---

## Success Metrics (Post 1-Week)

| Metric | How to Measure | Target |
|--------|---------------|--------|
| Type errors caught by pyright | Count of auto-fix cycles during edits | >5 per session |
| Security patterns blocked | Count of security-guidance flags | >0 (any flags = value) |
| PR review adoption | % of PRs reviewed with pr-review-toolkit | 100% of PRs |
| Commit workflow time | Time from "ready to commit" to committed | <30 seconds |
| Plugin stability | Errors in `/plugin` Errors tab | 0 persistent errors |
