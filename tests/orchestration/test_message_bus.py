"""Tests for the in-memory message bus."""

import pytest

from nightwatch.orchestration.message_bus import MessageBus
from nightwatch.types.agents import AgentType
from nightwatch.types.messages import (
    MessagePriority,
    MessageType,
    create_message,
)


@pytest.fixture
def bus():
    return MessageBus()


def test_publish_delivers_to_targeted_subscriber(bus):
    received = []
    bus.subscribe(AgentType.ANALYZER, None, lambda msg: received.append(msg))
    msg = create_message(
        MessageType.TASK_ASSIGNED,
        payload="test",
        to_agent=AgentType.ANALYZER,
        session_id="s1",
    )
    bus.publish(msg)
    assert len(received) == 1
    assert received[0].payload == "test"


def test_publish_skips_non_targeted_subscriber(bus):
    received = []
    bus.subscribe(AgentType.REPORTER, None, lambda msg: received.append(msg))
    msg = create_message(
        MessageType.TASK_ASSIGNED,
        payload="test",
        to_agent=AgentType.ANALYZER,
        session_id="s1",
    )
    bus.publish(msg)
    assert len(received) == 0


def test_broadcast_delivers_to_all(bus):
    received_a = []
    received_b = []
    bus.subscribe(AgentType.ANALYZER, None, lambda msg: received_a.append(msg))
    bus.subscribe(AgentType.REPORTER, None, lambda msg: received_b.append(msg))
    msg = create_message(MessageType.PHASE_COMPLETE, payload="done", session_id="s1")
    bus.broadcast(msg)
    assert len(received_a) == 1
    assert len(received_b) == 1


def test_subscribe_with_type_filter(bus):
    received = []
    bus.subscribe(
        AgentType.ANALYZER,
        MessageType.TASK_ASSIGNED,
        lambda msg: received.append(msg),
    )
    bus.publish(create_message(MessageType.TASK_ASSIGNED, session_id="s1"))
    bus.publish(create_message(MessageType.TASK_COMPLETED, session_id="s1"))
    assert len(received) == 1


def test_subscribe_without_filter(bus):
    received = []
    bus.subscribe(AgentType.ANALYZER, None, lambda msg: received.append(msg))
    bus.publish(create_message(MessageType.TASK_ASSIGNED, session_id="s1"))
    bus.publish(create_message(MessageType.TASK_COMPLETED, session_id="s1"))
    assert len(received) == 2


def test_unsubscribe_stops_delivery(bus):
    received = []
    sub_id = bus.subscribe(AgentType.ANALYZER, None, lambda msg: received.append(msg))
    bus.publish(create_message(MessageType.TASK_ASSIGNED, session_id="s1"))
    assert len(received) == 1
    bus.unsubscribe(sub_id)
    bus.publish(create_message(MessageType.TASK_ASSIGNED, session_id="s1"))
    assert len(received) == 1


def test_messages_are_deep_copied(bus):
    received = []
    bus.subscribe(AgentType.ANALYZER, None, lambda msg: received.append(msg))
    msg = create_message(
        MessageType.TASK_ASSIGNED,
        payload={"key": "value"},
        session_id="s1",
    )
    bus.publish(msg)
    received[0].payload["key"] = "modified"
    stored = bus.get_messages("s1")
    assert stored[0].payload["key"] == "value"


def test_handler_error_doesnt_propagate(bus):
    def bad_handler(msg):
        raise RuntimeError("boom")

    bus.subscribe(AgentType.ANALYZER, None, bad_handler)
    # Should not raise
    bus.publish(create_message(MessageType.TASK_ASSIGNED, session_id="s1"))


def test_get_messages_returns_copies(bus):
    bus.publish(create_message(MessageType.TASK_ASSIGNED, payload="a", session_id="s1"))
    msgs1 = bus.get_messages("s1")
    msgs2 = bus.get_messages("s1")
    assert msgs1[0] is not msgs2[0]


def test_get_messages_by_priority(bus):
    bus.publish(
        create_message(
            MessageType.TASK_ASSIGNED,
            priority=MessagePriority.LOW,
            session_id="s1",
        )
    )
    bus.publish(
        create_message(
            MessageType.TASK_COMPLETED,
            priority=MessagePriority.HIGH,
            session_id="s1",
        )
    )
    msgs = bus.get_messages_by_priority("s1")
    assert msgs[0].priority == MessagePriority.HIGH
    assert msgs[1].priority == MessagePriority.LOW


def test_clear_session(bus):
    bus.publish(create_message(MessageType.TASK_ASSIGNED, session_id="s1"))
    bus.publish(create_message(MessageType.TASK_ASSIGNED, session_id="s2"))
    bus.clear_session("s1")
    assert len(bus.get_messages("s1")) == 0
    assert len(bus.get_messages("s2")) == 1
