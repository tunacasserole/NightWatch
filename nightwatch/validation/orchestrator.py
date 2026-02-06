"""Validation orchestrator -- runs layers in sequence with short-circuit."""

from __future__ import annotations

from nightwatch.types.validation import (
    LayerResult,
    ValidationIssue,
    ValidationLayer,
    ValidationResult,
    ValidationSeverity,
)
from nightwatch.validation.layers.content import ContentValidator
from nightwatch.validation.layers.path_safety import PathSafetyValidator
from nightwatch.validation.layers.quality import QualityValidator
from nightwatch.validation.layers.semantic import SemanticValidator
from nightwatch.validation.layers.syntax import SyntaxValidator


class ValidationOrchestrator:
    """Runs validation layers in sequence.

    Default layer order:
    1. PathSafety -- reject dangerous paths immediately (short-circuits on failure)
    2. Content -- verify file content is present and reasonable
    3. Syntax -- basic language syntax checks
    4. Semantic -- check changes relate to root cause
    5. Quality -- enforce analysis quality thresholds
    """

    def __init__(self, layers=None):
        self.layers = layers or [
            PathSafetyValidator(),
            ContentValidator(),
            SyntaxValidator(),
            SemanticValidator(),
            QualityValidator(),
        ]

    def validate(self, file_changes, context=None) -> ValidationResult:
        all_layers: list[LayerResult] = []
        blocking: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []

        for validator in self.layers:
            result = validator.validate(file_changes, context)
            all_layers.append(result)

            for issue in result.issues:
                if issue.severity == ValidationSeverity.ERROR:
                    blocking.append(issue)
                elif issue.severity == ValidationSeverity.WARNING:
                    warnings.append(issue)

            # Short-circuit on PATH_SAFETY failure
            if result.layer == ValidationLayer.PATH_SAFETY and not result.passed:
                break

        return ValidationResult(
            valid=len(blocking) == 0,
            layers=all_layers,
            blocking_errors=blocking,
            warnings=warnings,
        )
