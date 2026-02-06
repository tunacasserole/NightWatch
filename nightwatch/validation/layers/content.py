"""Content validator -- checks file change content is present and reasonable."""

from __future__ import annotations

from nightwatch.types.validation import (
    LayerResult,
    ValidationIssue,
    ValidationLayer,
    ValidationSeverity,
)


class ContentValidator:
    """Validates file change content is present and reasonable."""

    def validate(self, file_changes, context=None) -> LayerResult:
        issues = []
        for change in file_changes:
            action = change.action if hasattr(change, "action") else change.get("action")
            content = change.content if hasattr(change, "content") else change.get("content")
            path = change.path if hasattr(change, "path") else change.get("path", "")

            if action in ("modify", "create") and not (content and content.strip()):
                issues.append(
                    ValidationIssue(
                        layer=ValidationLayer.CONTENT,
                        severity=ValidationSeverity.ERROR,
                        message=f"Empty content for {action} action: {path}",
                        file_path=path,
                    )
                )
            if content and len(content.strip()) < 20 and action == "modify":
                issues.append(
                    ValidationIssue(
                        layer=ValidationLayer.CONTENT,
                        severity=ValidationSeverity.WARNING,
                        message=(
                            f"Suspiciously short content ({len(content.strip())} chars): {path}"
                        ),
                        file_path=path,
                    )
                )
        return LayerResult(
            layer=ValidationLayer.CONTENT,
            passed=not any(i.severity == ValidationSeverity.ERROR for i in issues),
            issues=issues,
        )
