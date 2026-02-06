"""Path safety validator -- prevents path traversal and absolute paths."""

from __future__ import annotations

from nightwatch.types.validation import (
    LayerResult,
    ValidationIssue,
    ValidationLayer,
    ValidationSeverity,
)


class PathSafetyValidator:
    """Validates file paths are safe for PR creation."""

    def validate(self, file_changes, context=None) -> LayerResult:
        issues = []
        for change in file_changes:
            path = change.path if hasattr(change, "path") else change.get("path", "")
            if path.startswith("/"):
                issues.append(
                    ValidationIssue(
                        layer=ValidationLayer.PATH_SAFETY,
                        severity=ValidationSeverity.ERROR,
                        message=f"Absolute path not allowed: {path}",
                        file_path=path,
                    )
                )
            if ".." in path:
                issues.append(
                    ValidationIssue(
                        layer=ValidationLayer.PATH_SAFETY,
                        severity=ValidationSeverity.ERROR,
                        message=f"Path traversal not allowed: {path}",
                        file_path=path,
                    )
                )
        return LayerResult(
            layer=ValidationLayer.PATH_SAFETY,
            passed=not any(i.severity == ValidationSeverity.ERROR for i in issues),
            issues=issues,
        )
