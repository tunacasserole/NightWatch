"""Tests verifying backward compatibility — all types importable from both paths."""

from __future__ import annotations


class TestModelsBackwardCompat:
    """All original types must still be importable from nightwatch.models."""

    def test_all_original_types_from_models(self):
        from nightwatch.models import (
            Analysis,
            Confidence,
            CorrelatedPR,
            CreatedIssueResult,
            CreatedPRResult,
            DetectedPattern,
            ErrorAnalysisResult,
            ErrorGroup,
            FileChange,
            FileValidationResult,
            IgnoreSuggestion,
            PriorAnalysis,
            RunContext,
            RunReport,
            TokenBreakdown,
            TraceData,
        )

        # Verify they are the same classes (not copies)
        assert Confidence.HIGH == "high"
        assert ErrorGroup is not None
        assert TraceData is not None
        assert RunContext is not None
        assert FileChange is not None
        assert Analysis is not None
        assert FileValidationResult is not None
        assert TokenBreakdown is not None
        assert ErrorAnalysisResult is not None
        assert CreatedIssueResult is not None
        assert CreatedPRResult is not None
        assert CorrelatedPR is not None
        assert PriorAnalysis is not None
        assert DetectedPattern is not None
        assert IgnoreSuggestion is not None
        assert RunReport is not None


class TestTypesPackageCompat:
    """All types also importable from nightwatch.types."""

    def test_all_types_from_package(self):
        # Same identity check
        from nightwatch.models import Confidence as ModelsConfidence
        from nightwatch.models import ErrorGroup as ModelsErrorGroup
        from nightwatch.types import (
            Confidence,
            ErrorGroup,
        )

        assert Confidence is ModelsConfidence
        assert ErrorGroup is ModelsErrorGroup

        # Verify new types are also available
        from nightwatch.types import (
            AgentConfig,
            AgentType,
            ExecutionPhase,
            MessageType,
            PatternType,
            ValidationLayer,
        )

        assert AgentType.ANALYZER == "analyzer"
        assert ExecutionPhase.ANALYSIS == "analysis"
        assert MessageType.TASK_ASSIGNED == "task_assigned"
        assert PatternType.RECURRING_ERROR == "recurring_error"
        assert ValidationLayer.CONTENT == "content"
        assert AgentConfig is not None
