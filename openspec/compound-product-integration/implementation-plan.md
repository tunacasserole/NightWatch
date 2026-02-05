# Implementation Plan: compound-product Integration

**Depends On**: [proposal.md](./proposal.md) (CP-001)
**Status**: Approved
**Date**: 2026-02-05
**Estimated Total Effort**: 4-6 hours implementation + 1 week validation

---

## Phase 0: License Gate (Blocker)

**Effort**: 15 minutes
**Outcome**: Go / no-go for the entire plan

### 0.1 Check License Status
```bash
gh api repos/snarktank/compound-product --jq '.license'
```

### 0.2 Decision Tree
- **License exists (MIT/Apache/ISC)** → Proceed to Phase 1
- **No license** → Open issue requesting one:
  ```bash
  gh issue create --repo snarktank/compound-product \
    --title "Add open source license" \
    --body "Would love to use this in my project. Could you add a LICENSE file (MIT, Apache-2.0, etc.)? Without one the code is technically all-rights-reserved."
  ```
  Then: **STOP.** Do not proceed until license resolved. Fork only if explicitly approved.

---

## Phase 1: Self-Health Report Generator

**Effort**: 2-3 hours
**Branch**: `feat/self-health-report`
**Files touched**: 5 modified, 2 new

This is the core deliverable — NightWatch must emit a structured daily report about its own runs. This phase is valuable *independent* of compound-product (useful for monitoring, debugging, and operational awareness).

### 1.1 New Data Models (`nightwatch/models.py`)

Add to existing models file:

```python
@dataclass
class HealthEvent:
    """A notable event during a NightWatch run (failure, warning, anomaly)."""
    timestamp: str
    severity: Literal["error", "warning", "info"]
    component: str          # e.g. "analyzer", "github", "newrelic", "slack"
    message: str
    details: dict = field(default_factory=dict)
    # Optional: link to error learning system
    error_report_id: str | None = None


@dataclass
class RunHealthReport:
    """Self-health report for a single NightWatch run."""
    # Run identity
    run_timestamp: str
    run_duration_seconds: float
    lookback: str

    # Core metrics
    total_errors_found: int
    errors_filtered: int
    errors_analyzed: int
    fixes_found: int
    high_confidence_fixes: int
    issues_created: int
    issues_updated: int
    prs_created: int

    # Resource usage
    total_tokens_used: int
    total_api_calls: int
    estimated_cost_usd: float   # tokens * rate

    # Per-error efficiency
    avg_iterations_per_error: float
    max_iterations_hit: int     # count of errors that hit max_iterations
    avg_tokens_per_error: int

    # Health events (failures, warnings)
    events: list[HealthEvent] = field(default_factory=list)

    # Quality signals (populated by correlation with past data)
    prs_merged_from_past_runs: int = 0
    prs_rejected_from_past_runs: int = 0
    issues_closed_as_duplicate: int = 0

    @property
    def error_rate(self) -> float:
        """Percentage of events that are errors."""
        if not self.events:
            return 0.0
        return sum(1 for e in self.events if e.severity == "error") / max(len(self.events), 1)
```

### 1.2 Health Event Collector (`nightwatch/health.py`) — NEW FILE

A lightweight collector that runner.py calls at each step boundary:

