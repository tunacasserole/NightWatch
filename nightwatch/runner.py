"""Main orchestration pipeline — fetch → rank → trace → analyze → report → issues → PR → notify."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

import anthropic

# Import workflow modules to trigger @register decorators
import nightwatch.workflows.ci_doctor  # noqa: F401
import nightwatch.workflows.errors  # noqa: F401
import nightwatch.workflows.patterns  # noqa: F401
from nightwatch.analyzer import analyze_error
from nightwatch.config import get_settings
from nightwatch.correlation import (
    correlate_error_with_prs,
    fetch_recent_merged_prs,
    format_correlated_prs,
)
from nightwatch.github import CodeCache, GitHubClient
from nightwatch.guardrails import generate_guardrails
from nightwatch.health import HealthReport
from nightwatch.history import save_run
from nightwatch.knowledge import (
    compound_result,
    rebuild_index,
    save_error_pattern,
    search_prior_knowledge,
    update_result_metadata,
)
from nightwatch.models import (
    CreatedIssueResult,
    CreatedPRResult,
    ErrorAnalysisResult,
    PriorAnalysis,
    RunContext,
    RunReport,
)
from nightwatch.newrelic import (
    NewRelicClient,
    filter_errors,
    load_ignore_patterns,
    rank_errors,
)
from nightwatch.patterns import (
    detect_patterns_with_knowledge,
    suggest_ignore_updates,
    write_pattern_doc,
)
from nightwatch.quality import QualityTracker
from nightwatch.research import ResearchContext, research_error
from nightwatch.slack import SlackClient
from nightwatch.validation import validate_file_changes
from nightwatch.workflows.registry import list_registered

logger = logging.getLogger("nightwatch")


def run(
    since: str | None = None,
    max_errors: int | None = None,
    max_issues: int | None = None,
    dry_run: bool | None = None,
    verbose: bool = False,
    model: str | None = None,
    agent_name: str = "base-analyzer",
) -> RunReport:
    """Execute the full NightWatch pipeline.

    Args:
        since: Lookback period (e.g. "24h", "12h"). Overrides env var.
        max_errors: Max errors to analyze. Overrides env var.
        max_issues: Max GitHub issues to create. Overrides env var.
        dry_run: If True, analyze only — no issues/PRs/Slack. Overrides env var.
        verbose: Show iteration details.
        model: Claude model to use. Overrides env var.

    Returns:
        RunReport with full results.
    """
    settings = get_settings()
    start_time = time.time()

    # Initialize Opik tracing (no-op if unconfigured)
    from nightwatch.observability import configure_opik

    configure_opik()

    # Apply overrides
    since = since or settings.nightwatch_since
    max_errors = max_errors if max_errors is not None else settings.nightwatch_max_errors
    max_issues = max_issues if max_issues is not None else settings.nightwatch_max_issues
    dry_run = dry_run if dry_run is not None else settings.nightwatch_dry_run
    if model:
        settings.nightwatch_model = model

    logger.info(f"NightWatch starting — looking back {since} for errors...")
    if dry_run:
        logger.info("DRY RUN — no issues, PRs, or Slack messages will be created")

    # ------------------------------------------------------------------
    # Step 1: Initialize clients
    # ------------------------------------------------------------------
    nr = NewRelicClient()
    gh = GitHubClient()

    try:
        # ------------------------------------------------------------------
        # Step 2: Fetch and rank errors
        # ------------------------------------------------------------------
        all_errors = nr.fetch_errors(since=since)

        ignore_patterns = load_ignore_patterns()
        filtered = filter_errors(all_errors, ignore_patterns)
        errors_filtered = len(all_errors) - len(filtered)

        ranked = rank_errors(filtered)
        top_errors = ranked[:max_errors]

        logger.info(
            f"Top {len(top_errors)} errors selected for analysis "
            f"(filtered {errors_filtered} known errors)"
        )

        # ------------------------------------------------------------------
        # Step 3: Fetch traces for each error
        # ------------------------------------------------------------------
        logger.info("Fetching detailed traces...")
        traces_map = {}
        for i, error in enumerate(top_errors, 1):
            logger.info(f"  [{i}/{len(top_errors)}] {error.error_class}")
            traces_map[id(error)] = nr.fetch_traces(error, since=since)

        # ------------------------------------------------------------------
        # Step 3.5: Search knowledge base for prior analyses
        # ------------------------------------------------------------------
        prior_knowledge_map: dict[int, list[PriorAnalysis]] = {}
        if settings.nightwatch_compound_enabled:
            logger.info("Searching knowledge base for prior analyses...")
            for error in top_errors:
                try:
                    prior = search_prior_knowledge(error)
                    if prior:
                        prior_knowledge_map[id(error)] = prior
                        logger.info(
                            f"  Found {len(prior)} prior analyses for {error.error_class}"
                        )
                except Exception as e:
                    logger.warning(f"  Knowledge search failed for {error.error_class}: {e}")

        # ------------------------------------------------------------------
        # Step 3.7: Pre-analysis research (file inference + pre-fetch)
        # ------------------------------------------------------------------
        research_map: dict[int, ResearchContext] = {}
        logger.info("Running pre-analysis research...")
        correlated_prs_early = fetch_recent_merged_prs(gh.repo, hours=24)
        for error in top_errors:
            try:
                ctx = research_error(
                    error=error,
                    traces=traces_map[id(error)],
                    github_client=gh,
                    correlated_prs=correlate_error_with_prs(error, correlated_prs_early),
                    prior_analyses=prior_knowledge_map.get(id(error)),
                )
                if ctx.likely_files or ctx.file_previews:
                    research_map[id(error)] = ctx
                    logger.info(
                        f"  Research for {error.error_class}: "
                        f"{len(ctx.likely_files)} files, "
                        f"{len(ctx.file_previews)} previews"
                    )
            except Exception as e:
                logger.warning(f"  Research failed for {error.error_class}: {e}")

        # ------------------------------------------------------------------
        # Step 4: Analyze each error with Claude (with RunContext sharing)
        # ------------------------------------------------------------------
        logger.info("Starting Claude analysis...")
        analyses: list[ErrorAnalysisResult] = []
        run_context = RunContext()  # Shared across all errors in this run
        multi_pass_retries = 0
        pr_validation_failures = 0

        # Self-health and quality tracking
        health = HealthReport()
        health.check_configuration()
        quality_tracker = QualityTracker()

        # Cross-error context and code cache
        cross_error_context: list[str] = []
        code_cache = CodeCache()

        for i, error in enumerate(top_errors, 1):
            logger.info(
                f"Analyzing {i}/{len(top_errors)}: "
                f"{error.error_class} in {error.transaction} "
                f"({error.occurrences} occurrences)"
            )
            try:
                # Build cross-error prior context
                prior_text = None
                if cross_error_context:
                    recent = cross_error_context[-4:]
                    prior_text = (
                        "Previously Analyzed Errors:\n" + "\n".join(recent)
                    )

                result = analyze_error(
                    error=error,
                    traces=traces_map[id(error)],
                    github_client=gh,
                    newrelic_client=nr,
                    run_context=run_context,
                    prior_analyses=prior_knowledge_map.get(id(error)),
                    research_context=research_map.get(id(error)),
                    agent_name=agent_name,
                    prior_context=prior_text,
                )
                analyses.append(result)

                # Build cross-error summary for subsequent analyses
                root = (
                    result.analysis.root_cause[:200]
                    if result.analysis.root_cause
                    else "Unknown"
                )
                files = ", ".join(
                    fc.path
                    for fc in (result.analysis.file_changes[:3])
                ) if result.analysis.file_changes else ""
                summary = (
                    f"Error #{i}: {error.error_class} in "
                    f"{error.transaction} — Root cause: {root}"
                )
                if files:
                    summary += f". Files: {files}"
                cross_error_context.append(summary)

                # Track multi-pass retries for reporting
                if result.pass_count > 1:
                    multi_pass_retries += 1

                # Record health + quality signals
                health.record_analysis(success=True, tokens_used=result.tokens_used)
                quality_tracker.record_signal(
                    error_class=error.error_class,
                    transaction=error.transaction,
                    confidence=_confidence_float(result.analysis.confidence),
                    iterations_used=result.iterations,
                    tokens_used=result.tokens_used,
                    had_file_changes=bool(result.analysis.file_changes),
                    had_root_cause=bool(result.analysis.root_cause),
                )

            except Exception as e:
                logger.error(f"Analysis failed for {error.error_class}: {e}")
                health.record_analysis(success=False, error_msg=str(e))
                # Fail forward — skip this error, continue

            # Brief pause between errors to help with rate limits
            if i < len(top_errors):
                time.sleep(5)

        # Log code cache stats
        logger.info(f"Code cache: {code_cache.stats}")

        # Save quality signals and log health
        quality_tracker.save()
        health_report_data = health.generate()
        logger.info(
            f"Health: {health_report_data['health']['status']} | "
            f"Success rate: {health_report_data['analysis']['success_rate']}% | "
            f"Cost: ${health_report_data['resources']['estimated_cost_usd']:.4f}"
        )

        # ------------------------------------------------------------------
        # Step 5: Build report
        # ------------------------------------------------------------------
        total_tokens = sum(a.tokens_used for a in analyses)
        total_api_calls = sum(a.api_calls for a in analyses)
        elapsed = time.time() - start_time

        report = RunReport(
            timestamp=datetime.now(UTC).isoformat(),
            lookback=since,
            total_errors_found=len(all_errors),
            errors_filtered=errors_filtered,
            errors_analyzed=len(analyses),
            analyses=analyses,
            total_tokens_used=total_tokens,
            total_api_calls=total_api_calls,
            run_duration_seconds=elapsed,
            multi_pass_retries=multi_pass_retries,
        )

        # ------------------------------------------------------------------
        # Step 5.5: Detect cross-error patterns (with knowledge base)
        # ------------------------------------------------------------------
        try:
            patterns = detect_patterns_with_knowledge(analyses)
            if patterns:
                report.patterns = patterns
                logger.info(f"Detected {len(patterns)} cross-error patterns")
                for p in patterns:
                    logger.info(f"  Pattern: {p.title} ({p.occurrences} errors)")

            ignores = suggest_ignore_updates(analyses)
            if ignores:
                report.ignore_suggestions = ignores
                logger.info(f"Generated {len(ignores)} ignore suggestions")
        except Exception as e:
            logger.error(f"Pattern detection failed: {e}")

        logger.info(
            f"Analysis complete: {report.errors_analyzed} analyzed, "
            f"{report.fixes_found} fixes found, "
            f"{report.high_confidence} high confidence"
        )

        if dry_run:
            _print_dry_run_summary(report)
            return report

        # ------------------------------------------------------------------
        # Step 6: Send Slack report
        # ------------------------------------------------------------------
        try:
            slack = SlackClient()
            slack.send_report(report)
        except Exception as e:
            logger.error(f"Slack report failed: {e}")

        # ------------------------------------------------------------------
        # Step 7: Select top errors for GitHub issues
        # ------------------------------------------------------------------
        candidates = select_for_issues(analyses, max_issues=max_issues)

        # Check WIP limits
        open_count = gh.get_open_nightwatch_issue_count()
        max_open = settings.nightwatch_max_open_issues
        slots = max(0, max_open - open_count)

        if slots == 0:
            logger.warning(
                f"WIP limit reached: {open_count}/{max_open} open nightwatch issues. "
                "Skipping issue creation."
            )
            candidates = []
        elif slots < len(candidates):
            logger.info(f"WIP limit: only {slots} slots available, reducing from {len(candidates)}")
            candidates = candidates[:slots]

        # ------------------------------------------------------------------
        # Step 8: Fetch PR correlations
        # ------------------------------------------------------------------
        correlated_prs = fetch_recent_merged_prs(gh.repo, hours=24)

        # ------------------------------------------------------------------
        # Step 9: Create/update GitHub issues
        # ------------------------------------------------------------------
        issues_created: list[CreatedIssueResult] = []

        for result in candidates:
            try:
                existing = gh.find_existing_issue(result.error)
                if existing:
                    issue_result = gh.add_occurrence_comment(
                        existing, result.error, result.analysis
                    )
                else:
                    # Correlate this error with recent PRs
                    related = correlate_error_with_prs(result.error, correlated_prs)
                    pr_section = format_correlated_prs(related)
                    issue_result = gh.create_issue(result, correlated_prs_section=pr_section)

                issues_created.append(issue_result)
            except Exception as e:
                logger.error(f"Issue creation failed for {result.error.error_class}: {e}")

        report.issues_created = issues_created

        # ------------------------------------------------------------------
        # Step 10: Validate and create draft PR for highest-confidence fix
        # ------------------------------------------------------------------
        pr_result: CreatedPRResult | None = None

        best_fix = _best_fix_candidate(analyses, issues_created)
        if best_fix:
            result, issue_number = best_fix

            # Quality gate: validate file changes before creating PR
            if settings.nightwatch_quality_gate_enabled and result.analysis.file_changes:
                validation = validate_file_changes(result.analysis, gh)

                if not validation.is_valid:
                    logger.warning(
                        f"  Quality gate failed ({len(validation.errors)} errors)"
                    )

                    if settings.nightwatch_quality_gate_correction:
                        logger.info("  Attempting correction...")
                        corrected = _attempt_correction(result, validation, gh, nr)
                        if corrected:
                            revalidation = validate_file_changes(corrected.analysis, gh)
                            if revalidation.is_valid:
                                logger.info("  Correction succeeded — quality gate passed")
                                result = corrected
                                validation = revalidation
                            else:
                                logger.warning("  Correction failed re-validation — skipping PR")
                                pr_validation_failures += 1
                                best_fix = None
                        else:
                            logger.warning("  Correction attempt failed — skipping PR")
                            pr_validation_failures += 1
                            best_fix = None
                    else:
                        logger.warning("  Skipping PR (correction disabled)")
                        pr_validation_failures += 1
                        best_fix = None

                # Log warnings even on success
                for warn in validation.warnings:
                    logger.info(f"  ⚠ {warn}")

        if best_fix:
            result, issue_number = best_fix
            try:
                pr_result = gh.create_pull_request(result, issue_number)
                report.pr_created = pr_result
                logger.info(f"Created draft PR #{pr_result.pr_number}")
            except Exception as e:
                logger.error(f"PR creation failed: {e}")

        report.pr_validation_failures = pr_validation_failures

        # ------------------------------------------------------------------
        # Step 11: Send Slack follow-up with issue/PR links
        # ------------------------------------------------------------------
        if issues_created or pr_result:
            try:
                slack.send_followup(issues_created, pr_result)
            except Exception as e:
                logger.error(f"Slack follow-up failed: {e}")

        # ------------------------------------------------------------------
        # Step 12: Compound — persist analysis results to knowledge base
        # ------------------------------------------------------------------
        if not dry_run and settings.nightwatch_compound_enabled:
            try:
                logger.info("Persisting analysis results to knowledge base...")
                for a_result in analyses:
                    compound_result(a_result)

                # Auto-save high-confidence error patterns
                for a_result in analyses:
                    if (
                        a_result.quality_score >= 0.7
                        and a_result.analysis.root_cause
                    ):
                        try:
                            save_error_pattern(
                                error_class=a_result.error.error_class,
                                transaction=a_result.error.transaction,
                                pattern_description=(
                                    a_result.analysis.root_cause[:500]
                                ),
                                confidence=str(a_result.analysis.confidence),
                            )
                        except Exception as e:
                            logger.warning(f"  Error pattern save failed: {e}")

                # Persist detected patterns
                for pattern in report.patterns:
                    try:
                        write_pattern_doc(pattern)
                    except Exception as e:
                        logger.warning(f"  Pattern doc failed: {e}")

                # Back-fill issue/PR numbers
                for issue_result in issues_created:
                    update_result_metadata(
                        error_class=issue_result.error.error_class,
                        transaction=issue_result.error.transaction,
                        issue_number=issue_result.issue_number,
                    )
                if pr_result and best_fix:
                    pr_error_result, _ = best_fix
                    update_result_metadata(
                        error_class=pr_error_result.error.error_class,
                        transaction=pr_error_result.error.transaction,
                        pr_number=pr_result.pr_number,
                    )

                rebuild_index()
            except Exception as e:
                logger.error(f"Knowledge compounding failed: {e}")

        # ------------------------------------------------------------------
        # Step 13: Save run history for cross-run pattern analysis
        # ------------------------------------------------------------------
        try:
            run_data = {
                "errors_analyzed": [
                    {
                        "error_class": a.error.error_class,
                        "transaction": a.error.transaction,
                        "confidence": str(a.analysis.confidence),
                        "has_fix": a.analysis.has_fix,
                        "root_cause": (a.analysis.root_cause or "")[:200],
                    }
                    for a in analyses
                ],
                "patterns_detected": [
                    {
                        "title": p.title,
                        "error_classes": p.error_classes,
                        "occurrences": p.occurrences,
                    }
                    for p in report.patterns
                ],
                "issues_created": len(issues_created),
                "pr_created": pr_result is not None,
                "total_tokens_used": report.total_tokens_used,
            }
            save_run(run_data)
        except Exception as e:
            logger.warning(f"Failed to save run history: {e}")

        # ------------------------------------------------------------------
        # Step 14: Generate Ralph guardrails if configured
        # ------------------------------------------------------------------
        guardrails_path = settings.nightwatch_guardrails_output
        if guardrails_path:
            try:
                generate_guardrails(run_data, output_path=guardrails_path)
                logger.info(f"Guardrails written to {guardrails_path}")
            except Exception as e:
                logger.warning(f"Guardrails generation failed: {e}")

        # Log registered workflows
        logger.info(f"Registered workflows: {list_registered()}")

        elapsed_final = time.time() - start_time
        report.run_duration_seconds = elapsed_final

        logger.info(
            f"NightWatch complete: "
            f"{len(issues_created)} issues, "
            f"{'1 PR' if pr_result else 'no PR'}, "
            f"{elapsed_final:.0f}s total"
        )

        return report

    finally:
        nr.close()


# ---------------------------------------------------------------------------
# Selection + helpers
# ---------------------------------------------------------------------------


def select_for_issues(
    analyses: list[ErrorAnalysisResult], max_issues: int = 3
) -> list[ErrorAnalysisResult]:
    """Pick the top N errors most likely to produce useful GitHub issues.

    Prioritizes errors where Claude has high/medium confidence with
    a concrete fix or clear actionable next steps.
    """
    candidates: list[ErrorAnalysisResult] = []

    for result in analyses:
        a = result.analysis

        # Skip low-confidence vague analyses
        if a.confidence == "low" and not a.has_fix:
            continue

        # Score for issue selection (different from error ranking)
        score = 0.0
        if a.has_fix:
            score += 0.5
        if a.confidence == "high":
            score += 0.3
        elif a.confidence == "medium":
            score += 0.15
        if a.file_changes:
            score += 0.1
        if a.suggested_next_steps:
            score += 0.05
        # Higher occurrence errors are more impactful
        score += min(result.error.occurrences / 200, 0.1)

        result.issue_score = score
        candidates.append(result)

    candidates.sort(key=lambda r: r.issue_score, reverse=True)
    return candidates[:max_issues]


def _best_fix_candidate(
    analyses: list[ErrorAnalysisResult],
    issues_created: list[CreatedIssueResult],
) -> tuple[ErrorAnalysisResult, int] | None:
    """Find the best candidate for a draft PR (1 per run).

    Requirements:
    - has_fix=True with file_changes
    - high confidence preferred
    - Must have a corresponding created issue
    """
    # Build issue number lookup
    issue_map: dict[str, int] = {}
    for issue in issues_created:
        if issue.action == "created":
            key = f"{issue.error.error_class}:{issue.error.transaction}"
            issue_map[key] = issue.issue_number

    best: ErrorAnalysisResult | None = None
    best_issue: int = 0

    for result in analyses:
        a = result.analysis
        if not a.has_fix or not a.file_changes:
            continue

        key = f"{result.error.error_class}:{result.error.transaction}"
        issue_number = issue_map.get(key)
        if not issue_number:
            continue

        if best is None or (
            a.confidence == "high" and (best.analysis.confidence != "high")
        ):
            best = result
            best_issue = issue_number

    if best and best_issue:
        return best, best_issue
    return None


def _attempt_correction(
    result: ErrorAnalysisResult,
    validation: Any,
    github_client: Any,
    newrelic_client: Any,
) -> ErrorAnalysisResult | None:
    """One-shot correction: send validation errors to Claude, get fixed file_changes.

    Creates a fresh Claude conversation with the validation errors and
    original analysis, asking Claude to fix the specific issues found.

    Returns corrected ErrorAnalysisResult or None on failure.
    """
    from nightwatch.models import Analysis, FileChange
    from nightwatch.prompts import SYSTEM_PROMPT

    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # Build correction prompt
    error_list = "\n".join(f"- {e}" for e in validation.errors)
    warning_list = (
        "\n".join(f"- {w}" for w in validation.warnings) if validation.warnings else "None"
    )

    file_changes_desc = "\n".join(
        f"- {fc.action} {fc.path}: {fc.description}" for fc in result.analysis.file_changes
    )

    correction_prompt = f"""## Correction Request

