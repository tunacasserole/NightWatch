"""Main orchestration pipeline — fetch → rank → trace → analyze → report → issues → PR → notify."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from nightwatch.analyzer import analyze_error
from nightwatch.config import get_settings
from nightwatch.correlation import (
    correlate_error_with_prs,
    fetch_recent_merged_prs,
    format_correlated_prs,
)
from nightwatch.github import GitHubClient
from nightwatch.models import (
    CreatedIssueResult,
    CreatedPRResult,
    ErrorAnalysisResult,
    RunReport,
)
from nightwatch.newrelic import (
    NewRelicClient,
    filter_errors,
    load_ignore_patterns,
    rank_errors,
)
from nightwatch.slack import SlackClient

logger = logging.getLogger("nightwatch")


def run(
    since: str | None = None,
    max_errors: int | None = None,
    max_issues: int | None = None,
    dry_run: bool | None = None,
    verbose: bool = False,
    model: str | None = None,
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
        # Step 4: Analyze each error with Claude
        # ------------------------------------------------------------------
        logger.info("Starting Claude analysis...")
        analyses: list[ErrorAnalysisResult] = []

        for i, error in enumerate(top_errors, 1):
            logger.info(
                f"Analyzing {i}/{len(top_errors)}: "
                f"{error.error_class} in {error.transaction} "
                f"({error.occurrences} occurrences)"
            )
            try:
                result = analyze_error(
                    error=error,
                    traces=traces_map[id(error)],
                    github_client=gh,
                    newrelic_client=nr,
                )
                analyses.append(result)
            except Exception as e:
                logger.error(f"Analysis failed for {error.error_class}: {e}")
                # Fail forward — skip this error, continue

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
        )

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
        # Step 10: Create draft PR for highest-confidence fix
        # ------------------------------------------------------------------
        pr_result: CreatedPRResult | None = None

        best_fix = _best_fix_candidate(analyses, issues_created)
        if best_fix:
            result, issue_number = best_fix
            try:
                pr_result = gh.create_pull_request(result, issue_number)
                report.pr_created = pr_result
                logger.info(f"Created draft PR #{pr_result.pr_number}")
            except Exception as e:
                logger.error(f"PR creation failed: {e}")

        # ------------------------------------------------------------------
        # Step 11: Send Slack follow-up with issue/PR links
        # ------------------------------------------------------------------
        if issues_created or pr_result:
            try:
                slack.send_followup(issues_created, pr_result)
            except Exception as e:
                logger.error(f"Slack follow-up failed: {e}")

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
    print(f"{'='*60}")

    for i, result in enumerate(report.analyses, 1):
        e = result.error
        a = result.analysis
        status = "FIX" if a.has_fix else "INVESTIGATE"
        print(f"\n  {i}. [{a.confidence.upper()}] {e.error_class}")
        print(f"     {e.transaction} ({e.occurrences} occurrences)")
        print(f"     Status: {status}")
        print(f"     {a.reasoning[:150]}...")

    print()
