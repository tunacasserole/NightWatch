"""In-memory pub/sub message bus for inter-agent communication.

Single interface design (fixes Gandalf's dual IMessageBus problem).
Uses copy.deepcopy() for message isolation instead of JSON.parse/stringify.
"""

from __future__ import annotations

import copy
import logging
import uuid
from collections import defaultdict
from collections.abc import Callable

from nightwatch.types.agents import AgentType
from nightwatch.types.messages import AgentMessage, MessageType

logger = logging.getLogger("nightwatch.orchestration.bus")

MessageHandler = Callable[[AgentMessage], None]


class MessageBus:
    """In-memory pub/sub with typed handlers."""

    def __init__(self) -> None:
        self._subscribers: dict[str, tuple[AgentType, MessageType | None, MessageHandler]] = {}
        self._messages: dict[str, list[AgentMessage]] = defaultdict(list)

    def subscribe(
        self,
        agent_type: AgentType,
        msg_type: MessageType | None,
        handler: MessageHandler,
    ) -> str:
        """Subscribe to messages. msg_type=None subscribes to all types."""
        sub_id = str(uuid.uuid4())
        self._subscribers[sub_id] = (agent_type, msg_type, handler)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription by ID."""
        self._subscribers.pop(subscription_id, None)

    def publish(self, message: AgentMessage) -> None:
        """Publish message to targeted agent or broadcast."""
        self._messages[message.session_id].append(copy.deepcopy(message))
        for _sub_id, (agent_type, msg_type, handler) in list(self._subscribers.items()):
            if message.to_agent is not None and message.to_agent != agent_type:
                continue
            if msg_type is not None and message.type != msg_type:
                continue
            try:
                handler(copy.deepcopy(message))
            except Exception as e:
                logger.error(f"Handler error: {e}")

    def broadcast(self, message: AgentMessage) -> None:
        """Broadcast message to all subscribers (clears to_agent)."""
        msg = copy.deepcopy(message)
        broadcast_msg = AgentMessage(
            id=msg.id,
            from_agent=msg.from_agent,
            to_agent=None,
            type=msg.type,
            payload=msg.payload,
            timestamp=msg.timestamp,
            priority=msg.priority,
            session_id=msg.session_id,
        )
        self.publish(broadcast_msg)

    def get_messages(self, session_id: str) -> list[AgentMessage]:
        """Return deep copies of all messages for a session."""
        return [copy.deepcopy(m) for m in self._messages.get(session_id, [])]

    def get_messages_by_priority(self, session_id: str) -> list[AgentMessage]:
        """Return messages sorted by priority (HIGH=0 first)."""
        msgs = self.get_messages(session_id)
        return sorted(msgs, key=lambda m: m.priority)

    def clear_session(self, session_id: str) -> None:
        """Remove all stored messages for a session."""
        self._messages.pop(session_id, None)

    def clear_all(self) -> None:
        """Remove all subscribers and messages."""
        self._subscribers.clear()
        self._messages.clear()
