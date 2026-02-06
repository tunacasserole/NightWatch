"""Pipeline orchestration types for NightWatch multi-phase execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from nightwatch.types.agents import AgentResult, AgentType


class ExecutionPhase(StrEnum):
    INGESTION = "ingestion"
    ENRICHMENT = "enrichment"
    ANALYSIS = "analysis"
    SYNTHESIS = "synthesis"
    REPORTING = "reporting"
    ACTION = "action"
    LEARNING = "learning"
    COMPLETE = "complete"


class PipelineTimestamps(BaseModel, frozen=True):
    """Immutable timestamp record for pipeline execution."""

    started: datetime
    phase_started: datetime | None = None
    last_updated: datetime | None = None
    completed: datetime | None = None


class PipelineState(BaseModel, frozen=True):
    """Immutable snapshot of pipeline execution state."""

    session_id: str
    current_phase: ExecutionPhase = ExecutionPhase.INGESTION
    iteration_count: int = 0
    agent_results: dict[str, Any] = Field(default_factory=dict)
    timestamps: PipelineTimestamps = Field(
        default_factory=lambda: PipelineTimestamps(started=datetime.now(UTC))
    )
    errors_data: list[Any] = Field(default_factory=list)
    analyses_data: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass
class PhaseResult:
    """Result of executing a single pipeline phase."""

    phase: ExecutionPhase
    success: bool
    agent_results: dict[AgentType, AgentResult] = field(default_factory=dict)
    execution_time_ms: float = 0.0
    error_message: str | None = None


@dataclass
class PipelineConfig:
    """Configuration for the orchestration pipeline."""

    max_iterations: int = 2
    phase_timeouts: dict[ExecutionPhase, int] = field(
        default_factory=lambda: {
            ExecutionPhase.INGESTION: 60,
            ExecutionPhase.ENRICHMENT: 120,
            ExecutionPhase.ANALYSIS: 300,
            ExecutionPhase.SYNTHESIS: 60,
            ExecutionPhase.REPORTING: 60,
            ExecutionPhase.ACTION: 120,
            ExecutionPhase.LEARNING: 60,
        }
    )
    enable_fallback: bool = True
    dry_run: bool = False


def create_pipeline_state(session_id: str) -> PipelineState:
    """Factory function to create a fresh PipelineState with current timestamps."""
    return PipelineState(
        session_id=session_id,
        timestamps=PipelineTimestamps(started=datetime.now(UTC)),
    )
