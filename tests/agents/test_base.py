"""Tests for BaseAgent lifecycle and execution helpers."""

from __future__ import annotations

import asyncio

import pytest

from nightwatch.agents.base import BaseAgent
from nightwatch.types.agents import (
    AgentConfig,
    AgentContext,
    AgentResult,
    AgentStatus,
    AgentType,
)

# -- Concrete test double -----------------------------------------------------


class DummyAgent(BaseAgent):
    """Minimal concrete subclass used by all tests in this module."""

    agent_type = AgentType.ANALYZER

    async def execute(self, context: AgentContext) -> AgentResult:
        return await self.execute_with_timeout(context, self._do_work)

    async def _do_work(self) -> AgentResult:
        return AgentResult(success=True, data="test")


def _make_context(**overrides) -> AgentContext:
    defaults: dict = {"session_id": "sess-1", "run_id": "run-1"}
    defaults.update(overrides)
    return AgentContext(**defaults)


# -- Tests --------------------------------------------------------------------


class TestBaseAgentAbstract:
    def test_base_agent_is_abstract(self):
        """Cannot instantiate BaseAgent directly; concrete subclass works."""
        with pytest.raises(TypeError):
            BaseAgent()  # type: ignore[abstract]

        agent = DummyAgent()
        assert isinstance(agent, BaseAgent)

    def test_agent_default_config(self):
        """When no config is given, auto-generates one from the class name."""
        agent = DummyAgent()
        assert agent.name == "DummyAgent"

    def test_agent_custom_config(self):
        cfg = AgentConfig(name="custom-analyzer", timeout_seconds=60)
        agent = DummyAgent(config=cfg)
        assert agent.name == "custom-analyzer"
        assert agent.config.timeout_seconds == 60


class TestAgentLifecycle:
    def test_initialize_sets_idle(self):
        agent = DummyAgent()
        agent.initialize()
        assert agent.status == AgentStatus.IDLE

    def test_cleanup_resets_state(self):
        agent = DummyAgent()
        agent.initialize()
        # Simulate post-execute state
        agent._status = AgentStatus.COMPLETED
        agent.cleanup()
        assert agent.status == AgentStatus.IDLE


class TestExecuteWithTimeout:
    def test_success(self):
        async def _test():
            agent = DummyAgent()
            ctx = _make_context()
            result = await agent.execute(ctx)

            assert result.success is True
            assert result.data == "test"
            assert result.execution_time_ms > 0
            assert agent.status == AgentStatus.COMPLETED

        asyncio.run(_test())

    def test_timeout(self):
        async def _test():
            agent = DummyAgent(config=AgentConfig(name="slow", timeout_seconds=0.01))
            ctx = _make_context()

            async def _slow() -> AgentResult:
                await asyncio.sleep(5)
                return AgentResult(success=True)  # pragma: no cover

            result = await agent.execute_with_timeout(ctx, _slow)

            assert result.success is False
            assert result.error_code == "TIMEOUT"
            assert agent.status == AgentStatus.FAILED

        asyncio.run(_test())

    def test_exception(self):
        async def _test():
            agent = DummyAgent()
            ctx = _make_context()

            async def _boom() -> AgentResult:
                raise RuntimeError("kaboom")

            result = await agent.execute_with_timeout(ctx, _boom)

            assert result.success is False
            assert result.error_code == "EXECUTION_ERROR"
            assert "kaboom" in (result.error_message or "")
            assert agent.status == AgentStatus.FAILED

        asyncio.run(_test())

    def test_status_transitions(self):
        """Status should move IDLE -> RUNNING -> COMPLETED on success."""

        async def _test():
            agent = DummyAgent()
            assert agent.status == AgentStatus.IDLE

            observed: list[AgentStatus] = []

            async def _observe() -> AgentResult:
                observed.append(agent.status)
                return AgentResult(success=True, data="ok")

            ctx = _make_context()
            result = await agent.execute_with_timeout(ctx, _observe)

            assert result.success is True
            assert observed == [AgentStatus.RUNNING]
            assert agent.status == AgentStatus.COMPLETED

        asyncio.run(_test())


class TestSendMessage:
    def test_send_message_without_bus_no_error(self):
        """Sending a message when no bus is set should silently no-op."""
        from nightwatch.types.messages import MessageType

        agent = DummyAgent()
        # Should not raise
        agent.send_message(MessageType.TASK_COMPLETED, payload={"key": "val"})
