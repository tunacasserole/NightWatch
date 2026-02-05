"""Cross-error pattern detection — identifies systemic issues across multiple error analyses.

Analyzes completed ErrorAnalysisResult objects for:
- Module clustering: multiple errors touching the same files/directories
- Error class clustering: same error class appearing across transactions
- File hotspots: files referenced in multiple analyses (fix targets)
- Knowledge-base integration: recurring patterns across runs
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import yaml

from nightwatch.knowledge import _render_frontmatter, _slugify
from nightwatch.models import DetectedPattern, ErrorAnalysisResult, IgnoreSuggestion

logger = logging.getLogger("nightwatch.patterns")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_patterns(
    analyses: list[ErrorAnalysisResult],
    min_cluster_size: int = 2,
) -> list[DetectedPattern]:
    """Detect cross-error patterns from a batch of completed analyses.

    Runs three detectors and merges their results:
    1. Module clustering — errors touching the same directories
    2. Error class clustering — same error class across transactions
    3. File hotspots — files proposed for changes in multiple analyses

    Args:
        analyses: Completed analysis results from a single run.
        min_cluster_size: Minimum number of errors to form a pattern.

    Returns:
        List of DetectedPattern objects, sorted by occurrence count descending.
    """
    if len(analyses) < min_cluster_size:
        return []

    patterns: list[DetectedPattern] = []

    patterns.extend(_detect_module_clusters(analyses, min_cluster_size))
    patterns.extend(_detect_error_class_clusters(analyses, min_cluster_size))
    patterns.extend(_detect_file_hotspots(analyses, min_cluster_size))

    # Sort by occurrences descending, then by title for stability
    patterns.sort(key=lambda p: (-p.occurrences, p.title))

    return patterns


def suggest_ignores(
    analyses: list[ErrorAnalysisResult],
    min_occurrences: int = 3,
) -> list[IgnoreSuggestion]:
    """Suggest errors that could be added to ignore.yml.

    Candidates:
    - Low-confidence analyses with no fix across multiple occurrences
    - Known transient/noise patterns (timeout, rate limit, etc.)

    Args:
        analyses: Completed analysis results from a single run.
        min_occurrences: Minimum occurrences to suggest ignoring.

    Returns:
        List of IgnoreSuggestion objects.
    """
    suggestions: list[IgnoreSuggestion] = []

    # Noise patterns — known transient error classes
    noise_indicators = {
        "timeout": "Timeout errors are typically transient network issues",
        "rate limit": "Rate limiting errors are expected under load",
        "connection reset": "Connection resets are transient infrastructure issues",
        "ssl": "SSL errors are often transient certificate/handshake issues",
        "econnrefused": "Connection refused errors are transient",
        "deadlock": "Deadlock errors may be transient under high concurrency",
    }

    for result in analyses:
        error = result.error
        analysis = result.analysis

        # Criterion 1: Low confidence, no fix, high occurrence
        if (
            analysis.confidence == "low"
            and not analysis.has_fix
            and error.occurrences >= min_occurrences
        ):
            suggestions.append(
                IgnoreSuggestion(
                    pattern=error.error_class,
                    match="exact",
                    reason=(
                        f"Low confidence analysis with no fix "
                        f"({error.occurrences} occurrences)"
                    ),
                    evidence=(
                        f"Analyzed in {error.transaction} — "
                        f"root cause: {analysis.root_cause[:100]}"
                    ),
                )
            )

        # Criterion 2: Known noise patterns in error class or message
        error_text = f"{error.error_class} {error.message}".lower()
        for indicator, reason in noise_indicators.items():
            if indicator in error_text:
                suggestions.append(
                    IgnoreSuggestion(
                        pattern=indicator,
                        match="contains",
                        reason=reason,
                        evidence=(
                            f"Matched in {error.error_class}: "
                            f"{error.message[:100]}"
                        ),
                    )
                )
                break  # One suggestion per error

    # Deduplicate by pattern
    seen: set[str] = set()
    unique: list[IgnoreSuggestion] = []
    for s in suggestions:
        key = f"{s.match}:{s.pattern}"
        if key not in seen:
            seen.add(key)
            unique.append(s)

    return unique


# ---------------------------------------------------------------------------
# Internal detectors
# ---------------------------------------------------------------------------


def _detect_module_clusters(
    analyses: list[ErrorAnalysisResult],
    min_size: int,
) -> list[DetectedPattern]:
    """Find directories with multiple errors touching them.

    Extracts directories from:
    - File changes proposed by Claude
    - Transaction names (e.g. Controller/orders/update → app/controllers/orders)
    """
    # Map: directory → list of error classes that touch it
    dir_to_errors: dict[str, list[str]] = {}

    for result in analyses:
        dirs: set[str] = set()

        # From file changes
        for fc in result.analysis.file_changes:
            parent = str(PurePosixPath(fc.path).parent)
            if parent and parent != ".":
                dirs.add(parent)

        # From transaction name (heuristic: Controller/X → app/controllers)
        tx = result.error.transaction
        tx_dir = _transaction_to_directory(tx)
        if tx_dir:
            dirs.add(tx_dir)

        for d in dirs:
            dir_to_errors.setdefault(d, []).append(result.error.error_class)

    patterns: list[DetectedPattern] = []
    for directory, error_classes in dir_to_errors.items():
        if len(error_classes) >= min_size:
            unique_classes = sorted(set(error_classes))
            patterns.append(
                DetectedPattern(
                    title=f"Multiple errors in {directory}",
                    description=(
                        f"{len(error_classes)} errors touch the `{directory}` module. "
                        f"Error classes: {', '.join(unique_classes)}"
                    ),
                    error_classes=unique_classes,
                    modules=[directory],
                    occurrences=len(error_classes),
                    suggestion=(
                        f"Review `{directory}` for systemic issues — "
                        f"{len(unique_classes)} distinct error types in one module."
                    ),
                    pattern_type="systemic_issue",
                )
            )

    return patterns


def _detect_error_class_clusters(
    analyses: list[ErrorAnalysisResult],
    min_size: int,
) -> list[DetectedPattern]:
    """Find error classes appearing in multiple transactions."""
    # Map: error_class → list of transactions
    class_to_txs: dict[str, list[str]] = {}

    for result in analyses:
        ec = result.error.error_class
        tx = result.error.transaction
        class_to_txs.setdefault(ec, []).append(tx)

    patterns: list[DetectedPattern] = []
    for error_class, transactions in class_to_txs.items():
        if len(transactions) >= min_size:
            unique_txs = sorted(set(transactions))
            # Identify common modules from transaction names
            modules = sorted(
                _transaction_to_directory(tx)
                for tx in transactions
                if _transaction_to_directory(tx)
            )

            patterns.append(
                DetectedPattern(
                    title=f"{error_class} across {len(unique_txs)} transactions",
                    description=(
                        f"`{error_class}` appears in {len(transactions)} analyses "
                        f"across transactions: {', '.join(unique_txs)}"
                    ),
                    error_classes=[error_class],
                    modules=modules,
                    occurrences=len(transactions),
                    suggestion=(
                        f"Investigate common root cause for `{error_class}` — "
                        f"may be a shared dependency or pattern issue."
                    ),
                    pattern_type="recurring_error",
                )
            )

    return patterns


def _detect_file_hotspots(
    analyses: list[ErrorAnalysisResult],
    min_size: int,
) -> list[DetectedPattern]:
    """Find files proposed for changes in multiple analyses."""
    # Map: file_path → list of error classes proposing changes
    file_to_errors: dict[str, list[str]] = {}

    for result in analyses:
        for fc in result.analysis.file_changes:
            file_to_errors.setdefault(fc.path, []).append(
                result.error.error_class
            )

    patterns: list[DetectedPattern] = []
    for file_path, error_classes in file_to_errors.items():
        if len(error_classes) >= min_size:
            unique_classes = sorted(set(error_classes))
            parent = str(PurePosixPath(file_path).parent)

            patterns.append(
                DetectedPattern(
                    title=f"Hotspot: {file_path}",
                    description=(
                        f"`{file_path}` is targeted by {len(error_classes)} "
                        f"separate fix proposals. Error classes: {', '.join(unique_classes)}"
                    ),
                    error_classes=unique_classes,
                    modules=[parent] if parent != "." else [],
                    occurrences=len(error_classes),
                    suggestion=(
                        f"Consider a comprehensive review of `{file_path}` — "
                        f"multiple errors point here."
                    ),
                    pattern_type="systemic_issue",
                )
            )

    return patterns


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _transaction_to_directory(transaction: str) -> str:
    """Heuristic: map a transaction name to a likely source directory.

    Examples:
        Controller/orders/update → app/controllers/orders
        Controller/api/v2/products/index → app/controllers/api/v2/products
        OtherTransaction/Rake/some_task → (empty — not mappable)
        WebTransaction/Sinatra/GET /health → (empty)
    """
    # Skip non-Controller transactions
    if not transaction.startswith("Controller/"):
        return ""

    parts = transaction.split("/")
    if len(parts) < 3:
        return ""

    # Drop "Controller" prefix and the action (last part)
    # Controller/orders/update → ["Controller", "orders", "update"]
    # → app/controllers/orders
    path_parts = parts[1:-1]  # Remove "Controller" and action
    if not path_parts:
        return ""

    return "app/controllers/" + "/".join(path_parts)


def _extract_file_paths(analyses: list[ErrorAnalysisResult]) -> Counter[str]:
    """Count how often each file path appears across all analyses."""
    counter: Counter[str] = Counter()
    for result in analyses:
        for fc in result.analysis.file_changes:
            counter[fc.path] += 1
    return counter


# ---------------------------------------------------------------------------
# Knowledge-base integration
# ---------------------------------------------------------------------------

TRANSIENT_INDICATORS: set[str] = {
    "timeout",
    "timed out",
    "rate limit",
    "rate_limit",
    "connection reset",
    "connection refused",
    "econnrefused",
    "econnreset",
    "ssl",
    "deadlock",
    "lock wait",
    "too many connections",
    "service unavailable",
    "502",
    "503",
    "504",
}


def detect_patterns_with_knowledge(
    analyses: list[ErrorAnalysisResult],
    knowledge_dir: str | None = None,
    min_cluster_size: int = 2,
) -> list[DetectedPattern]:
    """Detect patterns using both current run data AND knowledge base history.

    Extends detect_patterns() with:
    - Cross-run recurring errors (from knowledge base)
    - Transient error detection

    Args:
        analyses: Completed analysis results from current run.
        knowledge_dir: Override knowledge directory.
        min_cluster_size: Minimum errors to form a pattern.

    Returns:
        Combined list of DetectedPattern objects, sorted by occurrences desc.
    """
    # Start with current-run patterns
    patterns = detect_patterns(analyses, min_cluster_size)

    # Add cross-run patterns from knowledge base
    patterns.extend(
        _find_recurring_in_knowledge(analyses, knowledge_dir)
    )

    # Add transient error detection
    patterns.extend(_detect_transient_errors(analyses))

    # Re-sort combined set
    patterns.sort(key=lambda p: (-p.occurrences, p.title))
    return patterns


def write_pattern_doc(
    pattern: DetectedPattern,
    knowledge_dir: str | None = None,
) -> Path:
    """Persist a detected pattern as a knowledge-base document.

    Creates: nightwatch/knowledge/patterns/YYYY-MM-DD_<slug>.md
    """
    from nightwatch.config import get_settings

    settings = get_settings()
    kb_dir = Path(knowledge_dir or settings.nightwatch_knowledge_dir)
    patterns_dir = kb_dir / "patterns"
    patterns_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    slug = _slugify(pattern.title)
    filename = f"{date_str}_{slug}.md"
    doc_path = patterns_dir / filename

    frontmatter = {
        "title": pattern.title,
        "pattern_type": pattern.pattern_type,
        "error_classes": pattern.error_classes,
        "modules": pattern.modules,
        "occurrences": pattern.occurrences,
        "first_detected": date_str,
    }

    body_parts = [
        f"# {pattern.title}",
        "",
        "## Description",
        "",
        pattern.description,
        "",
        "## Suggestion",
        "",
        pattern.suggestion,
        "",
    ]

    body = "\n".join(body_parts)
    content = _render_frontmatter(frontmatter) + body
    doc_path.write_text(content)

    logger.info(f"  Pattern doc: {filename}")
    return doc_path


def suggest_ignore_updates(
    analyses: list[ErrorAnalysisResult],
    ignore_path: str | Path | None = None,
    min_occurrences: int = 3,
) -> list[IgnoreSuggestion]:
    """Suggest new ignore.yml entries, excluding already-ignored patterns.

    Extends suggest_ignores() by checking the current ignore.yml to avoid
    suggesting patterns that are already configured.
    """
    raw_suggestions = suggest_ignores(analyses, min_occurrences)

    current_patterns = _get_current_ignore_patterns(ignore_path)
    if not current_patterns:
        return raw_suggestions

    # Filter out already-configured patterns
    new_suggestions: list[IgnoreSuggestion] = []
    for suggestion in raw_suggestions:
        pattern_lower = suggestion.pattern.lower()
        already_covered = any(
            pattern_lower in existing or existing in pattern_lower
            for existing in current_patterns
        )
        if not already_covered:
            new_suggestions.append(suggestion)

    return new_suggestions


def _find_recurring_in_knowledge(
    analyses: list[ErrorAnalysisResult],
    knowledge_dir: str | None = None,
) -> list[DetectedPattern]:
    """Find error classes from this run that also appear in the knowledge base.

    Detects errors that recur across runs — a strong signal for systemic issues.
    """
    from nightwatch.config import get_settings

    settings = get_settings()
    kb_dir = Path(knowledge_dir or settings.nightwatch_knowledge_dir)
    index_path = kb_dir / "index.yml"

    if not index_path.exists():
        return []

    try:
        index = yaml.safe_load(index_path.read_text()) or {}
    except (yaml.YAMLError, OSError):
        return []

    solutions = index.get("solutions", [])
    if not solutions:
        return []

    # Build lookup: error_class → count in knowledge base
    kb_class_count: Counter[str] = Counter()
    for entry in solutions:
        ec = entry.get("error_class", "")
        if ec:
            kb_class_count[ec] += 1

    # Find matches with current run
    patterns: list[DetectedPattern] = []
    current_classes = {r.error.error_class for r in analyses}

    for error_class in current_classes:
        kb_count = kb_class_count.get(error_class, 0)
        if kb_count >= 1:  # Appeared at least once before
            total = kb_count + 1  # +1 for current run
            patterns.append(
                DetectedPattern(
                    title=f"Recurring: {error_class}",
                    description=(
                        f"`{error_class}` has appeared in {total} runs "
                        f"({kb_count} prior + current run)."
                    ),
                    error_classes=[error_class],
                    modules=[],
                    occurrences=total,
                    suggestion=(
                        "This error recurs across runs. "
                        "Consider prioritizing a permanent fix."
                    ),
                    pattern_type="recurring_error",
                )
            )

    return patterns


def _detect_transient_errors(
    analyses: list[ErrorAnalysisResult],
) -> list[DetectedPattern]:
    """Detect errors that match transient/noise patterns."""
    patterns: list[DetectedPattern] = []
    transient_classes: list[str] = []

    for result in analyses:
        if _is_transient_error(result):
            transient_classes.append(result.error.error_class)

    if len(transient_classes) >= 1:
        unique = sorted(set(transient_classes))
        patterns.append(
            DetectedPattern(
                title=f"Transient noise: {len(unique)} error types",
                description=(
                    f"{len(transient_classes)} errors match transient/noise patterns: "
                    f"{', '.join(unique)}"
                ),
                error_classes=unique,
                modules=[],
                occurrences=len(transient_classes),
                suggestion=(
                    "Consider adding these to ignore.yml to reduce noise "
                    "in future runs."
                ),
                pattern_type="transient_noise",
            )
        )

    return patterns


def _is_transient_error(result: ErrorAnalysisResult) -> bool:
    """Check if an error matches known transient/noise patterns."""
    error_text = (
        f"{result.error.error_class} {result.error.message}"
    ).lower()
    return any(indicator in error_text for indicator in TRANSIENT_INDICATORS)


def _get_current_ignore_patterns(
    ignore_path: str | Path | None = None,
) -> set[str]:
    """Load current ignore.yml patterns as a set of lowercase strings."""
    ignore_path = Path("ignore.yml") if ignore_path is None else Path(ignore_path)

    if not ignore_path.exists():
        return set()

    try:
        data = yaml.safe_load(ignore_path.read_text()) or {}
    except (yaml.YAMLError, OSError):
        return set()

    patterns: set[str] = set()
    for entry in data.get("ignore", []):
        if isinstance(entry, dict):
            p = entry.get("pattern", "")
            if p:
                patterns.add(p.lower())
        elif isinstance(entry, str):
            patterns.add(entry.lower())

    return patterns
