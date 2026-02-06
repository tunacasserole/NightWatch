"""Agent-related type definitions for NightWatch multi-agent architecture."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class AgentType(StrEnum):
    ANALYZER = "analyzer"
    RESEARCHER = "researcher"
    PATTERN_DETECTOR = "pattern_detector"
    REPORTER = "reporter"
    VALIDATOR = "validator"


class AgentStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentConfig:
    """Configuration for a NightWatch agent."""

    name: str
    system_prompt: str = ""
    model: str = "claude-sonnet-4-5-20250929"
    thinking_budget: int = 8000
    max_tokens: int = 16384
    max_iterations: int = 15
    timeout_seconds: int = 300
    retries: int = 1
    enabled: bool = True
    tools: list[str] = field(
        default_factory=lambda: [
            "read_file",
            "search_code",
            "list_directory",
            "get_error_traces",
        ]
    )
    description: str = ""


@dataclass
class AgentResult(Generic[T]):
    """Result of an agent execution."""

    success: bool
    data: T | None = None
    confidence: float = 0.0
    execution_time_ms: float = 0.0
    error_message: str | None = None
    error_code: str | None = None
    recoverable: bool = True
    suggestions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentContext:
    """Runtime context for an agent execution."""

    session_id: str
    run_id: str
    agent_state: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False


def create_agent_context(session_id: str, run_id: str, **kwargs: Any) -> AgentContext:
    """Factory function to create an AgentContext."""
    return AgentContext(session_id=session_id, run_id=run_id, **kwargs)
