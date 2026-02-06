"""Syntax validator -- basic language syntax checks."""

from __future__ import annotations

from nightwatch.types.validation import (
    LayerResult,
    ValidationIssue,
    ValidationLayer,
    ValidationSeverity,
)


class SyntaxValidator:
    """Validates basic syntax for known languages (currently Ruby)."""

    def validate(self, file_changes, context=None) -> LayerResult:
        issues = []
        for change in file_changes:
            path = change.path if hasattr(change, "path") else change.get("path", "")
            content = change.content if hasattr(change, "content") else change.get("content")

            if path.endswith(".rb") and content:
                ruby_issues = self._check_ruby_syntax(content, path)
                issues.extend(ruby_issues)

        return LayerResult(
            layer=ValidationLayer.SYNTAX,
            passed=not any(i.severity == ValidationSeverity.ERROR for i in issues),
            issues=issues,
        )

    def _check_ruby_syntax(self, content: str, path: str) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        openers = 0
        enders = 0
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for keyword in (
                "def ",
                "class ",
                "module ",
                "do",
                "if ",
                "unless ",
                "begin",
            ):
                if stripped.startswith(keyword) or f" {keyword}" in stripped:
                    openers += 1
                    break
            if stripped == "end" or stripped.startswith("end ") or stripped.startswith("end#"):
                enders += 1

        if openers > 0 and enders == 0:
            issues.append(
                ValidationIssue(
                    layer=ValidationLayer.SYNTAX,
                    severity=ValidationSeverity.ERROR,
                    message="Ruby syntax: no 'end' keywords found (likely incomplete)",
                    file_path=path,
                )
            )
        elif abs(openers - enders) > 2:
            issues.append(
                ValidationIssue(
                    layer=ValidationLayer.SYNTAX,
                    severity=ValidationSeverity.ERROR,
                    message=f"Ruby syntax: imbalanced blocks ({openers} openers vs {enders} ends)",
                    file_path=path,
                )
            )
        return issues
