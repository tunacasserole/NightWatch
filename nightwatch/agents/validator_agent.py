"""ValidatorAgent — wraps nightwatch.validation.validate_file_changes.

Named ``validator_agent.py`` to avoid confusion with ``nightwatch/validation.py``.
"""

from __future__ import annotations

from nightwatch.agents.base import BaseAgent
from nightwatch.agents.registry import register_agent
from nightwatch.types.agents import AgentContext, AgentResult, AgentType


@register_agent(AgentType.VALIDATOR)
class ValidatorAgent(BaseAgent):
    """Thin async wrapper around ``validate_file_changes``."""

    async def execute(self, context: AgentContext) -> AgentResult:
        async def _run() -> AgentResult:
            from nightwatch.validation import validate_file_changes

            state = context.agent_state
            result = validate_file_changes(
                analysis=state["analysis"],
                github_client=state["github_client"],
            )
            return AgentResult(
                success=True,
                data=result,
                confidence=1.0 if result.is_valid else 0.0,
            )

        return await self.execute_with_timeout(context, _run)
