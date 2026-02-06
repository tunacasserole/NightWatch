"""Quality validator -- enforces analysis quality thresholds."""

from __future__ import annotations

from nightwatch.types.validation import (
    LayerResult,
    ValidationIssue,
    ValidationLayer,
    ValidationSeverity,
)


class QualityValidator:
    """Validates analysis quality meets thresholds for PR creation."""

    def __init__(self, min_confidence: str = "medium", max_files: int = 5):
        self.min_confidence = min_confidence.lower()
        self.max_files = max_files
        self._confidence_order = {"low": 0, "medium": 1, "high": 2}

    def validate(self, file_changes, context=None) -> LayerResult:
        issues: list[ValidationIssue] = []

        if not context:
            return LayerResult(layer=ValidationLayer.QUALITY, passed=True, issues=[])

        # Check confidence
        confidence = context.get("confidence", "medium").lower()
        if self._confidence_order.get(confidence, 0) < self._confidence_order.get(
            self.min_confidence, 1
        ):
            issues.append(
                ValidationIssue(
                    layer=ValidationLayer.QUALITY,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Analysis confidence '{confidence}' below minimum '{self.min_confidence}'"
                    ),
                )
            )

        # Check file count
        if len(file_changes) > self.max_files:
            issues.append(
                ValidationIssue(
                    layer=ValidationLayer.QUALITY,
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"File change count ({len(file_changes)})"
                        f" exceeds maximum ({self.max_files})"
                    ),
                )
            )

        # Check root cause present
        root_cause = context.get("root_cause", "")
        if not root_cause or not root_cause.strip():
            issues.append(
                ValidationIssue(
                    layer=ValidationLayer.QUALITY,
                    severity=ValidationSeverity.ERROR,
                    message="Analysis has empty root_cause -- cannot validate fix",
                )
            )

        # Check reasoning present
        reasoning = context.get("reasoning", "")
        if not reasoning or not reasoning.strip():
            issues.append(
                ValidationIssue(
                    layer=ValidationLayer.QUALITY,
                    severity=ValidationSeverity.WARNING,
                    message="Analysis has empty reasoning",
                )
            )

        return LayerResult(
            layer=ValidationLayer.QUALITY,
            passed=not any(i.severity == ValidationSeverity.ERROR for i in issues),
            issues=issues,
        )
