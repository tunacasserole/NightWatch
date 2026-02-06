"""NightWatch agent system.

Re-exports legacy API for backward compatibility.
New code should use: from nightwatch.agents.base import BaseAgent
"""

from nightwatch.agents._legacy import (
    AgentConfig,
    _parse_agent_frontmatter,
    list_agents,
    load_agent,
)

__all__ = ["AgentConfig", "load_agent", "list_agents", "_parse_agent_frontmatter"]