```python
"""Health event collection and self-report generation."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from nightwatch.models import HealthEvent, RunHealthReport, RunReport

logger = logging.getLogger("nightwatch.health")

# Token pricing (Claude Sonnet 4.5, approximate)
INPUT_COST_PER_MTOK = 3.00
OUTPUT_COST_PER_MTOK = 15.00
# Rough estimate: assume 60/40 input/output split
BLENDED_COST_PER_TOKEN = (INPUT_COST_PER_MTOK * 0.6 + OUTPUT_COST_PER_MTOK * 0.4) / 1_000_000


class HealthCollector:
    """Collects health events during a NightWatch run."""

    def __init__(self) -> None:
        self.events: list[HealthEvent] = []

    def record(
        self,
        severity: str,
        component: str,
        message: str,
        **details: object,
    ) -> None:
        self.events.append(
            HealthEvent(
                timestamp=datetime.now(UTC).isoformat(),
                severity=severity,
                component=component,
                message=message,
                details=dict(details),
            )
        )

    def error(self, component: str, message: str, **details: object) -> None:
        self.record("error", component, message, **details)

    def warning(self, component: str, message: str, **details: object) -> None:
        self.record("warning", component, message, **details)

    def info(self, component: str, message: str, **details: object) -> None:
        self.record("info", component, message, **details)


def build_health_report(
    run_report: RunReport,
    collector: HealthCollector,
) -> RunHealthReport:
    """Build a RunHealthReport from a completed RunReport + collected events."""

    iterations = [a.iterations for a in run_report.analyses]
    tokens = [a.tokens_used for a in run_report.analyses]
    max_iter = get_settings().nightwatch_max_iterations

    return RunHealthReport(
        run_timestamp=run_report.timestamp,
        run_duration_seconds=run_report.run_duration_seconds,
        lookback=run_report.lookback,
        total_errors_found=run_report.total_errors_found,
        errors_filtered=run_report.errors_filtered,
        errors_analyzed=run_report.errors_analyzed,
        fixes_found=run_report.fixes_found,
        high_confidence_fixes=run_report.high_confidence,
        issues_created=sum(
            1 for i in run_report.issues_created if i.action == "created"
        ),
        issues_updated=sum(
            1 for i in run_report.issues_created if i.action == "commented"
        ),
        prs_created=1 if run_report.pr_created else 0,
        total_tokens_used=run_report.total_tokens_used,
        total_api_calls=run_report.total_api_calls,
        estimated_cost_usd=run_report.total_tokens_used * BLENDED_COST_PER_TOKEN,
        avg_iterations_per_error=(
            sum(iterations) / len(iterations) if iterations else 0.0
        ),
        max_iterations_hit=sum(1 for i in iterations if i >= max_iter),
        avg_tokens_per_error=(
            sum(tokens) // len(tokens) if tokens else 0
        ),
        events=collector.events,
    )


def write_report_markdown(
    health: RunHealthReport,
    run_report: RunReport,
    output_dir: Path,
) -> Path:
    """Write a markdown self-health report to disk.

    Returns path to written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Filename: YYYY-MM-DD_HH-MM_self-report.md
    ts = datetime.fromisoformat(health.run_timestamp)
    filename = f"{ts.strftime('%Y-%m-%d_%H-%M')}_self-report.md"
    filepath = output_dir / filename

    lines = _render_markdown(health, run_report)
    filepath.write_text("\n".join(lines))

    logger.info(f"Self-health report written: {filepath}")
    return filepath


def _render_markdown(
    health: RunHealthReport,
    run_report: RunReport,
) -> list[str]:
    """Render the markdown report content."""
    lines: list[str] = []

    ts = datetime.fromisoformat(health.run_timestamp)
    lines.append(f"# NightWatch Daily Self-Report — {ts.strftime('%Y-%m-%d')}")
    lines.append("")

    # --- Run Metrics ---
    lines.append("## Run Metrics")
    lines.append(f"- **Duration**: {health.run_duration_seconds:.0f}s")
    lines.append(f"- **Lookback**: {health.lookback}")
    lines.append(f"- Errors found: {health.total_errors_found}")
    lines.append(f"- Errors filtered (ignored): {health.errors_filtered}")
    lines.append(f"- Errors analyzed: {health.errors_analyzed}")
    lines.append(f"- Fixes found: {health.fixes_found}")
    lines.append(f"- High confidence fixes: {health.high_confidence_fixes}")
    lines.append(f"- Issues created: {health.issues_created}")
    lines.append(f"- Issues updated: {health.issues_updated}")
    lines.append(f"- Draft PRs created: {health.prs_created}")
    lines.append("")

    # --- Resource Usage ---
    lines.append("## Resource Usage")
    lines.append(f"- Total tokens: {health.total_tokens_used:,}")
    lines.append(f"- Estimated cost: ${health.estimated_cost_usd:.2f}")
    lines.append(f"- API calls: {health.total_api_calls}")
    lines.append(f"- Avg iterations/error: {health.avg_iterations_per_error:.1f}")
    lines.append(f"- Avg tokens/error: {health.avg_tokens_per_error:,}")
    lines.append(
        f"- Errors hitting max iterations: {health.max_iterations_hit}"
    )
    lines.append("")

    # --- Failures & Warnings ---
    errors = [e for e in health.events if e.severity == "error"]
    warnings = [e for e in health.events if e.severity == "warning"]

    if errors:
        lines.append("## Failures")
        for ev in errors:
            lines.append(f"- **{ev.component}**: {ev.message}")
            if ev.details:
                for k, v in ev.details.items():
                    lines.append(f"  - {k}: {v}")
        lines.append("")

    if warnings:
        lines.append("## Warnings")
        for ev in warnings:
            lines.append(f"- **{ev.component}**: {ev.message}")
        lines.append("")

    if not errors and not warnings:
        lines.append("## Failures")
        lines.append("None — clean run.")
        lines.append("")

    # --- Per-Error Analysis Summary ---
    lines.append("## Analysis Details")
    for i, result in enumerate(run_report.analyses, 1):
        e = result.error
        a = result.analysis
        status = "FIX" if a.has_fix else "INVESTIGATE"
        conf = a.confidence.upper() if isinstance(a.confidence, str) else a.confidence.value.upper()
        lines.append(
            f"{i}. [{conf}] [{status}] **{e.error_class}** in `{e.transaction}` "
            f"({e.occurrences} occ, {result.iterations} iter, {result.tokens_used:,} tok)"
        )
    lines.append("")

    # --- Quality Signals (from past runs) ---
    lines.append("## Quality Signals")
    if health.prs_merged_from_past_runs or health.prs_rejected_from_past_runs:
        lines.append(
            f"- PRs merged from past runs: {health.prs_merged_from_past_runs}"
        )
        lines.append(
            f"- PRs rejected from past runs: {health.prs_rejected_from_past_runs}"
        )
    if health.issues_closed_as_duplicate:
        lines.append(
            f"- Issues closed as duplicate: {health.issues_closed_as_duplicate}"
        )
    if not any([
        health.prs_merged_from_past_runs,
        health.prs_rejected_from_past_runs,
        health.issues_closed_as_duplicate,
    ]):
        lines.append("No quality signals available yet (first run or no past data).")
    lines.append("")

    return lines


def cleanup_old_reports(output_dir: Path, retain_days: int = 30) -> int:
    """Delete reports older than retain_days. Returns count deleted."""
    if not output_dir.exists():
        return 0

    cutoff = datetime.now(UTC).timestamp() - (retain_days * 86400)
    deleted = 0
    for f in output_dir.glob("*_self-report.md"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            deleted += 1

    if deleted:
        logger.info(f"Cleaned up {deleted} old self-reports")
    return deleted
```

