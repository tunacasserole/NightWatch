"""Tests for nightwatch.types.agents — agent architecture types."""

from __future__ import annotations

from nightwatch.types.agents import (
    AgentConfig,
    AgentResult,
    AgentStatus,
    AgentType,
    create_agent_context,
)


class TestAgentTypeEnum:
    def test_values(self):
        assert AgentType.ANALYZER == "analyzer"
        assert AgentType.RESEARCHER == "researcher"
        assert AgentType.PATTERN_DETECTOR == "pattern_detector"
        assert AgentType.REPORTER == "reporter"
        assert AgentType.VALIDATOR == "validator"


class TestAgentStatusEnum:
    def test_lifecycle_values(self):
        assert AgentStatus.IDLE == "idle"
        assert AgentStatus.RUNNING == "running"
        assert AgentStatus.COMPLETED == "completed"
        assert AgentStatus.FAILED == "failed"


class TestAgentConfig:
    def test_defaults(self):
        cfg = AgentConfig(name="test-agent")
        assert cfg.name == "test-agent"
        assert cfg.model == "claude-sonnet-4-5-20250929"
        assert cfg.thinking_budget == 8000
        assert cfg.max_tokens == 16384
        assert cfg.enabled is True
        assert "read_file" in cfg.tools

    def test_custom_values(self):
        cfg = AgentConfig(
            name="custom",
            model="claude-haiku",
            thinking_budget=4000,
            enabled=False,
            tools=["search_code"],
        )
        assert cfg.model == "claude-haiku"
        assert cfg.tools == ["search_code"]


class TestAgentResult:
    def test_success_result(self):
        result: AgentResult[str] = AgentResult(success=True, data="analysis done")
        assert result.success is True
        assert result.data == "analysis done"
        assert result.recoverable is True

    def test_failure_result(self):
        result: AgentResult[None] = AgentResult(
            success=False,
            error_message="timeout",
            error_code="TIMEOUT",
            recoverable=True,
        )
        assert result.success is False
        assert result.error_message == "timeout"


class TestAgentContext:
    def test_factory(self):
        ctx = create_agent_context("sess-1", "run-1", dry_run=True)
        assert ctx.session_id == "sess-1"
        assert ctx.run_id == "run-1"
        assert ctx.dry_run is True
        assert ctx.agent_state == {}
