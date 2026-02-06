"""Agent registry — decorator-based registration and factory for NightWatch agents.

Usage::

    from nightwatch.agents.registry import register_agent
    from nightwatch.types.agents import AgentType

    @register_agent(AgentType.ANALYZER)
    class AnalyzerAgent(BaseAgent):
        async def execute(self, context):
            ...
"""

from __future__ import annotations

import logging
from typing import Any

from nightwatch.types.agents import AgentType

logger = logging.getLogger("nightwatch.agents")

_REGISTRY: dict[AgentType, type] = {}


def register_agent(agent_type: AgentType):
    """Class decorator that registers an agent class for *agent_type*."""

    def _decorator(cls: type) -> type:
        if agent_type in _REGISTRY:
            logger.warning(
                "Overwriting agent registration for %s: %s -> %s",
                agent_type,
                _REGISTRY[agent_type].__name__,
                cls.__name__,
            )
        cls.agent_type = agent_type  # type: ignore[attr-defined]
        _REGISTRY[agent_type] = cls
        return cls

    return _decorator


def get_agent_class(agent_type: AgentType) -> type:
    """Return the registered class for *agent_type*.

    Raises ``KeyError`` if no agent is registered for the given type.
    """
    if agent_type not in _REGISTRY:
        raise KeyError(f"No agent registered for type: {agent_type}")
    return _REGISTRY[agent_type]


def create_agent(agent_type: AgentType, **kwargs: Any):
    """Instantiate a registered agent by type."""
    cls = get_agent_class(agent_type)
    return cls(**kwargs)


def list_registered() -> dict[AgentType, type]:
    """Return a copy of the current registry."""
    return dict(_REGISTRY)


def clear_registry() -> None:
    """Remove all registrations (for testing)."""
    _REGISTRY.clear()