### 1.3 Instrument `runner.py`

Modify the existing `run()` function to collect health events and emit the report. Changes are additive — no existing behavior changes.

**Imports to add**:
```python
from pathlib import Path
from nightwatch.health import HealthCollector, build_health_report, write_report_markdown, cleanup_old_reports
```

**Instrumentation points** (insert into existing try/except blocks):

| Location | What to collect |
|----------|----------------|
| Step 2 (fetch errors) | `collector.info("newrelic", f"Fetched {len(all_errors)} errors")` |
| Step 2 (filter) | `collector.info("newrelic", f"Filtered {errors_filtered} errors")` |
| Step 4 (analysis `except`) | `collector.error("analyzer", f"Analysis failed: {e}", error_class=error.error_class)` |
| Step 6 (Slack `except`) | `collector.error("slack", f"Report failed: {e}")` |
| Step 9 (issue `except`) | `collector.error("github", f"Issue creation failed: {e}", error_class=result.error.error_class)` |
| Step 10 (PR `except`) | `collector.error("github", f"PR creation failed: {e}")` |
| Step 11 (Slack follow-up `except`) | `collector.warning("slack", f"Follow-up failed: {e}")` |

**Post-pipeline report generation** (add after `return report` in the `finally` or after Step 11):

```python
# Step 12: Generate self-health report
try:
    health = build_health_report(report, collector)
    report_dir = Path("reports")
    write_report_markdown(health, report, report_dir)
    cleanup_old_reports(report_dir)
except Exception as e:
    logger.error(f"Self-health report generation failed: {e}")
```

### 1.4 Add `--self-report` CLI Flag (`nightwatch/__main__.py`)

```python
run_parser.add_argument(
    "--self-report", action="store_true",
    help="Generate self-health report after run (default: enabled in non-dry-run mode)",
)
run_parser.add_argument(
    "--report-dir", default="reports",
    help="Directory for self-health reports (default: reports/)",
)
```

