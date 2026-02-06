"""Semantic validator -- checks file changes relate to analysis root cause."""

from __future__ import annotations

from nightwatch.types.validation import (
    LayerResult,
    ValidationIssue,
    ValidationLayer,
    ValidationSeverity,
)


class SemanticValidator:
    """Validates file changes are semantically consistent with the analysis."""

    def validate(self, file_changes, context=None) -> LayerResult:
        issues: list[ValidationIssue] = []

        # If no context, skip semantic checks
        if not context:
            return LayerResult(layer=ValidationLayer.SEMANTIC, passed=True, issues=[])

        root_cause = context.get("root_cause", "")
        reasoning = context.get("reasoning", "")
        analysis_text = f"{root_cause} {reasoning}".lower()

        # Check if number of changes seems proportional
        if len(file_changes) > 5:
            issues.append(
                ValidationIssue(
                    layer=ValidationLayer.SEMANTIC,
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Large number of file changes"
                        f" ({len(file_changes)}) -- verify all are necessary"
                    ),
                )
            )

        # Check if any modified files relate to the root cause text
        if analysis_text.strip() and file_changes:
            paths = []
            for change in file_changes:
                path = change.path if hasattr(change, "path") else change.get("path", "")
                paths.append(path)

            # Extract directory/module names from paths
            modules = set()
            for path in paths:
                parts = path.replace("\\", "/").split("/")
                for part in parts[:-1]:  # directories only
                    if part:
                        modules.add(part.lower())

            # Check if any module is mentioned in the analysis
            mentioned = any(mod in analysis_text for mod in modules if len(mod) > 2)
            if not mentioned and modules:
                issues.append(
                    ValidationIssue(
                        layer=ValidationLayer.SEMANTIC,
                        severity=ValidationSeverity.WARNING,
                        message="Modified files don't appear related to the root cause analysis",
                        details={
                            "paths": paths,
                            "root_cause_snippet": root_cause[:100],
                        },
                    )
                )

        return LayerResult(
            layer=ValidationLayer.SEMANTIC,
            passed=not any(i.severity == ValidationSeverity.ERROR for i in issues),
            issues=issues,
        )
