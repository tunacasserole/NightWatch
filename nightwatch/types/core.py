"""Core enums and foundational data structures for NightWatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# --- Enums ---


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PatternType(StrEnum):
    RECURRING_ERROR = "recurring_error"
    SYSTEMIC_ISSUE = "systemic_issue"
    TRANSIENT_NOISE = "transient_noise"


class MatchType(StrEnum):
    CONTAINS = "contains"
    EXACT = "exact"
    PREFIX = "prefix"


# --- Core Data Structures ---


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

    files_examined: dict[str, str] = field(default_factory=dict)  # path -> brief summary
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
