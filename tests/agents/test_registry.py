"""Tests for the agent registry (decorator, factory, listing)."""

from __future__ import annotations

import logging

import pytest

from nightwatch.agents.base import BaseAgent
from nightwatch.agents.registry import (
    clear_registry,
    create_agent,
    get_agent_class,
    list_registered,
    register_agent,
)
from nightwatch.types.agents import AgentContext, AgentResult, AgentType


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure each test starts and ends with an empty registry."""
    clear_registry()
    yield
    clear_registry()


def _make_agent_cls(agent_type: AgentType, name: str = "TestAgent"):
    """Build a one-off concrete agent class."""

    @register_agent(agent_type)
    class _Agent(BaseAgent):
        async def execute(self, context: AgentContext) -> AgentResult:
            return AgentResult(success=True)

    _Agent.__name__ = name
    _Agent.__qualname__ = name
    return _Agent


class TestRegisterAgentDecorator:
    def test_register_agent(self):
        cls = _make_agent_cls(AgentType.ANALYZER, "MyAnalyzer")
        assert cls.agent_type == AgentType.ANALYZER
        assert get_agent_class(AgentType.ANALYZER) is cls

    def test_overwrite_warning(self, caplog):
        _make_agent_cls(AgentType.RESEARCHER, "First")
        with caplog.at_level(logging.WARNING, logger="nightwatch.agents"):
            _make_agent_cls(AgentType.RESEARCHER, "Second")
        assert "Overwriting" in caplog.text


class TestGetAgentClass:
    def test_found(self):
        cls = _make_agent_cls(AgentType.VALIDATOR)
        assert get_agent_class(AgentType.VALIDATOR) is cls

    def test_not_found(self):
        with pytest.raises(KeyError, match="No agent registered"):
            get_agent_class(AgentType.REPORTER)


class TestCreateAgent:
    def test_factory(self):
        _make_agent_cls(AgentType.PATTERN_DETECTOR, "PD")
        agent = create_agent(AgentType.PATTERN_DETECTOR)
        assert isinstance(agent, BaseAgent)
        assert agent.agent_type == AgentType.PATTERN_DETECTOR


class TestListRegistered:
    def test_empty(self):
        assert list_registered() == {}

    def test_populated(self):
        _make_agent_cls(AgentType.ANALYZER)
        _make_agent_cls(AgentType.REPORTER)
        reg = list_registered()
        assert AgentType.ANALYZER in reg
        assert AgentType.REPORTER in reg
        assert len(reg) == 2


class TestClearRegistry:
    def test_clear(self):
        _make_agent_cls(AgentType.ANALYZER)
        assert len(list_registered()) == 1
        clear_registry()
        assert len(list_registered()) == 0
