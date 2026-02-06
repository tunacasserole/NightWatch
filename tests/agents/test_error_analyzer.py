"""Tests for AnalyzerAgent wrapper and confidence mapping."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nightwatch.agents.error_analyzer import AnalyzerAgent, _confidence_to_float
from nightwatch.agents.registry import clear_registry, list_registered
from nightwatch.types.agents import AgentContext, AgentType


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    # Re-register by re-applying the decorator (class already exists).
    from nightwatch.agents.registry import register_agent

    register_agent(AgentType.ANALYZER)(AnalyzerAgent)
    yield
    clear_registry()


def _make_context(**state_overrides) -> AgentContext:
    return AgentContext(
        session_id="s-1",
        run_id="r-1",
        agent_state=state_overrides,
    )


class TestAnalyzerAgentRegistered:
    def test_registered(self):
        reg = list_registered()
        assert AgentType.ANALYZER in reg
        assert reg[AgentType.ANALYZER] is AnalyzerAgent


class TestAnalyzerAgentExecute:
    def test_success(self):
        async def _test():
            fake_result = SimpleNamespace(
                analysis=SimpleNamespace(confidence="high"),
            )
            agent = AnalyzerAgent()

            ctx = _make_context(
                error={"id": "1"},
                traces=[],
                github_client=object(),
                newrelic_client=object(),
            )

            with patch(
                "nightwatch.analyzer.analyze_error",
                return_value=fake_result,
            ) as mock_fn:
                result = await agent.execute(ctx)

            assert result.success is True
            assert result.data is fake_result
            assert result.confidence == pytest.approx(0.9)
            mock_fn.assert_called_once()

        asyncio.run(_test())

    def test_missing_state_key(self):
        """Missing required keys should produce a failure result."""

        async def _test():
            agent = AnalyzerAgent()
            ctx = _make_context()  # empty state - no "error" key
            result = await agent.execute(ctx)

            assert result.success is False
            assert result.error_code == "EXECUTION_ERROR"

        asyncio.run(_test())


class TestConfidenceMapping:
    @pytest.mark.parametrize(
        ("input_val", "expected"),
        [
            ("high", 0.9),
            ("High", 0.9),
            ("medium", 0.6),
            ("low", 0.3),
            ("unknown", 0.5),
            ("", 0.5),
        ],
    )
    def test_mapping(self, input_val: str, expected: float):
        assert _confidence_to_float(input_val) == pytest.approx(expected)
