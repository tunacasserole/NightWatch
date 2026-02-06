"""AnalyzerAgent — wraps nightwatch.analyzer.analyze_error as a BaseAgent."""

from __future__ import annotations

from nightwatch.agents.base import BaseAgent
from nightwatch.agents.registry import register_agent
from nightwatch.types.agents import AgentContext, AgentResult, AgentType


@register_agent(AgentType.ANALYZER)
class AnalyzerAgent(BaseAgent):
    """Thin async wrapper around the synchronous ``analyze_error`` function."""

    async def execute(self, context: AgentContext) -> AgentResult:
        async def _run() -> AgentResult:
            from nightwatch.analyzer import analyze_error

            state = context.agent_state
            result = analyze_error(
                error=state["error"],
                traces=state["traces"],
                github_client=state["github_client"],
                newrelic_client=state["newrelic_client"],
                run_context=state.get("run_context"),
                prior_analyses=state.get("prior_analyses"),
                research_context=state.get("research_context"),
                agent_name=state.get("agent_name", "base-analyzer"),
                prior_context=state.get("prior_context"),
            )
            return AgentResult(
                success=True,
                data=result,
                confidence=_confidence_to_float(result.analysis.confidence),
            )

        return await self.execute_with_timeout(context, _run)


def _confidence_to_float(confidence: object) -> float:
    """Map a ``Confidence`` enum value (or string) to a float score."""
    mapping = {"high": 0.9, "medium": 0.6, "low": 0.3}
    return mapping.get(str(confidence).lower(), 0.5)
