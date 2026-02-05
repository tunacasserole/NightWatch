"""Pydantic models for NightWatch data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

# --- Enums ---


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# --- Claude Structured Output Models ---


class FileChange(BaseModel):
    """A proposed file change from Claude's analysis."""

    path: str
    action: Literal["modify", "create", "delete"]
    content: str | None = None
    description: str = ""


class Analysis(BaseModel):
    """Claude's structured analysis of a production error."""

    title: str
    reasoning: str
    root_cause: str
    has_fix: bool
    confidence: Confidence
    file_changes: list[FileChange] = []
    suggested_next_steps: list[str] = []


# --- Internal Data Models ---


@dataclass
class ErrorGroup:
    """A group of identical errors from New Relic, aggregated by class + transaction."""

    error_class: str
    transaction: str
    message: str
    occurrences: int
    last_seen: str
    http_path: str = ""
    entity_guid: str | None = None
    host: str = ""
    score: float = 0.0


@dataclass
class TraceData:
    """Detailed trace data for an error group."""

    transaction_errors: list[dict] = field(default_factory=list)
    error_traces: list[dict] = field(default_factory=list)


@dataclass
class ErrorAnalysisResult:
    """Result of analyzing a single error: the error + Claude's analysis."""

    error: ErrorGroup
    analysis: Analysis
    traces: TraceData
    iterations: int = 0
    tokens_used: int = 0
    api_calls: int = 0
    issue_score: float = 0.0  # Set during issue selection


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
class CorrelatedPR:
    """A recently merged PR that may correlate to an error."""

    number: int
    title: str
    url: str
    merged_at: str
    changed_files: list[str]
    overlap_score: float = 0.0


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
