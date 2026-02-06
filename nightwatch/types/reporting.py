"""Reporting and output types for NightWatch run results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from nightwatch.types.analysis import Analysis, ErrorAnalysisResult
from nightwatch.types.core import Confidence, ErrorGroup
from nightwatch.types.patterns import DetectedPattern, IgnoreSuggestion


@dataclass
class CreatedIssueResult:
    """Result of creating (or updating) a GitHub issue."""

    error: ErrorGroup
    analysis: Analysis
    action: Literal["created", "commented"]  # New issue or occurrence comment
    issue_number: int
    issue_url: str = ""


@dataclass
class CreatedPRResult:
    """Result of creating a draft PR."""

    issue_number: int
    pr_number: int
    pr_url: str
    branch_name: str
    files_changed: int


@dataclass
class RunReport:
    """Summary of an entire NightWatch run."""

    timestamp: str
    lookback: str
    total_errors_found: int
    errors_filtered: int
    errors_analyzed: int
    analyses: list[ErrorAnalysisResult]
    issues_created: list[CreatedIssueResult] = field(default_factory=list)
    pr_created: CreatedPRResult | None = None
    total_tokens_used: int = 0
    total_api_calls: int = 0
    run_duration_seconds: float = 0.0
    multi_pass_retries: int = 0  # Count of analyses that needed a second pass
    pr_validation_failures: int = 0  # Count of PR validations that failed
    patterns: list[DetectedPattern] = field(default_factory=list)
    ignore_suggestions: list[IgnoreSuggestion] = field(default_factory=list)

    @property
    def fixes_found(self) -> int:
        return sum(1 for a in self.analyses if a.analysis.has_fix)

    @property
    def high_confidence(self) -> int:
        return sum(
            1
            for a in self.analyses
            if a.analysis.has_fix and a.analysis.confidence == Confidence.HIGH
        )