Self-report is **on by default** for real runs, skip for `--dry-run` (add `--self-report` to force it in dry-run mode).

### 1.5 Add Config Settings (`nightwatch/config.py`)

```python
# Self-health reporting
nightwatch_report_dir: str = "reports"
nightwatch_report_retention_days: int = 30
nightwatch_self_report: bool = True  # Generate self-health reports
```

### 1.6 Gitignore the Reports Directory

Add to `.gitignore`:
```
# Self-health reports (machine-generated, contain operational data)
reports/
```

### 1.7 Tests (`tests/test_health.py`) — NEW FILE

```python
"""Tests for self-health report generation."""

# Test cases:
# - test_health_collector_records_events
# - test_health_collector_severity_levels
# - test_build_health_report_from_run_report
# - test_build_health_report_empty_run
# - test_render_markdown_structure (check section headings exist)
# - test_render_markdown_failures_section (errors present)
# - test_render_markdown_clean_run (no errors)
# - test_estimated_cost_calculation
# - test_max_iterations_hit_count
# - test_cleanup_old_reports
```

### 1.8 Validation

```bash
uv run ruff check nightwatch/ tests/
uv run pytest tests/ -v
uv run python -m nightwatch run --dry-run --self-report  # confirm report generated
cat reports/*_self-report.md  # inspect output
```

---

## Phase 2: Quality Signal Feedback Loop

**Effort**: 1-2 hours
**Branch**: `feat/quality-signals`
**Files touched**: 3 modified, 1 new
**Depends on**: Phase 1

The self-health report is more useful when it can report on the *outcomes* of past runs (were PRs merged? were issues duplicates?). This phase adds a lightweight feedback mechanism.

### 2.1 Quality Signal Collector (`nightwatch/quality.py`) — NEW FILE

Query GitHub for outcomes of NightWatch's past work:

```python
"""Quality signal collection — track outcomes of past NightWatch runs."""

def collect_quality_signals(gh_client, lookback_days: int = 7) -> QualitySignals:
    """Check what happened to NightWatch's past issues and PRs."""
    # 1. Find all issues labeled 'nightwatch'
    # 2. Count: merged PRs, rejected PRs, closed-as-duplicate issues
    # 3. Return structured data for health report
```

### 2.2 Integrate into Runner

After Step 1 (initialize clients), before the main pipeline:

```python
# Step 1.5: Collect quality signals from past runs
try:
    signals = collect_quality_signals(gh, lookback_days=7)
    collector.info("quality", f"Past 7d: {signals.merged} merged, {signals.rejected} rejected")
except Exception as e:
    collector.warning("quality", f"Could not collect quality signals: {e}")
    signals = None
```

Then populate `health.prs_merged_from_past_runs` etc. from signals.

### 2.3 Tests

```python
# test_quality.py
# - test_collect_quality_signals_counts_merged_prs
# - test_collect_quality_signals_counts_rejected_prs
# - test_collect_quality_signals_counts_duplicate_issues
# - test_collect_quality_signals_empty_history
```

---

## Phase 3: compound-product Installation

**Effort**: 30-45 minutes
**Branch**: `feat/compound-product`
**Depends on**: Phase 0 (license clear) + Phase 1 (reports exist)

### 3.1 Pin and Install

```bash
# Get the current latest commit SHA
COMPOUND_SHA=$(gh api repos/snarktank/compound-product/commits/main --jq '.sha')

# Install from that specific commit
curl -fsSL "https://raw.githubusercontent.com/snarktank/compound-product/${COMPOUND_SHA}/install.sh" \
  | bash -s -- /Users/ahenderson/dev/NightWatch
```

### 3.2 Create Configuration (`compound.config.json`)

```json
{
  "report_dir": "reports",
  "report_pattern": "*_self-report.md",
  "quality_checks": [
    "uv run ruff check nightwatch/ tests/",
    "uv run pytest tests/ -v"
  ],
  "max_iterations": 15,
  "agent": "claude-code",
  "branch_prefix": "compound/",
  "pinned_commit": "<SHA from step 3.1>",
  "constraints": {
    "max_tasks": 3,
    "scope_hours": 2,
    "no_database_migrations": true,
    "no_dependency_changes": true
  }
}
```

