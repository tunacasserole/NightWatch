"""Pattern detection and knowledge types for NightWatch."""

from __future__ import annotations

from dataclasses import dataclass

from nightwatch.types.core import MatchType, PatternType


@dataclass
class DetectedPattern:
    """A systemic pattern detected across multiple errors."""

    title: str
    description: str
    error_classes: list[str]
    modules: list[str]
    occurrences: int
    suggestion: str
    pattern_type: PatternType  # was str, now typed


@dataclass
class IgnoreSuggestion:
    """A suggested addition to ignore.yml."""

    pattern: str
    match: MatchType  # was str, now typed
    reason: str
    evidence: str


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
