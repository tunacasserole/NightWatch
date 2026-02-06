"""Integration tests for Pipeline V2 (GANDALF-001d).

These tests verify:
- V2 dry-run produces no side effects
- Fallback from V2 to V1 on pipeline error
- Feature flag routing in run_v2()
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from nightwatch.orchestration.pipeline import Phase, Pipeline
from nightwatch.types.orchestration import ExecutionPhase, PipelineConfig


class TestPipelineV2DryRun:
    """Pipeline V2 produces no side effects in dry-run mode."""

    def test_dry_run_skips_learning(self):
        """Learning phase is a no-op in dry run."""
        config = PipelineConfig(dry_run=True, enable_fallback=False)
        pipeline = Pipeline(config=config)

        learning_executed = False

        async def run():
            nonlocal learning_executed
            # Replace all phases with no-ops except learning
            for i, phase_def in enumerate(pipeline._phases):
                phase_name = phase_def.name
                if phase_name == ExecutionPhase.LEARNING:
                    # Keep original learning handler (should skip in dry_run)
                    continue

                async def noop(sid, n=phase_name):
                    from nightwatch.types.orchestration import PhaseResult

                    return PhaseResult(phase=n, success=True)

                pipeline._phases[i] = Phase(name=phase_name, custom_handler=noop)

            # Mock compound_result to detect if it gets called
            with patch("nightwatch.knowledge.compound_result") as mock_compound:
                with patch("nightwatch.config.get_settings") as mock_settings:
                    settings = MagicMock()
                    settings.nightwatch_compound_enabled = True
                    mock_settings.return_value = settings

                    report = await pipeline.execute(since="1h")

                    # compound_result should NOT be called in dry_run
                    mock_compound.assert_not_called()

            return report

        report = asyncio.run(run())
        assert report is not None


class TestPipelineV2Fallback:
    """Fallback from V2 to V1 on pipeline error."""

    def test_fallback_to_v1(self):
        """On pipeline error, falls back to run()."""
        config = PipelineConfig(enable_fallback=True)
        pipeline = Pipeline(config=config)

        async def failing_ingestion(session_id):
            raise RuntimeError("NR API unavailable")

        pipeline._phases[0] = Phase(
            name=ExecutionPhase.INGESTION,
            custom_handler=failing_ingestion,
        )

        with patch("nightwatch.runner.run") as mock_v1:
            mock_v1.return_value = MagicMock()
            result = asyncio.run(pipeline.execute(since="2h", max_errors=3))
            # V1 run() should be called with pipeline-safe kwargs
            mock_v1.assert_called_once()
            call_kwargs = mock_v1.call_args[1]
            assert call_kwargs.get("since") == "2h"
            assert call_kwargs.get("max_errors") == 3

    def test_no_fallback_raises(self):
        """Without fallback, pipeline errors are raised."""
        config = PipelineConfig(enable_fallback=False)
        pipeline = Pipeline(config=config)

        async def failing_ingestion(session_id):
            raise RuntimeError("NR API unavailable")

        pipeline._phases[0] = Phase(
            name=ExecutionPhase.INGESTION,
            custom_handler=failing_ingestion,
        )

        with pytest.raises(RuntimeError, match="fallback is disabled"):
            asyncio.run(pipeline.execute())


class TestRunV2Wrapper:
    """Test the sync run_v2() wrapper."""

    def test_run_v2_calls_pipeline(self):
        """run_v2() delegates to Pipeline.execute()."""
        with patch("nightwatch.orchestration.pipeline.Pipeline") as MockPipeline:
            mock_pipeline = MagicMock()

            async def mock_execute(**kwargs):
                return MagicMock()

            mock_pipeline.execute = mock_execute
            MockPipeline.return_value = mock_pipeline

            with patch("nightwatch.runner.get_settings") as mock_settings:
                settings = MagicMock()
                settings.nightwatch_pipeline_fallback = True
                mock_settings.return_value = settings

                from nightwatch.runner import run_v2

                result = run_v2(since="1h", dry_run=True)
                assert result is not None
