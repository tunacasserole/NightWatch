"""PR correlation service — link errors to recently merged PRs."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

from github import GithubException
from github.Repository import Repository

from nightwatch.models import CorrelatedPR, ErrorGroup

logger = logging.getLogger("nightwatch.correlation")


def fetch_recent_merged_prs(repo: Repository, hours: int = 24) -> list[CorrelatedPR]:
    """Fetch PRs merged to main in the last N hours."""
    since = datetime.now(UTC) - timedelta(hours=hours)
    logger.info(f"Fetching PRs merged since {since.isoformat()}")

    try:
        pulls = repo.get_pulls(state="closed", sort="updated", direction="desc", base="main")
        results: list[CorrelatedPR] = []

        for pr in pulls:
            if not pr.merged_at:
                continue

            merged_at = pr.merged_at
            if merged_at.tzinfo is None:
                merged_at = merged_at.replace(tzinfo=UTC)

            if merged_at < since:
                break  # Past our window

            try:
                changed_files = [f.filename for f in pr.get_files()]
            except GithubException:
                changed_files = []

            results.append(
                CorrelatedPR(
                    number=pr.number,
                    title=pr.title,
                    url=pr.html_url,
                    merged_at=merged_at.isoformat(),
                    changed_files=changed_files,
                )
            )

            if len(results) >= 10:
                break

        logger.info(f"Found {len(results)} merged PRs in last {hours}h")
        return results

    except GithubException as e:
        logger.error(f"Error fetching recent PRs: {e}")
        return []


def correlate_error_with_prs(
    error: ErrorGroup, prs: list[CorrelatedPR]
) -> list[CorrelatedPR]:
    """Find PRs that changed files related to this error. Returns related PRs sorted by overlap."""
    search_terms = _extract_search_terms(error.error_class, error.transaction)
    if not search_terms:
        return []

    related: list[CorrelatedPR] = []
    for pr in prs:
        overlap = 0
        for f in pr.changed_files:
            f_lower = f.lower()
            if any(term in f_lower for term in search_terms):
                overlap += 1
        if overlap > 0:
            pr.overlap_score = overlap / max(len(pr.changed_files), 1)
            related.append(pr)

    return sorted(related, key=lambda p: p.overlap_score, reverse=True)


def format_correlated_prs(prs: list[CorrelatedPR]) -> str | None:
    """Format correlated PRs as a markdown section for the GitHub issue body."""
    if not prs:
        return None

    lines = ["## Recent Related Changes", ""]
    lines.append("| PR | Title | Merged | Overlap |")
    lines.append("|----|-------|--------|---------|")

    now = datetime.now(UTC)
    for pr in prs[:5]:
        title = pr.title[:40] + "..." if len(pr.title) > 40 else pr.title
        merged = _time_ago(pr.merged_at, now)
        lines.append(
            f"| [#{pr.number}]({pr.url}) | {title} | {merged} | {pr.overlap_score:.0%} |"
        )

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_search_terms(error_class: str, transaction: str) -> list[str]:
    """Extract file-name search terms from error class and transaction."""
    terms: set[str] = set()

    # Parse transaction (e.g. "Controller/products/show")
    if transaction and "/" in transaction:
        for part in transaction.lower().split("/"):
            if part and part not in ("controller", "action", "nested"):
                terms.add(part)
                if part.endswith("s") and len(part) > 2:
                    terms.add(part[:-1])
                if not part.endswith("_controller"):
                    terms.add(f"{part}_controller")

    # Parse error class (e.g. "ProductsController::NotFoundError")
    if error_class and "::" in error_class:
        for part in error_class.split("::"):
            if "error" in part.lower():
                continue
            snake = _camel_to_snake(part)
            terms.add(snake)
            if snake.endswith("_controller"):
                terms.add(snake[:-11])
    elif error_class:
        snake = _camel_to_snake(error_class)
        if "error" not in snake:
            terms.add(snake)

    return [t for t in terms if t and len(t) > 2]


def _camel_to_snake(name: str) -> str:
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _time_ago(iso_str: str, reference: datetime) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return "?"

    hours = (reference - dt).total_seconds() / 3600
    if hours < 1:
        return f"{int(hours * 60)}m ago"
    if hours < 24:
        return f"{int(hours)}h ago"
    return f"{int(hours / 24)}d ago"
