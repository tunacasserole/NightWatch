"""Knowledge base — compound engineering pattern for persistent analysis results.

Stores error analysis results as YAML-frontmatter Markdown documents.
Provides index-first search to inject prior knowledge into new analyses.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml

from nightwatch.config import get_settings
from nightwatch.models import ErrorAnalysisResult, ErrorGroup, PriorAnalysis

logger = logging.getLogger("nightwatch.knowledge")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_prior_knowledge(
    error: ErrorGroup,
    max_results: int = 3,
    knowledge_dir: str | None = None,
) -> list[PriorAnalysis]:
    """Search knowledge base for prior analyses of similar errors.

    Strategy (from compound-engineering 'learnings-researcher'):
    1. Load index.yml (small, structured)
    2. Score each entry against error (error_class=0.5, transaction=0.3, tag overlap=0.1 each)
    3. Read only top N matching full documents
    4. Return structured PriorAnalysis objects
    """
    settings = get_settings()
    kb_dir = Path(knowledge_dir or settings.nightwatch_knowledge_dir)
    index_path = kb_dir / "index.yml"

    if not index_path.exists():
        return []

    try:
        index = yaml.safe_load(index_path.read_text()) or {}
    except (yaml.YAMLError, OSError) as e:
        logger.warning(f"Failed to read knowledge index: {e}")
        return []

    solutions = index.get("solutions", [])
    if not solutions:
        return []

    error_tags = _extract_tags(error)

    # Score and rank
    scored: list[tuple[float, dict]] = []
    for entry in solutions:
        score = _match_score(error, entry, error_tags)
        if score > 0.0:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:max_results]

    # Read full docs for top matches
    results: list[PriorAnalysis] = []
    for score, entry in top:
        doc_path = kb_dir / entry["file"]
        if not doc_path.exists():
            continue

        try:
            frontmatter, body = _parse_frontmatter(doc_path.read_text())
        except OSError:
            continue

        results.append(PriorAnalysis(
            error_class=frontmatter.get("error_class", ""),
            transaction=frontmatter.get("transaction", ""),
            root_cause=frontmatter.get("root_cause", ""),
            fix_confidence=frontmatter.get("fix_confidence", "low"),
            has_fix=frontmatter.get("has_fix", False),
            summary=body[:500],
            match_score=score,
            source_file=str(doc_path),
            first_detected=frontmatter.get("first_detected", ""),
        ))

    return results


def compound_result(result: ErrorAnalysisResult, knowledge_dir: str | None = None) -> Path:
    """Persist an ErrorAnalysisResult as a knowledge document.

    Creates: nightwatch/knowledge/errors/YYYY-MM-DD_<slug>.md
    """
    settings = get_settings()
    kb_dir = Path(knowledge_dir or settings.nightwatch_knowledge_dir)
    errors_dir = kb_dir / "errors"
    errors_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    slug = _slugify(f"{result.error.error_class}_{result.error.transaction}")
    filename = f"{date_str}_{slug}.md"
    doc_path = errors_dir / filename

    error_tags = _extract_tags(result.error)

    frontmatter = {
        "error_class": result.error.error_class,
        "transaction": result.error.transaction,
        "message": result.error.message[:300],
        "occurrences": result.error.occurrences,
        "root_cause": result.analysis.root_cause,
        "fix_confidence": str(result.analysis.confidence),
        "has_fix": result.analysis.has_fix,
        "issue_number": None,
        "pr_number": None,
        "tags": sorted(error_tags),
        "first_detected": date_str,
        "run_id": datetime.now(UTC).isoformat(),
        "iterations_used": result.iterations,
        "tokens_used": result.tokens_used,
    }

    body_parts = [
        f"# {result.analysis.title}",
        "",
        "## Root Cause",
        "",
        result.analysis.root_cause,
        "",
        "## Analysis",
        "",
        result.analysis.reasoning,
        "",
    ]

    if result.analysis.suggested_next_steps:
        body_parts.extend(["## Next Steps", ""])
        for step in result.analysis.suggested_next_steps:
            body_parts.append(f"- {step}")
        body_parts.append("")

    if result.analysis.file_changes:
        body_parts.extend(["## File Changes", ""])
        for fc in result.analysis.file_changes:
            body_parts.append(f"- `{fc.path}`: {fc.action} — {fc.description}")
        body_parts.append("")

    body = "\n".join(body_parts)
    content = _render_frontmatter(frontmatter) + body

    doc_path.write_text(content)
    logger.info(f"  Compounded: {filename}")
    return doc_path


def rebuild_index(knowledge_dir: str | None = None) -> None:
    """Rebuild nightwatch/knowledge/index.yml from all documents.

    Scans errors/ and patterns/ directories.
    Writes structured YAML with solutions[] and patterns[] arrays.
    """
    settings = get_settings()
    kb_dir = Path(knowledge_dir or settings.nightwatch_knowledge_dir)
    errors_dir = kb_dir / "errors"
    patterns_dir = kb_dir / "patterns"

    solutions: list[dict] = []
    patterns: list[dict] = []

    # Scan error docs
    if errors_dir.exists():
        for doc_path in sorted(errors_dir.glob("*.md")):
            try:
                frontmatter, _ = _parse_frontmatter(doc_path.read_text())
                if not frontmatter:
                    continue
                solutions.append({
                    "file": f"errors/{doc_path.name}",
                    "error_class": frontmatter.get("error_class", ""),
                    "transaction": frontmatter.get("transaction", ""),
                    "fix_confidence": frontmatter.get("fix_confidence", "low"),
                    "has_fix": frontmatter.get("has_fix", False),
                    "tags": frontmatter.get("tags", []),
                })
            except (OSError, yaml.YAMLError) as e:
                logger.warning(f"Failed to index {doc_path.name}: {e}")

    # Scan pattern docs
    if patterns_dir.exists():
        for doc_path in sorted(patterns_dir.glob("*.md")):
            try:
                frontmatter, _ = _parse_frontmatter(doc_path.read_text())
                if not frontmatter:
                    continue
                patterns.append({
                    "file": f"patterns/{doc_path.name}",
                    "title": frontmatter.get("title", ""),
                    "pattern_type": frontmatter.get("pattern_type", ""),
                    "error_classes": frontmatter.get("error_classes", []),
                })
            except (OSError, yaml.YAMLError) as e:
                logger.warning(f"Failed to index {doc_path.name}: {e}")

    index = {
        "last_updated": datetime.now(UTC).isoformat(),
        "total_solutions": len(solutions),
        "total_patterns": len(patterns),
        "solutions": solutions,
        "patterns": patterns,
    }

    index_path = kb_dir / "index.yml"
    index_path.write_text(yaml.dump(index, default_flow_style=False, sort_keys=False))
    logger.info(f"  Knowledge index rebuilt: {len(solutions)} solutions, {len(patterns)} patterns")


def build_knowledge_context(
    error: ErrorGroup,
    max_results: int = 3,
    max_chars: int = 1500,
    knowledge_dir: str | None = None,
) -> str:
    """Search knowledge base and format results as a prompt context section.

    Convenience function combining search_prior_knowledge + formatting.
    Returns empty string if no relevant knowledge found.
    """
    prior = search_prior_knowledge(error, max_results=max_results, knowledge_dir=knowledge_dir)
    if not prior:
        return ""

    parts = ["## Prior Knowledge from NightWatch Knowledge Base"]
    for i, p in enumerate(prior, 1):
        section = f"\n### Prior Analysis #{i} (match: {p.match_score:.1%})"
        section += f"\n- **Error**: `{p.error_class}` in `{p.transaction}`"
        section += f"\n- **Root Cause**: {p.root_cause[:200]}"
        section += f"\n- **Had Fix**: {p.has_fix} (confidence: {p.fix_confidence})"
        if p.summary:
            section += f"\n- **Summary**: {p.summary[:200]}"
        parts.append(section)

    result = "\n".join(parts)
    if len(result) > max_chars:
        result = result[:max_chars - 20] + "\n\n[...truncated]"
    return result


def save_error_pattern(
    error_class: str,
    transaction: str,
    pattern_description: str,
    confidence: str = "medium",
    knowledge_dir: str | None = None,
) -> Path | None:
    """Save a detected error pattern to the knowledge base patterns directory.

    Used by runner.py to auto-persist high-confidence patterns discovered
    during analysis for future reference.

    Returns path to created doc or None on failure.
    """
    try:
        settings = get_settings()
        kb_dir = Path(knowledge_dir or settings.nightwatch_knowledge_dir)
        patterns_dir = kb_dir / "patterns"
        patterns_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        slug = _slugify(f"{error_class}_{transaction}")
        filename = f"{date_str}_{slug}.md"
        doc_path = patterns_dir / filename

        frontmatter = {
            "title": f"Pattern: {error_class} in {transaction}",
            "error_classes": [error_class],
            "pattern_type": "recurring_error",
            "confidence": confidence,
            "first_detected": date_str,
            "transaction": transaction,
        }

        body = (
            f"# Pattern: {error_class}\n\n"
            f"## Description\n\n{pattern_description}\n\n"
            f"## Transaction\n\n`{transaction}`\n"
        )

        content = _render_frontmatter(frontmatter) + body
        doc_path.write_text(content)
        logger.info(f"  Saved error pattern: {filename}")
        return doc_path
    except Exception as e:
        logger.warning(f"Failed to save error pattern: {e}")
        return None


def update_result_metadata(
    error_class: str,
    transaction: str,
    issue_number: int | None = None,
    pr_number: int | None = None,
    knowledge_dir: str | None = None,
) -> bool:
    """Update a knowledge doc's frontmatter with issue/PR numbers after creation.

    Finds the most recent doc matching error_class + transaction.
    Returns True if a doc was updated, False otherwise.
    """
    settings = get_settings()
    kb_dir = Path(knowledge_dir or settings.nightwatch_knowledge_dir)
    errors_dir = kb_dir / "errors"

    if not errors_dir.exists():
        return False

    # Find matching doc (most recent first)
    matching: list[Path] = []
    for doc_path in errors_dir.glob("*.md"):
        try:
            frontmatter, _ = _parse_frontmatter(doc_path.read_text())
            if (
                frontmatter.get("error_class") == error_class
                and frontmatter.get("transaction") == transaction
            ):
                matching.append(doc_path)
        except (OSError, yaml.YAMLError):
            continue

    if not matching:
        return False

    # Update the most recent one (sort by name, last = most recent date prefix)
    target = sorted(matching)[-1]
    content = target.read_text()
    frontmatter, body = _parse_frontmatter(content)

    if issue_number is not None:
        frontmatter["issue_number"] = issue_number
    if pr_number is not None:
        frontmatter["pr_number"] = pr_number

    target.write_text(_render_frontmatter(frontmatter) + body)
    logger.info(f"  Updated metadata: {target.name}")
    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _match_score(error: ErrorGroup, solution: dict, error_tags: set[str] | None = None) -> float:
    """Score relevance: error_class exact=0.5, transaction exact=0.3, tag overlap=0.1 each."""
    score = 0.0

    if error.error_class == solution.get("error_class", ""):
        score += 0.5

    if error.transaction == solution.get("transaction", ""):
        score += 0.3

    if error_tags is None:
        error_tags = _extract_tags(error)

    solution_tags = set(solution.get("tags", []))
    overlap = error_tags & solution_tags
    score += len(overlap) * 0.1

    return min(score, 1.0)


def _extract_tags(error: ErrorGroup) -> set[str]:
    """Extract searchable tags from error class and transaction name.

    Split on ::, /, #. Lowercase. Filter noise words.
    """
    noise = {"controller", "action", "othertransaction", "rake", "n/a", ""}

    parts: list[str] = []
    # Split error_class on :: and .
    parts.extend(re.split(r"[:./]+", error.error_class))
    # Split transaction on /
    parts.extend(re.split(r"[/]+", error.transaction))

    tags = {p.strip().lower() for p in parts} - noise
    return tags


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split '---\\n...---\\n' YAML from Markdown body. Uses yaml.safe_load."""
    if not content.startswith("---"):
        return {}, content

    # Find the closing ---
    end = content.find("---", 3)
    if end == -1:
        return {}, content

    yaml_str = content[3:end].strip()
    body = content[end + 3:].lstrip("\n")

    try:
        data = yaml.safe_load(yaml_str) or {}
    except yaml.YAMLError:
        return {}, content

    return data, body


def _render_frontmatter(data: dict) -> str:
    """Render dict as '---\\n{yaml}---\\n' block."""
    yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False)
    return f"---\n{yaml_str}---\n\n"


def _slugify(text: str) -> str:
    """Lowercase, replace non-alnum with hyphens, truncate to 60 chars."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60]