### 3.3 Create compound-product AGENTS.md

Extend the existing `.claude/` context for compound-product's agent:

```markdown
# NightWatch — compound-product Agent Context

## Project Overview
NightWatch is a Python CLI tool that analyzes production errors via New Relic + Claude
and creates GitHub issues + draft PRs.

## Stack
- Python 3.11, uv package manager
- anthropic SDK, PyGithub, slack-sdk, pydantic
- pytest for testing, ruff for linting

## Quality Checks (MUST pass before commit)
- `uv run ruff check nightwatch/ tests/` — zero errors
- `uv run pytest tests/ -v` — all tests pass

## Off-Limits
- Do NOT modify .env or config.py API keys
- Do NOT change the Claude model or max_iterations defaults
- Do NOT add new dependencies without documenting why
- Do NOT touch the GitHub/Slack/NewRelic client authentication
- Do NOT modify compound.config.json or install scripts

## Patterns
- Dataclasses for internal models, Pydantic for API/validation models
- Logging via `logging.getLogger("nightwatch.<module>")`
- All functions have docstrings
- Error handling: log and continue (fail forward), never crash the pipeline
```

### 3.4 Verify Installation

```bash
# Check scripts exist
ls -la scripts/auto-compound.sh scripts/loop.sh scripts/analyze-report.sh

# Dry run (if supported)
bash scripts/auto-compound.sh --dry-run 2>&1 | head -20
```

---

## Phase 4: Scheduling

**Effort**: 15-30 minutes
**Branch**: `feat/compound-scheduling`
**Depends on**: Phase 3

### 4.1 NightWatch launchd (already exists or create)

File: `~/Library/LaunchAgents/com.nightwatch.daily.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nightwatch.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/ahenderson/.local/bin/uv</string>
        <string>run</string>
        <string>python</string>
        <string>-m</string>
        <string>nightwatch</string>
        <string>run</string>
        <string>--since</string>
        <string>24h</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/ahenderson/dev/NightWatch</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>2</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/ahenderson/dev/NightWatch/logs/nightwatch.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/ahenderson/dev/NightWatch/logs/nightwatch.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/Users/ahenderson/.local/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

### 4.2 compound-product launchd

File: `~/Library/LaunchAgents/com.nightwatch.compound.plist`

Run 2 hours after NightWatch to ensure a fresh report exists:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nightwatch.compound</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/Users/ahenderson/dev/NightWatch/scripts/auto-compound.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/ahenderson/dev/NightWatch</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>4</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/ahenderson/dev/NightWatch/logs/compound.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/ahenderson/dev/NightWatch/logs/compound.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/Users/ahenderson/.local/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>ANTHROPIC_API_KEY</key>
        <string>SET_ME</string>
    </dict>
</dict>
</plist>
```

### 4.3 Install Schedules

```bash
mkdir -p /Users/ahenderson/dev/NightWatch/logs

# Load schedules
launchctl load ~/Library/LaunchAgents/com.nightwatch.daily.plist
launchctl load ~/Library/LaunchAgents/com.nightwatch.compound.plist

# Verify
launchctl list | grep nightwatch
```

### 4.4 Daily Timeline

```
02:00  NightWatch runs → analyzes errors → creates issues/PRs → writes self-report
04:00  compound-product runs → reads self-report → picks priority → implements fix → opens PR
07:00  You wake up → review compound-product PR + NightWatch issues over coffee
```

---

## Phase 5: Validation Week

**Effort**: ~10 min/day for 7 days
**Branch**: n/a (monitoring only)
**Depends on**: Phases 1-4 complete

### 5.1 Daily Checklist

Each morning for 7 days:

- [ ] NightWatch self-report exists in `reports/` — check file was generated
- [ ] compound-product PR exists — check `gh pr list --label compound`
- [ ] PR passes quality checks — ruff + pytest both green
- [ ] PR is relevant — the chosen priority actually matters
- [ ] PR is correct — code changes make sense, no regressions
- [ ] Merge or close with feedback note

### 5.2 Tracking Spreadsheet

| Day | Report? | PR? | Quality? | Relevant? | Correct? | Action | Notes |
|-----|---------|-----|----------|-----------|----------|--------|-------|
| 1   |         |     |          |           |          |        |       |
| 2   |         |     |          |           |          |        |       |
| ...   |         |     |          |           |          |        |       |
| 7   |         |     |          |           |          |        |       |

