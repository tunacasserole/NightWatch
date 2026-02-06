"""Multi-layer validation types for NightWatch content safety."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationLayer(StrEnum):
    PATH_SAFETY = "path_safety"
    CONTENT = "content"
    SYNTAX = "syntax"
    SEMANTIC = "semantic"
    QUALITY = "quality"


@dataclass
class ValidationIssue:
    """A single validation issue found during content checking."""

    layer: ValidationLayer
    severity: ValidationSeverity
    message: str
    file_path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class LayerResult:
    """Result of running a single validation layer."""

    layer: ValidationLayer
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Aggregate result from all validation layers."""

    valid: bool
    layers: list[LayerResult] = field(default_factory=list)
    blocking_errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)


class IValidator(Protocol):
    """Protocol for validation layer implementations."""

    def validate(
        self, file_changes: list[Any], context: dict[str, Any] | None = None
    ) -> LayerResult: ...
