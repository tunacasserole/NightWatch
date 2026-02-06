"""Tests for the phase-based execution pipeline (GANDALF-001d)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nightwatch.orchestration.pipeline import Phase, Pipeline
from nightwatch.types.agents import AgentResult, AgentType
from nightwatch.types.orchestration import ExecutionPhase, PipelineConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_analysis():
    """Create a minimal fake ErrorAnalysisResult for testing."""
    analysis = MagicMock()
    analysis.confidence = "high"
    analysis.root_cause = "Test root cause"
    analysis.has_fix = True
    analysis.file_changes = []
    analysis.suggested_next_steps = []
    analysis.title = "Test"
    analysis.reasoning = "Test reasoning"

    result = MagicMock()
    result.analysis = analysis
    result.error = MagicMock()
    result.error.error_class = "TestError"
    result.error.transaction = "TestTransaction"
    result.tokens_used = 100
    result.api_calls = 1
    result.pass_count = 1
    result.iterations = 1
    result.quality_score = 0.8
    return result


def _make_pipeline(dry_run=False, enable_fallback=True):
    """Create a Pipeline with controlled config."""
    config = PipelineConfig(dry_run=dry_run, enable_fallback=enable_fallback)
    return Pipeline(config=config)


# ---------------------------------------------------------------------------
# Phase definition tests
# ---------------------------------------------------------------------------


class TestPhaseDefinition:
    def test_phase_has_name(self):
        p = Phase(name=ExecutionPhase.INGESTION)
        assert p.name == ExecutionPhase.INGESTION

    def test_phase_defaults(self):
        p = Phase(name=ExecutionPhase.ANALYSIS)
        assert p.agent_types == []
        assert p.per_error is False
        assert p.parallel is False
        assert p.custom_handler is None


# ---------------------------------------------------------------------------
# Pipeline construction tests
# ---------------------------------------------------------------------------


class TestPipelineConstruction:
    def test_default_config(self):
        pipeline = Pipeline()
        assert pipeline.config.enable_fallback is True
        assert pipeline.config.dry_run is False

    def test_custom_config(self):
        config = PipelineConfig(dry_run=True, enable_fallback=False)
        pipeline = Pipeline(config=config)
        assert pipeline.config.dry_run is True
        assert pipeline.config.enable_fallback is False

    def test_builds_seven_phases(self):
        pipeline = Pipeline()
        assert len(pipeline._phases) == 7

    def test_phase_order(self):
        pipeline = Pipeline()
        expected_order = [
            ExecutionPhase.INGESTION,
            ExecutionPhase.ENRICHMENT,
            ExecutionPhase.ANALYSIS,
            ExecutionPhase.SYNTHESIS,
            ExecutionPhase.REPORTING,
            ExecutionPhase.ACTION,
            ExecutionPhase.LEARNING,
        ]
        actual_order = [p.name for p in pipeline._phases]
        assert actual_order == expected_order

    def test_analysis_phase_is_per_error(self):
        pipeline = Pipeline()
        analysis_phase = [p for p in pipeline._phases if p.name == ExecutionPhase.ANALYSIS][0]
        assert analysis_phase.per_error is True

    def test_ingestion_has_custom_handler(self):
        pipeline = Pipeline()
        ingestion = pipeline._phases[0]
        assert ingestion.custom_handler is not None

    def test_learning_has_custom_handler(self):
        pipeline = Pipeline()
        learning = pipeline._phases[-1]
        assert learning.custom_handler is not None


# ---------------------------------------------------------------------------
# Pipeline execution tests (mocked agents)
# ---------------------------------------------------------------------------


class TestPipelineExecution:
    """Test pipeline execution with fully mocked agents and handlers."""

    @pytest.fixture
    def pipeline(self):
        return _make_pipeline()

    def test_pipeline_executes_all_phases(self, pipeline):
        """All 7 phases execute in order."""
        executed_phases = []

        async def fake_handler(session_id):
            from nightwatch.types.orchestration import PhaseResult

            return PhaseResult(phase=ExecutionPhase.INGESTION, success=True)

        async def run():
            # Replace all phases with simple tracking handlers
            for i, phase_def in enumerate(pipeline._phases):
                phase_name = phase_def.name

                async def make_handler(name=phase_name):
                    executed_phases.append(name)
                    from nightwatch.types.orchestration import PhaseResult

                    return PhaseResult(phase=name, success=True)

                pipeline._phases[i] = Phase(
                    name=phase_name,
                    custom_handler=lambda sid, n=phase_name: make_handler(n),
                )

            await pipeline.execute()

        asyncio.run(run())
        assert len(executed_phases) == 7
        assert executed_phases == [
            ExecutionPhase.INGESTION,
            ExecutionPhase.ENRICHMENT,
            ExecutionPhase.ANALYSIS,
            ExecutionPhase.SYNTHESIS,
            ExecutionPhase.REPORTING,
            ExecutionPhase.ACTION,
            ExecutionPhase.LEARNING,
        ]

    def test_pipeline_state_transitions(self, pipeline):
        """State moves through INGESTION→...→COMPLETE."""
        observed_phases = []

        original_set_phase = pipeline.state_manager.set_phase

        def tracking_set_phase(session_id, phase):
            observed_phases.append(phase)
            return original_set_phase(session_id, phase)

        pipeline.state_manager.set_phase = tracking_set_phase

        async def run():
            # Replace all phases with no-op handlers
            for i, phase_def in enumerate(pipeline._phases):
                phase_name = phase_def.name

                async def noop_handler(sid, n=phase_name):
                    from nightwatch.types.orchestration import PhaseResult

                    return PhaseResult(phase=n, success=True)

                pipeline._phases[i] = Phase(
                    name=phase_name,
                    custom_handler=noop_handler,
                )

            await pipeline.execute()

        asyncio.run(run())
        assert ExecutionPhase.INGESTION in observed_phases
        assert ExecutionPhase.LEARNING in observed_phases
        assert len(observed_phases) == 7

    def test_pipeline_fallback_on_failure(self):
        """Falls back to run() when enable_fallback=True."""
        pipeline = _make_pipeline(enable_fallback=True)

        async def failing_handler(session_id):
            raise RuntimeError("Critical failure in ingestion")

        # Make ingestion fail
        pipeline._phases[0] = Phase(
            name=ExecutionPhase.INGESTION,
            custom_handler=failing_handler,
        )

        with patch("nightwatch.runner.run") as mock_run:
            mock_run.return_value = MagicMock()
            result = asyncio.run(pipeline.execute(since="1h"))
            mock_run.assert_called_once()

    def test_pipeline_raises_on_failure_no_fallback(self):
        """Raises RuntimeError when fallback disabled."""
        pipeline = _make_pipeline(enable_fallback=False)

        async def failing_handler(session_id):
            raise RuntimeError("Critical failure")

        pipeline._phases[0] = Phase(
            name=ExecutionPhase.INGESTION,
            custom_handler=failing_handler,
        )

        with pytest.raises(RuntimeError, match="fallback is disabled"):
            asyncio.run(pipeline.execute())

    def test_pipeline_produces_run_report(self):
        """Output is a valid RunReport."""
        pipeline = _make_pipeline()

        async def run():
            # Replace all phases with no-ops
            for i, phase_def in enumerate(pipeline._phases):
                phase_name = phase_def.name

                async def noop(sid, n=phase_name):
                    from nightwatch.types.orchestration import PhaseResult

                    return PhaseResult(phase=n, success=True)

                pipeline._phases[i] = Phase(name=phase_name, custom_handler=noop)

            return await pipeline.execute(since="1h")

        report = asyncio.run(run())
        assert hasattr(report, "timestamp")
        assert hasattr(report, "errors_analyzed")
        assert hasattr(report, "analyses")
        assert report.lookback == "1h"

    def test_pipeline_per_error_phase(self):
        """ANALYSIS phase runs agent per error when mocked."""
        pipeline = _make_pipeline()
        call_count = 0

        # Set up ingestion to populate errors
        async def fake_ingestion(session_id):
            from nightwatch.types.orchestration import PhaseResult

            errors = [MagicMock(), MagicMock(), MagicMock()]
            pipeline.state_manager.update_state(
                session_id,
                errors_data=errors,
                metadata={"total_errors_found": 3, "errors_filtered": 0, "traces_map": {}},
            )
            return PhaseResult(phase=ExecutionPhase.INGESTION, success=True)

        # Track calls to the analysis phase
        async def fake_analysis(session_id):
            nonlocal call_count
            from nightwatch.types.orchestration import PhaseResult

            state = pipeline.state_manager.get_state(session_id)
            call_count = len(state.errors_data)
            # Simulate analyses
            analyses = [_make_fake_analysis() for _ in state.errors_data]
            pipeline.state_manager.update_state(session_id, analyses_data=analyses)
            return PhaseResult(phase=ExecutionPhase.ANALYSIS, success=True)

        pipeline._phases[0] = Phase(
            name=ExecutionPhase.INGESTION,
            custom_handler=fake_ingestion,
        )
        pipeline._phases[2] = Phase(
            name=ExecutionPhase.ANALYSIS,
            custom_handler=fake_analysis,
        )
        # No-op remaining phases
        for i in [1, 3, 4, 5, 6]:
            phase_name = pipeline._phases[i].name

            async def noop(sid, n=phase_name):
                from nightwatch.types.orchestration import PhaseResult

                return PhaseResult(phase=n, success=True)

            pipeline._phases[i] = Phase(name=phase_name, custom_handler=noop)

        report = asyncio.run(pipeline.execute(since="1h"))
        assert call_count == 3  # 3 errors to analyze


# ---------------------------------------------------------------------------
# Feature flag tests
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    def _make_args(self):
        args = MagicMock()
        args.since = None
        args.max_errors = None
        args.max_issues = None
        args.dry_run = False
        args.verbose = False
        args.model = None
        args.agent = "base-analyzer"
        return args

    def test_feature_flag_off_uses_run_v1(self):
        """run_v2 not called when pipeline_v2=False."""
        mock_settings = MagicMock()
        mock_settings.nightwatch_pipeline_v2 = False

        with patch("nightwatch.config.get_settings", return_value=mock_settings):
            with patch("nightwatch.runner.run") as mock_run:
                mock_run.return_value = MagicMock()
                from nightwatch.__main__ import _run

                _run(self._make_args())
                mock_run.assert_called_once()

    def test_feature_flag_on_uses_run_v2(self):
        """run_v2 called when pipeline_v2=True."""
        mock_settings = MagicMock()
        mock_settings.nightwatch_pipeline_v2 = True

        with patch("nightwatch.config.get_settings", return_value=mock_settings):
            with patch("nightwatch.runner.run_v2") as mock_run_v2:
                mock_run_v2.return_value = MagicMock()
                from nightwatch.__main__ import _run

                _run(self._make_args())
                mock_run_v2.assert_called_once()


# ---------------------------------------------------------------------------
# Agent phase execution tests
# ---------------------------------------------------------------------------


class TestAgentPhaseExecution:
    """Test _run_agent_phase with mocked agent registry."""

    def test_run_agent_phase_creates_and_runs_agents(self):
        """Agent phase creates agents from registry and runs them."""
        pipeline = _make_pipeline()
        session_id = "test-session"
        pipeline.state_manager.initialize_state(session_id)
        pipeline.state_manager.update_state(
            session_id,
            metadata={"traces_map": {}, "total_errors_found": 0, "errors_filtered": 0},
        )

        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(
            return_value=AgentResult(success=True, data=["pattern1"])
        )

        with patch("nightwatch.agents.registry.create_agent", return_value=mock_agent):
            phase_def = Phase(
                name=ExecutionPhase.SYNTHESIS,
                agent_types=[AgentType.PATTERN_DETECTOR],
            )

            result = asyncio.run(pipeline._run_agent_phase(phase_def, session_id))
            assert result.success is True
            mock_agent.initialize.assert_called_once()
            mock_agent.execute.assert_called_once()
            mock_agent.cleanup.assert_called_once()

    def test_run_agent_phase_per_error(self):
        """Per-error phase runs agent once per error and collects results."""
        pipeline = _make_pipeline()
        session_id = "test-session"
        pipeline.state_manager.initialize_state(session_id)

        errors = [MagicMock(), MagicMock()]
        pipeline.state_manager.update_state(
            session_id,
            errors_data=errors,
            metadata={"traces_map": {}, "total_errors_found": 2, "errors_filtered": 0},
        )

        fake_analysis = _make_fake_analysis()
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(
            return_value=AgentResult(success=True, data=fake_analysis)
        )

        with patch("nightwatch.agents.registry.create_agent", return_value=mock_agent):
            phase_def = Phase(
                name=ExecutionPhase.ANALYSIS,
                agent_types=[AgentType.ANALYZER],
                per_error=True,
            )

            result = asyncio.run(pipeline._run_agent_phase(phase_def, session_id))
            assert result.success is True
            # Called once per error
            assert mock_agent.execute.call_count == 2

            # Check analyses were stored
            state = pipeline.state_manager.get_state(session_id)
            assert len(state.analyses_data) == 2

    def test_execute_phase_handles_exception(self):
        """_execute_phase returns failure PhaseResult on exception."""
        pipeline = _make_pipeline()

        async def failing_handler(session_id):
            raise ValueError("Something broke")

        phase_def = Phase(
            name=ExecutionPhase.ENRICHMENT,
            custom_handler=failing_handler,
        )

        result = asyncio.run(pipeline._execute_phase(phase_def, "test-session"))
        assert result.success is False
        assert "Something broke" in result.error_message
        assert result.phase == ExecutionPhase.ENRICHMENT


# ---------------------------------------------------------------------------
# State and metadata storage tests
# ---------------------------------------------------------------------------


class TestStateStorage:
    """Test _build_agent_state and _store_agent_result."""

    def test_store_agent_result_patterns(self):
        """Patterns from SYNTHESIS are stored in metadata."""
        pipeline = _make_pipeline()
        session_id = "test-session"
        pipeline.state_manager.initialize_state(session_id)
        pipeline.state_manager.update_state(session_id, metadata={})

        patterns = [MagicMock(title="TestPattern")]
        result = AgentResult(success=True, data=patterns)

        pipeline._store_agent_result(
            session_id, ExecutionPhase.SYNTHESIS, AgentType.PATTERN_DETECTOR, result
        )

        state = pipeline.state_manager.get_state(session_id)
        assert state.metadata["patterns"] == patterns

    def test_store_agent_result_noop_on_failure(self):
        """Failed results are not stored."""
        pipeline = _make_pipeline()
        session_id = "test-session"
        pipeline.state_manager.initialize_state(session_id)
        pipeline.state_manager.update_state(session_id, metadata={})

        result = AgentResult(success=False, error_message="failed")

        pipeline._store_agent_result(
            session_id, ExecutionPhase.SYNTHESIS, AgentType.PATTERN_DETECTOR, result
        )

        state = pipeline.state_manager.get_state(session_id)
        assert "patterns" not in state.metadata

    def test_store_agent_result_noop_on_none_data(self):
        """Results with None data are not stored."""
        pipeline = _make_pipeline()
        session_id = "test-session"
        pipeline.state_manager.initialize_state(session_id)
        pipeline.state_manager.update_state(session_id, metadata={})

        result = AgentResult(success=True, data=None)

        pipeline._store_agent_result(
            session_id, ExecutionPhase.SYNTHESIS, AgentType.PATTERN_DETECTOR, result
        )

        state = pipeline.state_manager.get_state(session_id)
        assert "patterns" not in state.metadata

    def test_build_agent_state_for_analysis(self):
        """Agent state for ANALYSIS phase includes error and traces."""
        pipeline = _make_pipeline()
        pipeline._run_kwargs = {
            "github_client": MagicMock(),
            "newrelic_client": MagicMock(),
            "run_context": MagicMock(),
            "agent_name": "test-agent",
        }

        session_id = "test-session"
        pipeline.state_manager.initialize_state(session_id)

        error_data = MagicMock()
        traces_map = {id(error_data): [MagicMock()]}
        pipeline.state_manager.update_state(
            session_id, metadata={"traces_map": traces_map}
        )

        agent_state = pipeline._build_agent_state(
            ExecutionPhase.ANALYSIS, AgentType.ANALYZER, session_id, error_data=error_data
        )

        assert agent_state["error"] is error_data
        assert agent_state["traces"] == traces_map[id(error_data)]
        assert agent_state["agent_name"] == "test-agent"

    def test_build_agent_state_for_synthesis(self):
        """Agent state for SYNTHESIS includes analyses."""
        pipeline = _make_pipeline()
        session_id = "test-session"
        pipeline.state_manager.initialize_state(session_id)

        analyses = [_make_fake_analysis(), _make_fake_analysis()]
        pipeline.state_manager.update_state(
            session_id, analyses_data=analyses, metadata={}
        )

        agent_state = pipeline._build_agent_state(
            ExecutionPhase.SYNTHESIS, AgentType.PATTERN_DETECTOR, session_id
        )

        assert agent_state["analyses"] == analyses

    def test_store_reporter_result(self):
        """Reporter results set report_sent flag."""
        pipeline = _make_pipeline()
        session_id = "test-session"
        pipeline.state_manager.initialize_state(session_id)
        pipeline.state_manager.update_state(session_id, metadata={})

        result = AgentResult(success=True, data={"slack_sent": True})

        pipeline._store_agent_result(
            session_id, ExecutionPhase.REPORTING, AgentType.REPORTER, result
        )

        state = pipeline.state_manager.get_state(session_id)
        assert state.metadata["report_sent"] is True

    def test_store_validator_result(self):
        """Validator results store validation data."""
        pipeline = _make_pipeline()
        session_id = "test-session"
        pipeline.state_manager.initialize_state(session_id)
        pipeline.state_manager.update_state(session_id, metadata={})

        validation = MagicMock(is_valid=True)
        result = AgentResult(success=True, data=validation)

        pipeline._store_agent_result(
            session_id, ExecutionPhase.ACTION, AgentType.VALIDATOR, result
        )

        state = pipeline.state_manager.get_state(session_id)
        assert state.metadata["validation_result"] == validation
