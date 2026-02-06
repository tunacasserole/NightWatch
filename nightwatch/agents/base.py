"""BaseAgent — abstract base class for NightWatch agents.

Provides lifecycle management, timeout handling, and message bus integration.
All concrete agents extend this class and implement ``execute()``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any

from nightwatch.types.agents import (
    AgentConfig,
    AgentContext,
    AgentResult,
    AgentStatus,
    AgentType,
)
from nightwatch.types.messages import AgentMessage, MessageType, create_message

logger = logging.getLogger("nightwatch.agents")


class BaseAgent(ABC):
    """Abstract base for all NightWatch agents.

    Subclasses must:
    - Set ``agent_type`` as a class variable (or let the registry decorator set it).
    - Implement ``execute(context) -> AgentResult``.
    """

    agent_type: AgentType  # Set by subclass or @register_agent

    def __init__(self, config: AgentConfig | None = None) -> None:
        if config is None:
            config = AgentConfig(name=self.__class__.__name__)
        self._config = config
        self._status: AgentStatus = AgentStatus.IDLE
        self._message_bus: Any | None = None  # Will be a MessageBus in Phase 3

    # -- Properties -----------------------------------------------------------

    @property
    def name(self) -> str:
        """Agent display name (from config)."""
        return self._config.name

    @property
    def status(self) -> AgentStatus:
        """Current agent status."""
        return self._status

    @property
    def config(self) -> AgentConfig:
        """Agent configuration."""
        return self._config

    # -- Lifecycle ------------------------------------------------------------

    def initialize(self, message_bus: Any | None = None) -> None:
        """Prepare the agent for execution.

        Parameters
        ----------
        message_bus:
            Optional message bus for inter-agent communication.
        """
        self._message_bus = message_bus
        self._status = AgentStatus.IDLE
        logger.debug("Agent %s initialized", self.name)

    @abstractmethod
    async def execute(self, context: AgentContext) -> AgentResult:
        """Run the agent's main logic.

        Must be implemented by every concrete agent.
        """
        ...  # pragma: no cover

    def cleanup(self) -> None:
        """Release resources and reset state after execution."""
        self._message_bus = None
        self._status = AgentStatus.IDLE
        logger.debug("Agent %s cleaned up", self.name)

    # -- Execution helpers ----------------------------------------------------

    async def execute_with_timeout(
        self,
        context: AgentContext,
        operation: Callable[[], Coroutine[Any, Any, AgentResult]],
    ) -> AgentResult:
        """Run *operation* with the configured timeout.

        Handles timing, status transitions, and error wrapping.

        Returns
        -------
        AgentResult
            On success the result produced by *operation*; on timeout or
            exception a failure result with appropriate error information.
        """
        self._status = AgentStatus.RUNNING
        start = time.monotonic()
        timeout = self._config.timeout_seconds

        try:
            result: AgentResult = await asyncio.wait_for(
                operation(),
                timeout=timeout,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            result.execution_time_ms = elapsed_ms
            self._status = AgentStatus.COMPLETED
            return result

        except TimeoutError:
            elapsed_ms = (time.monotonic() - start) * 1000
            self._status = AgentStatus.FAILED
            logger.warning(
                "Agent %s timed out after %.0fms (limit=%ds)",
                self.name,
                elapsed_ms,
                timeout,
            )
            return AgentResult(
                success=False,
                error_message=f"Agent {self.name} timed out after {timeout}s",
                error_code="TIMEOUT",
                execution_time_ms=elapsed_ms,
                recoverable=True,
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            self._status = AgentStatus.FAILED
            logger.exception("Agent %s failed: %s", self.name, exc)
            return AgentResult(
                success=False,
                error_message=str(exc),
                error_code="EXECUTION_ERROR",
                execution_time_ms=elapsed_ms,
                recoverable=True,
            )

    # -- Messaging ------------------------------------------------------------

    def send_message(
        self,
        msg_type: MessageType,
        payload: Any = None,
        to_agent: AgentType | None = None,
    ) -> None:
        """Publish a message to the bus (no-op when bus is absent)."""
        if self._message_bus is None:
            logger.debug(
                "Agent %s: no message bus, dropping %s message",
                self.name,
                msg_type,
            )
            return
        msg: AgentMessage = create_message(
            msg_type=msg_type,
            payload=payload,
            from_agent=self.agent_type,
            to_agent=to_agent,
        )
        self._message_bus.publish(msg)
