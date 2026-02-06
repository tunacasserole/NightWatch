"""Analysis-related data structures for NightWatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from nightwatch.types.core import ErrorGroup, TraceData

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
    confidence: str  # Confidence enum value
    file_changes: list[FileChange] = []
    suggested_next_steps: list[str] = []


# --- Analysis Data Structures ---


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