### 5.3 Go/Tune/Kill Decision

After 7 days:

| Outcome | Criteria | Action |
|---------|----------|--------|
| **Go** | >50% PRs useful, <20% bad, cost <$5/day avg | Continue, reduce review cadence to 2x/week |
| **Tune** | 30-50% useful, fixable issues identified | Adjust prompts, constraints, or max_iterations. Run another 7 days. |
| **Kill** | <30% useful OR >$10/day OR consistently wrong | Disable compound-product schedule. Keep self-health reports (still valuable). |

---

## Phase 6: Hardening (Post-Validation)

**Effort**: 1-2 hours
**Depends on**: Phase 5 Go/Tune decision

Only if Phase 5 passes:

### 6.1 Cost Tracking Wrapper

Wrap compound-product's `auto-compound.sh` with a cost logger:

```bash
#!/bin/bash
# scripts/compound-wrapper.sh
START=$(date +%s)
bash scripts/auto-compound.sh 2>&1 | tee -a logs/compound.log
END=$(date +%s)
DURATION=$((END - START))
echo "[$(date -Iseconds)] compound-product run completed in ${DURATION}s" >> logs/compound-costs.log
```

### 6.2 Alert on Failures

Add a Slack notification if compound-product fails:

```bash
# In compound-wrapper.sh
if [ $? -ne 0 ]; then
    curl -X POST "$SLACK_WEBHOOK_URL" \
      -H 'Content-Type: application/json' \
      -d '{"text": "⚠️ compound-product run failed. Check logs/compound.err"}'
fi
```

### 6.3 Monthly Review Automation

Create a script that summarizes compound-product's 30-day performance:

```bash
# scripts/compound-monthly-review.sh
# Count PRs created, merged, closed
# Calculate total cost from logs
# Output summary to Slack
```

---

## File Summary

### New Files
| File | Phase | Purpose |
|------|-------|---------|
| `nightwatch/health.py` | 1 | Health event collector + report generator |
| `nightwatch/quality.py` | 2 | Quality signal collection from GitHub |
| `tests/test_health.py` | 1 | Tests for health reporting |
| `tests/test_quality.py` | 2 | Tests for quality signals |
| `compound.config.json` | 3 | compound-product configuration |
| `com.nightwatch.daily.plist` | 4 | NightWatch schedule |
| `com.nightwatch.compound.plist` | 4 | compound-product schedule |
| `scripts/compound-wrapper.sh` | 6 | Cost tracking wrapper |

### Modified Files
| File | Phase | Changes |
|------|-------|---------|
| `nightwatch/models.py` | 1 | Add `HealthEvent`, `RunHealthReport` dataclasses |
| `nightwatch/runner.py` | 1, 2 | Instrument with HealthCollector, add report generation step |
| `nightwatch/__main__.py` | 1 | Add `--self-report`, `--report-dir` flags |
| `nightwatch/config.py` | 1 | Add report settings |
| `.gitignore` | 1 | Add `reports/` |

---

## Risk Mitigation Summary

| Risk | Mitigation | Phase |
|------|------------|-------|
| No license | Hard gate at Phase 0. Do not proceed. | 0 |
| compound-product breaks | Pinned to commit SHA. Update manually. | 3 |
| Runaway costs | Max 15 iterations. Wrapper logs costs. Kill switch via `launchctl unload`. | 3, 6 |
| Bad PRs merged | **Never auto-merge.** Human review mandatory for all compound-product PRs. | 5 |
| Self-report feature breaks NightWatch | Self-report is in a `try/except` — pipeline continues if it fails. | 1 |
| compound-product modifies itself | AGENTS.md explicitly forbids touching config/install files. | 3 |

---

## Immediate Next Steps

1. **Run Phase 0** — Check license status right now
2. **Start Phase 1** — Self-health report is valuable regardless of compound-product
3. **Wait for license** before Phase 3+
4. **Phase 1 alone** makes NightWatch more observable and debuggable, even if compound-product is never adopted

---

*This plan is designed so Phase 1 delivers standalone value. Phases 2-6 are additive and can be deferred or abandoned without wasting Phase 1 work.*
