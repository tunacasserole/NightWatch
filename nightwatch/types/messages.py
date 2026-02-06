"""Inter-agent message types for NightWatch orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any, Generic, TypeVar

from nightwatch.types.agents import AgentType

T = TypeVar("T")


class MessageType(StrEnum):
    TASK_ASSIGNED = "task_assigned"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    ERRORS_READY = "errors_ready"
    TRACES_READY = "traces_ready"
    ANALYSIS_READY = "analysis_ready"
    PATTERNS_READY = "patterns_ready"
    VALIDATION_COMPLETE = "validation_complete"
    PHASE_COMPLETE = "phase_complete"
    ITERATION_NEEDED = "iteration_needed"


class MessagePriority(IntEnum):
    HIGH = 0
    MEDIUM = 1
    LOW = 2


@dataclass
class AgentMessage(Generic[T]):
    """A message passed between agents."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    from_agent: AgentType | None = None
    to_agent: AgentType | None = None
    type: MessageType = MessageType.TASK_ASSIGNED
    payload: T = None  # type: ignore[assignment]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    priority: MessagePriority = MessagePriority.MEDIUM
    session_id: str = ""


# Classification helpers
_TASK_MESSAGES = frozenset(
    {
        MessageType.TASK_ASSIGNED,
        MessageType.TASK_STARTED,
        MessageType.TASK_COMPLETED,
        MessageType.TASK_FAILED,
    }
)
_DATA_MESSAGES = frozenset(
    {
        MessageType.ERRORS_READY,
        MessageType.TRACES_READY,
        MessageType.ANALYSIS_READY,
        MessageType.PATTERNS_READY,
        MessageType.VALIDATION_COMPLETE,
    }
)
_CONTROL_MESSAGES = frozenset(
    {
        MessageType.PHASE_COMPLETE,
        MessageType.ITERATION_NEEDED,
    }
)


def is_task_message(msg_type: MessageType) -> bool:
    """Check if a message type is a task lifecycle message."""
    return msg_type in _TASK_MESSAGES


def is_data_message(msg_type: MessageType) -> bool:
    """Check if a message type is a data-ready message."""
    return msg_type in _DATA_MESSAGES


def is_control_message(msg_type: MessageType) -> bool:
    """Check if a message type is a control/flow message."""
    return msg_type in _CONTROL_MESSAGES


def create_message(
    msg_type: MessageType,
    payload: Any = None,
    from_agent: AgentType | None = None,
    to_agent: AgentType | None = None,
    session_id: str = "",
    priority: MessagePriority = MessagePriority.MEDIUM,
) -> AgentMessage:
    """Factory function to create an AgentMessage."""
    return AgentMessage(
        from_agent=from_agent,
        to_agent=to_agent,
        type=msg_type,
        payload=payload,
        session_id=session_id,
        priority=priority,
    )
