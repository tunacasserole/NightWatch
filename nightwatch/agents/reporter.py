"""ReporterAgent — sends run reports via Slack (and future channels)."""

from __future__ import annotations

from nightwatch.agents.base import BaseAgent
from nightwatch.agents.registry import register_agent
from nightwatch.types.agents import AgentContext, AgentResult, AgentType


@register_agent(AgentType.REPORTER)
class ReporterAgent(BaseAgent):
    """Thin async wrapper around Slack report delivery."""

    async def execute(self, context: AgentContext) -> AgentResult:
        async def _run() -> AgentResult:
            state = context.agent_state
            results: dict = {}

            if "report" in state and "slack_client" in state:
                from nightwatch.slack import SlackClient

                slack: SlackClient = state["slack_client"]
                slack.send_run_report(
                    state["report"],
                    state.get("patterns", []),
                    state.get("ignore_suggestions", []),
                )
                results["slack_sent"] = True

            return AgentResult(success=True, data=results)

        return await self.execute_with_timeout(context, _run)
