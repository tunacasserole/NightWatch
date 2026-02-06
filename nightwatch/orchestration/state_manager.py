"""Pipeline state management with immutable Pydantic snapshots.

Improvement over Gandalf: frozen Pydantic models instead of deep-clone dance.
State updates create new instances via model_copy(update={}).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from nightwatch.types.orchestration import (
    ExecutionPhase,
    PipelineState,
    create_pipeline_state,
)

logger = logging.getLogger("nightwatch.orchestration.state")


class StateManager:
    """Manages pipeline state per session. Returns immutable snapshots."""

    def __init__(self) -> None:
        self._states: dict[str, PipelineState] = {}

    def initialize_state(self, session_id: str) -> PipelineState:
        """Create and store a fresh pipeline state for a session."""
        state = create_pipeline_state(session_id)
        self._states[session_id] = state
        logger.debug(f"Initialized state for session {session_id}")
        return state

    def get_state(self, session_id: str) -> PipelineState:
        """Retrieve the current state snapshot for a session."""
        if session_id not in self._states:
            raise KeyError(f"No state for session: {session_id}")
        return self._states[session_id]

    def update_state(self, session_id: str, **updates) -> PipelineState:
        """Create a new state with the given updates. Automatically bumps last_updated."""
        current = self.get_state(session_id)
        if "timestamps" not in updates:
            updates["timestamps"] = current.timestamps.model_copy(
                update={"last_updated": datetime.now(UTC)}
            )
        new_state = current.model_copy(update=updates)
        self._states[session_id] = new_state
        return new_state

    def set_phase(self, session_id: str, phase: ExecutionPhase) -> PipelineState:
        """Transition to a new execution phase."""
        return self.update_state(
            session_id,
            current_phase=phase,
            timestamps=self.get_state(session_id).timestamps.model_copy(
                update={
                    "phase_started": datetime.now(UTC),
                    "last_updated": datetime.now(UTC),
                }
            ),
        )

    def increment_iteration(self, session_id: str) -> PipelineState:
        """Bump the iteration counter by one."""
        current = self.get_state(session_id)
        return self.update_state(session_id, iteration_count=current.iteration_count + 1)

    def complete(self, session_id: str) -> PipelineState:
        """Mark the pipeline as complete with a completion timestamp."""
        return self.update_state(
            session_id,
            current_phase=ExecutionPhase.COMPLETE,
            timestamps=self.get_state(session_id).timestamps.model_copy(
                update={
                    "completed": datetime.now(UTC),
                    "last_updated": datetime.now(UTC),
                }
            ),
        )

    def remove_state(self, session_id: str) -> None:
        """Discard state for a session."""
        self._states.pop(session_id, None)
