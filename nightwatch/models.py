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
class RunContext:
    """Accumulated codebase knowledge across error analyses in a single run.

    Inspired by Ralph's progress.txt — append-only, read-first pattern.
    Tracks files examined and patterns discovered so later analyses
    benefit from earlier discoveries.
    """

    files_examined: dict[str, str] = field(default_factory=dict)  # path → brief summary
    patterns_discovered: list[str] = field(default_factory=list)
    errors_analyzed: list[str] = field(default_factory=list)  # "ErrorClass in tx — cause"

    def to_prompt_section(self, max_chars: int = 1500) -> str:
        """Format accumulated context as a prompt section, capped at max_chars."""
        if not self.files_examined and not self.patterns_discovered and not self.errors_analyzed:
            return ""

        parts: list[str] = ["## Codebase Context from Previous Analyses"]

        if self.errors_analyzed:
            parts.append("\n### Errors Already Analyzed")
            for entry in self.errors_analyzed[-5:]:
                parts.append(f"- {entry}")

        if self.patterns_discovered:
            parts.append("\n### Codebase Patterns Discovered")
            for pattern in self.patterns_discovered[-5:]:
                parts.append(f"- {pattern}")

        if self.files_examined:
            parts.append("\n### Key Files Examined")
            items = list(self.files_examined.items())[-10:]
            for path, summary in items:
                parts.append(f"- `{path}`: {summary}")

        result = "\n".join(parts)

        if len(result) > max_chars:
            result = result[: max_chars - 20] + "\n\n[...truncated]"

        return result

    def record_analysis(self, error_class: str, transaction: str, summary: str) -> None:
        """Record a completed analysis for future context."""
        entry = f"{error_class} in {transaction}"
        if summary:
            entry += f" — {summary[:100]}"
        self.errors_analyzed.append(entry)

    def record_file(self, path: str, summary: str) -> None:
        """Record a file that was examined."""
        self.files_examined[path] = summary[:80]


@dataclass
class FileValidationResult:
    """Result of validating proposed file changes before PR creation."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class TokenBreakdown:
    """Detailed token usage breakdown for an analysis."""

    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    tool_result_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cache_savings(self) -> int:
        """Tokens saved by cache hits (approximate)."""
        return self.cache_read_tokens

    def to_dict(self) -> dict:
        return {
            "input": self.input_tokens,
            "output": self.output_tokens,
            "thinking": self.thinking_tokens,
            "cache_read": self.cache_read_tokens,
            "cache_write": self.cache_write_tokens,
            "tool_results": self.tool_result_tokens,
            "total": self.total,
            "cache_savings": self.cache_savings,
        }


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
    pass_count: int = 1  # How many analysis passes were run
    context_files_contributed: int = 0  # Files added to RunContext from this analysis
    quality_score: float = 0.0  # Quality gate score (0.0-1.0)
    token_breakdown: TokenBreakdown | None = None  # Detailed token usage


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
class PriorAnalysis:
    """A prior analysis retrieved from the knowledge base."""

    error_class: str
    transaction: str
    root_cause: str
    fix_confidence: str
    has_fix: bool
    summary: str
    match_score: float
    source_file: str
    first_detected: str


@dataclass
class DetectedPattern:
    """A systemic pattern detected across multiple errors."""

    title: str
    description: str
    error_classes: list[str]
    modules: list[str]
    occurrences: int
    suggestion: str
    pattern_type: str  # "recurring_error" | "systemic_issue" | "transient_noise"


@dataclass
class IgnoreSuggestion:
    """A suggested addition to ignore.yml."""

    pattern: str
    match: str  # "contains" | "exact" | "prefix"
    reason: str
    evidence: str


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
