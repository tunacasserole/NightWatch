"""ResearcherAgent — wraps nightwatch.research.research_error as a BaseAgent."""

from __future__ import annotations

from nightwatch.agents.base import BaseAgent
from nightwatch.agents.registry import register_agent
from nightwatch.types.agents import AgentContext, AgentResult, AgentType


@register_agent(AgentType.RESEARCHER)
class ResearcherAgent(BaseAgent):
    """Thin async wrapper around the synchronous ``research_error`` function."""

    async def execute(self, context: AgentContext) -> AgentResult:
        async def _run() -> AgentResult:
            from nightwatch.research import research_error

            state = context.agent_state
            result = research_error(
                error=state["error"],
                traces=state["traces"],
                github_client=state["github_client"],
                correlated_prs=state.get("correlated_prs"),
            )
            return AgentResult(success=True, data=result)

        return await self.execute_with_timeout(context, _run)
