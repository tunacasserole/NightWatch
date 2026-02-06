"""Tests for nightwatch.types.messages — inter-agent messaging."""

from __future__ import annotations

from nightwatch.types.agents import AgentType
from nightwatch.types.messages import (
    AgentMessage,
    MessagePriority,
    MessageType,
    create_message,
    is_control_message,
    is_data_message,
    is_task_message,
)


class TestMessageClassification:
    def test_task_messages(self):
        assert is_task_message(MessageType.TASK_ASSIGNED) is True
        assert is_task_message(MessageType.TASK_COMPLETED) is True
        assert is_task_message(MessageType.ERRORS_READY) is False

    def test_data_messages(self):
        assert is_data_message(MessageType.ERRORS_READY) is True
        assert is_data_message(MessageType.ANALYSIS_READY) is True
        assert is_data_message(MessageType.TASK_ASSIGNED) is False

    def test_control_messages(self):
        assert is_control_message(MessageType.PHASE_COMPLETE) is True
        assert is_control_message(MessageType.ITERATION_NEEDED) is True
        assert is_control_message(MessageType.TASK_ASSIGNED) is False


class TestMessagePriority:
    def test_ordering(self):
        assert MessagePriority.HIGH < MessagePriority.MEDIUM
        assert MessagePriority.MEDIUM < MessagePriority.LOW


class TestAgentMessage:
    def test_defaults(self):
        msg = AgentMessage()
        assert msg.id  # UUID generated
        assert msg.type == MessageType.TASK_ASSIGNED
        assert msg.priority == MessagePriority.MEDIUM
        assert msg.from_agent is None


class TestCreateMessage:
    def test_factory(self):
        msg = create_message(
            MessageType.ANALYSIS_READY,
            payload={"result": "ok"},
            from_agent=AgentType.ANALYZER,
            to_agent=AgentType.REPORTER,
            session_id="sess-1",
        )
        assert msg.type == MessageType.ANALYSIS_READY
        assert msg.from_agent == AgentType.ANALYZER
        assert msg.to_agent == AgentType.REPORTER
        assert msg.payload == {"result": "ok"}
        assert msg.session_id == "sess-1"
