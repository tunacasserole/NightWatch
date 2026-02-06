"""Phase-based execution pipeline replacing monolithic run().

Orchestrates agents through 7 explicit phases (INGESTION → LEARNING),
coordinated by the message bus and state manager. Feature-flagged via
NIGHTWATCH_PIPELINE_V2 with automatic fallback to existing run().

GANDALF-001d
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from nightwatch.orchestration.message_bus import MessageBus
from nightwatch.orchestration.state_manager import StateManager
from nightwatch.types.agents import AgentContext, AgentResult, AgentType
from nightwatch.types.messages import MessageType, create_message
from nightwatch.types.orchestration import (
    ExecutionPhase,
    PhaseResult,
    PipelineConfig,
)

logger = logging.getLogger("nightwatch.pipeline")


@dataclass
class Phase:
    """Definition of a single pipeline phase."""

    name: ExecutionPhase
    agent_types: list[AgentType] = field(default_factory=list)
    per_error: bool = False
    parallel: bool = False
    custom_handler: Callable[..., Coroutine[Any, Any, PhaseResult]] | None = None


class Pipeline:
    """Phase-based execution pipeline for NightWatch.

    Replaces the monolithic ``run()`` with 7 explicit phases, each delegating
    to registered agents or custom handlers. State is tracked via an immutable
    StateManager and inter-agent communication flows through a MessageBus.
    """

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or PipelineConfig()
        self.bus = MessageBus()
        self.state_manager = StateManager()
        self._phases = self._build_phases()
        self._run_kwargs: dict[str, Any] = {}

    def _build_phases(self) -> list[Phase]:
        return [
            Phase(ExecutionPhase.INGESTION, custom_handler=self._run_ingestion),
            Phase(ExecutionPhase.ENRICHMENT, agent_types=[AgentType.RESEARCHER]),
            Phase(
                ExecutionPhase.ANALYSIS,
                agent_types=[AgentType.ANALYZER],
                per_error=True,
            ),
            Phase(ExecutionPhase.SYNTHESIS, agent_types=[AgentType.PATTERN_DETECTOR]),
            Phase(ExecutionPhase.REPORTING, agent_types=[AgentType.REPORTER]),
            Phase(
                ExecutionPhase.ACTION,
                agent_types=[AgentType.VALIDATOR, AgentType.REPORTER],
            ),
            Phase(ExecutionPhase.LEARNING, custom_handler=self._run_learning),
        ]

    # -- Public API -----------------------------------------------------------

    async def execute(self, **run_kwargs: Any) -> Any:
        """Execute the full pipeline, returning a RunReport.

        Falls back to the existing ``run()`` function on failure when
        ``config.enable_fallback`` is True.
        """
        from nightwatch.models import RunReport

        self._run_kwargs = run_kwargs
        session_id = str(uuid.uuid4())
        start_time = time.time()

        try:
            state = self.state_manager.initialize_state(session_id)
            phase_results: list[PhaseResult] = []

            for phase_def in self._phases:
                self.state_manager.set_phase(session_id, phase_def.name)

                self.bus.publish(
                    create_message(
                        msg_type=MessageType.PHASE_COMPLETE,
                        payload={"phase": phase_def.name, "status": "starting"},
                        session_id=session_id,
                    )
                )

                result = await self._execute_phase(phase_def, session_id)
                phase_results.append(result)

                if not result.success:
                    logger.error(
                        "Phase %s failed: %s", phase_def.name, result.error_message
                    )
                    # Non-critical phases can fail without stopping the pipeline
                    if phase_def.name in (
                        ExecutionPhase.INGESTION,
                        ExecutionPhase.ANALYSIS,
                    ):
                        raise RuntimeError(
                            f"Critical phase {phase_def.name} failed: {result.error_message}"
                        )

            # Mark pipeline complete
            self.state_manager.complete(session_id)
            final_state = self.state_manager.get_state(session_id)

            # Build RunReport from accumulated state
            elapsed = time.time() - start_time
            analyses = final_state.analyses_data
            total_tokens = sum(
                getattr(a, "tokens_used", 0) for a in analyses
            )
            total_api_calls = sum(
                getattr(a, "api_calls", 0) for a in analyses
            )

            report = RunReport(
                timestamp=datetime.now(UTC).isoformat(),
                lookback=run_kwargs.get("since", ""),
                total_errors_found=final_state.metadata.get("total_errors_found", 0),
                errors_filtered=final_state.metadata.get("errors_filtered", 0),
                errors_analyzed=len(analyses),
                analyses=analyses,
                total_tokens_used=total_tokens,
                total_api_calls=total_api_calls,
                run_duration_seconds=elapsed,
                patterns=final_state.metadata.get("patterns", []),
                issues_created=final_state.metadata.get("issues_created", []),
                pr_created=final_state.metadata.get("pr_created"),
            )

            return report

        except Exception as exc:
            logger.error("Pipeline failed: %s", exc)
            return await self._fallback(run_kwargs, exc)
        finally:
            self.bus.clear_session(session_id)
            self.state_manager.remove_state(session_id)

    # -- Phase execution ------------------------------------------------------

    async def _execute_phase(
        self, phase_def: Phase, session_id: str
    ) -> PhaseResult:
        """Execute a single pipeline phase."""
        start = time.monotonic()

        try:
            if phase_def.custom_handler is not None:
                return await phase_def.custom_handler(session_id)

            # Agent-based phase
            return await self._run_agent_phase(phase_def, session_id)

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.exception("Phase %s error: %s", phase_def.name, exc)
            return PhaseResult(
                phase=phase_def.name,
                success=False,
                execution_time_ms=elapsed_ms,
                error_message=str(exc),
            )

    async def _run_agent_phase(
        self, phase_def: Phase, session_id: str
    ) -> PhaseResult:
        """Execute a phase that delegates to registered agents."""
        start = time.monotonic()
        agent_results: dict[AgentType, AgentResult] = {}

        # Import agent modules to trigger @register_agent decorators
        import nightwatch.agents.error_analyzer  # noqa: F401
        import nightwatch.agents.pattern_detector  # noqa: F401
        import nightwatch.agents.reporter  # noqa: F401
        import nightwatch.agents.researcher  # noqa: F401
        import nightwatch.agents.validator_agent  # noqa: F401
        from nightwatch.agents.registry import create_agent

        state = self.state_manager.get_state(session_id)

        if phase_def.per_error:
            # Run agent once per error (e.g., ANALYSIS phase)
            errors = state.errors_data
            analyses = []
            for error_data in errors:
                for agent_type in phase_def.agent_types:
                    agent = create_agent(agent_type)
                    agent.initialize(self.bus)

                    context = AgentContext(
                        session_id=session_id,
                        run_id=session_id,
                        agent_state=self._build_agent_state(
                            phase_def.name, agent_type, session_id, error_data=error_data
                        ),
                        dry_run=self.config.dry_run,
                    )

                    result = await agent.execute(context)
                    agent.cleanup()

                    if result.success and result.data is not None:
                        analyses.append(result.data)
                    agent_results[agent_type] = result

            # Store analyses in state
            self.state_manager.update_state(session_id, analyses_data=analyses)
        else:
            # Run each agent type once
            for agent_type in phase_def.agent_types:
                agent = create_agent(agent_type)
                agent.initialize(self.bus)

                context = AgentContext(
                    session_id=session_id,
                    run_id=session_id,
                    agent_state=self._build_agent_state(
                        phase_def.name, agent_type, session_id
                    ),
                    dry_run=self.config.dry_run,
                )

                result = await agent.execute(context)
                agent.cleanup()
                agent_results[agent_type] = result

                # Store phase-specific results in metadata
                self._store_agent_result(
                    session_id, phase_def.name, agent_type, result
                )

        elapsed_ms = (time.monotonic() - start) * 1000
        success = all(r.success for r in agent_results.values())

        return PhaseResult(
            phase=phase_def.name,
            success=success,
            agent_results=agent_results,
            execution_time_ms=elapsed_ms,
        )

    # -- Custom phase handlers ------------------------------------------------

    async def _run_ingestion(self, session_id: str) -> PhaseResult:
        """INGESTION phase: fetch errors from New Relic, filter, rank, fetch traces."""
        start = time.monotonic()

        try:
            from nightwatch.config import get_settings
            from nightwatch.newrelic import (
                NewRelicClient,
                filter_errors,
                load_ignore_patterns,
                rank_errors,
            )

            settings = get_settings()
            since = self._run_kwargs.get("since") or settings.nightwatch_since
            max_errors = self._run_kwargs.get("max_errors") or settings.nightwatch_max_errors

            nr = NewRelicClient()
            try:
                all_errors = nr.fetch_errors(since=since)
                ignore_patterns = load_ignore_patterns()
                filtered = filter_errors(all_errors, ignore_patterns)
                errors_filtered = len(all_errors) - len(filtered)
                ranked = rank_errors(filtered)
                top_errors = ranked[:max_errors]

                # Fetch traces
                traces_map: dict[int, Any] = {}
                for error in top_errors:
                    traces_map[id(error)] = nr.fetch_traces(error, since=since)

                # Store in pipeline state
                self.state_manager.update_state(
                    session_id,
                    errors_data=top_errors,
                    metadata={
                        "total_errors_found": len(all_errors),
                        "errors_filtered": errors_filtered,
                        "traces_map": traces_map,
                        "since": since,
                    },
                )

                # Broadcast errors ready
                self.bus.publish(
                    create_message(
                        msg_type=MessageType.ERRORS_READY,
                        payload={"count": len(top_errors)},
                        session_id=session_id,
                    )
                )

                elapsed_ms = (time.monotonic() - start) * 1000
                return PhaseResult(
                    phase=ExecutionPhase.INGESTION,
                    success=True,
                    execution_time_ms=elapsed_ms,
                )
            finally:
                nr.close()

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return PhaseResult(
                phase=ExecutionPhase.INGESTION,
                success=False,
                execution_time_ms=elapsed_ms,
                error_message=str(exc),
            )

    async def _run_learning(self, session_id: str) -> PhaseResult:
        """LEARNING phase: persist analysis results to knowledge base."""
        start = time.monotonic()

        try:
            from nightwatch.config import get_settings

            settings = get_settings()
            state = self.state_manager.get_state(session_id)

            if self.config.dry_run or not settings.nightwatch_compound_enabled:
                elapsed_ms = (time.monotonic() - start) * 1000
                return PhaseResult(
                    phase=ExecutionPhase.LEARNING,
                    success=True,
                    execution_time_ms=elapsed_ms,
                )

            from nightwatch.knowledge import compound_result, rebuild_index, save_error_pattern

            for analysis_result in state.analyses_data:
                try:
                    compound_result(analysis_result)
                except Exception as e:
                    logger.warning("Knowledge compounding failed for result: %s", e)

                # Save high-confidence error patterns
                if (
                    getattr(analysis_result, "quality_score", 0) >= 0.7
                    and getattr(analysis_result.analysis, "root_cause", None)
                ):
                    try:
                        save_error_pattern(
                            error_class=analysis_result.error.error_class,
                            transaction=analysis_result.error.transaction,
                            pattern_description=analysis_result.analysis.root_cause[:500],
                            confidence=str(analysis_result.analysis.confidence),
                        )
                    except Exception as e:
                        logger.warning("Error pattern save failed: %s", e)

            rebuild_index()

            elapsed_ms = (time.monotonic() - start) * 1000
            return PhaseResult(
                phase=ExecutionPhase.LEARNING,
                success=True,
                execution_time_ms=elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return PhaseResult(
                phase=ExecutionPhase.LEARNING,
                success=False,
                execution_time_ms=elapsed_ms,
                error_message=str(exc),
            )

    # -- Helpers --------------------------------------------------------------

    def _build_agent_state(
        self,
        phase: ExecutionPhase,
        agent_type: AgentType,
        session_id: str,
        error_data: Any = None,
    ) -> dict[str, Any]:
        """Build the agent_state dict for a given phase and agent type."""
        state = self.state_manager.get_state(session_id)
        metadata = state.metadata
        agent_state: dict[str, Any] = {}

        if phase == ExecutionPhase.ENRICHMENT and agent_type == AgentType.RESEARCHER:
            if error_data is not None:
                agent_state["error"] = error_data
                traces_map = metadata.get("traces_map", {})
                agent_state["traces"] = traces_map.get(id(error_data), [])
            agent_state["github_client"] = self._run_kwargs.get("github_client")
            agent_state["correlated_prs"] = metadata.get("correlated_prs")

        elif phase == ExecutionPhase.ANALYSIS and agent_type == AgentType.ANALYZER:
            agent_state["error"] = error_data
            traces_map = metadata.get("traces_map", {})
            agent_state["traces"] = traces_map.get(id(error_data), [])
            agent_state["github_client"] = self._run_kwargs.get("github_client")
            agent_state["newrelic_client"] = self._run_kwargs.get("newrelic_client")
            agent_state["run_context"] = self._run_kwargs.get("run_context")
            agent_state["agent_name"] = self._run_kwargs.get("agent_name", "base-analyzer")

        elif phase == ExecutionPhase.SYNTHESIS and agent_type == AgentType.PATTERN_DETECTOR:
            agent_state["analyses"] = state.analyses_data

        elif phase == ExecutionPhase.REPORTING and agent_type == AgentType.REPORTER:
            agent_state["report"] = self._run_kwargs.get("report")
            agent_state["slack_client"] = self._run_kwargs.get("slack_client")
            agent_state["patterns"] = metadata.get("patterns", [])

        elif phase == ExecutionPhase.ACTION:
            if agent_type == AgentType.VALIDATOR:
                agent_state["github_client"] = self._run_kwargs.get("github_client")
                # Validator needs the analysis with file changes
                if state.analyses_data:
                    agent_state["analysis"] = state.analyses_data[0].analysis
            elif agent_type == AgentType.REPORTER:
                agent_state["report"] = self._run_kwargs.get("report")
                agent_state["slack_client"] = self._run_kwargs.get("slack_client")

        return agent_state

    def _store_agent_result(
        self,
        session_id: str,
        phase: ExecutionPhase,
        agent_type: AgentType,
        result: AgentResult,
    ) -> None:
        """Store agent results in pipeline metadata for downstream phases."""
        if not result.success or result.data is None:
            return

        state = self.state_manager.get_state(session_id)
        metadata = dict(state.metadata)

        if phase == ExecutionPhase.SYNTHESIS and agent_type == AgentType.PATTERN_DETECTOR:
            metadata["patterns"] = result.data
        elif phase == ExecutionPhase.REPORTING and agent_type == AgentType.REPORTER:
            metadata["report_sent"] = True
        elif phase == ExecutionPhase.ACTION and agent_type == AgentType.VALIDATOR:
            metadata["validation_result"] = result.data

        self.state_manager.update_state(session_id, metadata=metadata)

    # -- Fallback -------------------------------------------------------------

    async def _fallback(self, run_kwargs: dict[str, Any], exc: Exception) -> Any:
        """Fall back to the existing run() function."""
        if not self.config.enable_fallback:
            raise RuntimeError(f"Pipeline failed and fallback is disabled: {exc}") from exc

        logger.warning("Pipeline failed, falling back to run(): %s", exc)
        from nightwatch.runner import run

        # Strip pipeline-specific kwargs
        allowed = {"since", "max_errors", "max_issues", "dry_run", "verbose", "model", "agent_name"}
        v1_kwargs = {k: v for k, v in run_kwargs.items() if k in allowed}
        return run(**v1_kwargs)
