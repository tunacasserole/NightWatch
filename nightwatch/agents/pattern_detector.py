"""PatternDetectorAgent — wraps nightwatch.patterns.detect_patterns_with_knowledge."""

from __future__ import annotations

from nightwatch.agents.base import BaseAgent
from nightwatch.agents.registry import register_agent
from nightwatch.types.agents import AgentContext, AgentResult, AgentType


@register_agent(AgentType.PATTERN_DETECTOR)
class PatternDetectorAgent(BaseAgent):
    """Thin async wrapper around ``detect_patterns_with_knowledge``."""

    async def execute(self, context: AgentContext) -> AgentResult:
        async def _run() -> AgentResult:
            from nightwatch.patterns import detect_patterns_with_knowledge

            state = context.agent_state
            patterns = detect_patterns_with_knowledge(
                analyses=state["analyses"],
                knowledge_dir=state.get("knowledge_dir", "nightwatch/knowledge"),
            )
            return AgentResult(success=True, data=patterns)

        return await self.execute_with_timeout(context, _run)
