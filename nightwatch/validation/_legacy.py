"""Validation of proposed file changes before PR creation.

Implements the Ralph quality gate pattern: validate before committing.
Checks file existence, content validity, and basic Ruby syntax.
"""

from __future__ import annotations

import logging
from typing import Any

from nightwatch.models import Analysis, FileValidationResult

logger = logging.getLogger("nightwatch.validation")


def validate_file_changes(
    analysis: Analysis,
    github_client: Any,
) -> FileValidationResult:
    """Validate proposed file changes before creating a PR.

    Checks:
    1. Path safety (no absolute paths, no '..' traversal)
    2. Content non-empty for create/modify actions
    3. File exists for 'modify' action (via github_client.read_file)
    4. File doesn't already exist for 'create' action (warning, not error)
    5. Basic Ruby syntax for .rb files

    Args:
        analysis: The analysis containing proposed file_changes.
        github_client: GitHubClient instance for file existence checks.

    Returns:
        FileValidationResult with is_valid, errors, and warnings.
    """
    if not analysis.file_changes:
        return FileValidationResult(is_valid=True)

    errors: list[str] = []
    warnings: list[str] = []

    for change in analysis.file_changes:
        _validate_single_change(change, github_client, errors, warnings)

    is_valid = len(errors) == 0

    if is_valid:
        logger.info(f"  Quality gate passed ({len(analysis.file_changes)} files)")
    else:
        logger.warning(f"  Quality gate FAILED: {len(errors)} errors")
        for err in errors:
            logger.warning(f"    ✗ {err}")

    if warnings:
        for warn in warnings:
            logger.info(f"    ⚠ {warn}")

    return FileValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)


def _validate_single_change(
    change: Any,
    github_client: Any,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validate a single file change."""
    # Path safety
    if change.path.startswith("/") or ".." in change.path:
        errors.append(f"Unsafe path: {change.path}")
        return

    if change.action in ("modify", "create"):
        # Content required
        if not change.content or not change.content.strip():
            errors.append(f"Empty content for {change.action} on {change.path}")
            return

        # Very short content is suspicious
        if len(change.content.strip()) < 10:
            warnings.append(f"Very short content ({len(change.content)} chars) for {change.path}")

    if change.action == "modify":
        # File must exist
        existing = github_client.read_file(change.path)
        if existing is None:
            errors.append(f"File does not exist for modify: {change.path}")

    elif change.action == "create":
        # File should not exist (warning, not error — overwrite is sometimes intentional)
        existing = github_client.read_file(change.path)
        if existing is not None:
            warnings.append(
                f"File already exists for create action: {change.path} (will overwrite)"
            )

    # Basic Ruby syntax check for .rb files
    if change.path.endswith(".rb") and change.content:
        syntax_issues = _check_ruby_syntax(change.content)
        for issue in syntax_issues:
            errors.append(f"{change.path}: {issue}")


def _check_ruby_syntax(content: str) -> list[str]:
    """Basic Ruby syntax checks (not a full parser, just balance checks).

    Checks for obviously imbalanced def/end, class/end, module/end blocks.
    Intentionally tolerant — threshold of abs(openers - enders) > 2.
    """
    issues: list[str] = []

    openers = 0
    enders = 0

    for line in content.split("\n"):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith("#"):
            continue

        # Count openers (check start of line to avoid false positives)
        for keyword in ("def ", "class ", "module ", "do", "if ", "unless ", "begin"):
            if stripped.startswith(keyword) or f" {keyword}" in stripped:
                openers += 1
                break  # Count each line once

        # Count end keywords
        if stripped == "end" or stripped.startswith("end ") or stripped.startswith("end#"):
            enders += 1

    if openers > 0 and enders == 0:
        issues.append("Ruby syntax: no 'end' keywords found (likely incomplete)")
    elif abs(openers - enders) > 2:
        issues.append(f"Ruby syntax: imbalanced blocks ({openers} openers vs {enders} ends)")

    return issues