Your previous analysis proposed file changes that failed validation.

### Original Analysis
**Title**: {result.analysis.title}
**Root Cause**: {result.analysis.root_cause}

### Proposed File Changes
{file_changes_desc}

### Validation Errors (MUST FIX)
{error_list}

### Validation Warnings
{warning_list}

Please provide corrected file changes that fix all validation errors.
Respond with the same JSON structure as the original analysis, but with corrected file_changes.

```json
{{
    "title": "...",
    "reasoning": "...",
    "root_cause": "...",
    "has_fix": true,
    "confidence": "...",
    "file_changes": [
        {{"path": "...", "action": "modify|create", "content": "...", "description": "..."}}
    ],
    "suggested_next_steps": []
}}
```"""

    try:
        response = client.messages.create(
            model=settings.nightwatch_model,
            max_tokens=8192,
            system=[{"type": "text", "text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": correction_prompt}],
        )

        # Parse response
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        # Try to extract JSON
        json_start = text.find("```json")
        json_end = text.find("```", json_start + 7) if json_start != -1 else -1

        if json_start != -1 and json_end != -1:
            json_str = text[json_start + 7 : json_end].strip()
            data = json.loads(json_str)
        else:
            data = json.loads(text)

        file_changes = [
            FileChange(
                path=fc["path"],
                action=fc.get("action", "modify"),
                content=fc.get("content"),
                description=fc.get("description", ""),
            )
            for fc in data.get("file_changes", [])
        ]

        corrected_analysis = Analysis(
            title=data.get("title", result.analysis.title),
            reasoning=data.get("reasoning", result.analysis.reasoning),
            root_cause=data.get("root_cause", result.analysis.root_cause),
            has_fix=data.get("has_fix", True),
            confidence=data.get("confidence", result.analysis.confidence),
            file_changes=file_changes,
            suggested_next_steps=data.get(
                "suggested_next_steps", result.analysis.suggested_next_steps
            ),
        )

        # Build corrected result, preserving original metadata
        corrected = ErrorAnalysisResult(
            error=result.error,
            analysis=corrected_analysis,
            traces=result.traces,
            iterations=result.iterations,
            tokens_used=result.tokens_used,
            api_calls=result.api_calls + 1,
            pass_count=result.pass_count,
        )

        return corrected

    except Exception as e:
        logger.error(f"  Correction failed: {e}")
        return None


def _confidence_float(confidence: str) -> float:
    """Convert confidence string to float for quality tracking."""
    return {"high": 0.9, "medium": 0.6, "low": 0.2}.get(str(confidence).lower(), 0.0)


def _print_dry_run_summary(report: RunReport) -> None:
    """Print a summary for dry-run mode (no side effects)."""
    print(f"\n{'='*60}")
    print("  NightWatch Dry Run Summary")
    print(f"{'='*60}")
    print(f"  Errors found:    {report.total_errors_found}")
    print(f"  Errors filtered: {report.errors_filtered}")
    print(f"  Errors analyzed: {report.errors_analyzed}")
    print(f"  Fixes found:     {report.fixes_found}")
    print(f"  High confidence: {report.high_confidence}")
    print(f"  Tokens used:     {report.total_tokens_used:,}")
    print(f"  API calls:       {report.total_api_calls}")
    print(f"  Duration:        {report.run_duration_seconds:.1f}s")
    if report.multi_pass_retries:
        print(f"  Multi-pass:      {report.multi_pass_retries} retries")
    if report.pr_validation_failures:
        print(f"  PR gate fails:   {report.pr_validation_failures}")
    print(f"{'='*60}")

    for i, result in enumerate(report.analyses, 1):
        e = result.error
        a = result.analysis
        status = "FIX" if a.has_fix else "INVESTIGATE"
        print(f"\n  {i}. [{a.confidence.upper()}] {e.error_class}")
        print(f"     {e.transaction} ({e.occurrences} occurrences)")
        print(f"     Status: {status}")
        if result.pass_count > 1:
            print(f"     Passes: {result.pass_count}")
        print(f"     {a.reasoning[:150]}...")

    print()
