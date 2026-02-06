"""NightWatch type system — domain-segmented type definitions.

Import all types from this package:
    from nightwatch.types import ErrorGroup, Analysis, AgentConfig

Or import from specific submodules:
    from nightwatch.types.core import Confidence, PatternType
    from nightwatch.types.agents import AgentConfig, AgentResult
"""

from __future__ import annotations

# --- agents.py: multi-agent architecture ---
from nightwatch.types.agents import (
    AgentConfig,
    AgentContext,
    AgentResult,
    AgentStatus,
    AgentType,
    create_agent_context,
)

# --- analysis.py: Claude output models and analysis results ---
from nightwatch.types.analysis import (
    Analysis,
    ErrorAnalysisResult,
    FileChange,
    FileValidationResult,
    TokenBreakdown,
)

# --- core.py: enums and foundational structures ---
from nightwatch.types.core import (
    Confidence,
    ErrorGroup,
    MatchType,
    PatternType,
    RunContext,
    TraceData,
)

# --- messages.py: inter-agent messaging ---
from nightwatch.types.messages import (
    AgentMessage,
    MessagePriority,
    MessageType,
    create_message,
    is_control_message,
    is_data_message,
    is_task_message,
)

# --- orchestration.py: pipeline execution ---
from nightwatch.types.orchestration import (
    ExecutionPhase,
    PhaseResult,
    PipelineConfig,
    PipelineState,
    PipelineTimestamps,
    create_pipeline_state,
)

# --- patterns.py: pattern detection and knowledge ---
from nightwatch.types.patterns import (
    CorrelatedPR,
    DetectedPattern,
    IgnoreSuggestion,
    PriorAnalysis,
)

# --- reporting.py: run output types ---
from nightwatch.types.reporting import (
    CreatedIssueResult,
    CreatedPRResult,
    RunReport,
)

# --- validation.py: multi-layer validation ---
from nightwatch.types.validation import (
    IValidator,
    LayerResult,
    ValidationIssue,
    ValidationLayer,
    ValidationResult,
    ValidationSeverity,
)

__all__ = [
    # core
    "Confidence",
    "ErrorGroup",
    "MatchType",
    "PatternType",
    "RunContext",
    "TraceData",
    # analysis
    "Analysis",
    "ErrorAnalysisResult",
    "FileChange",
    "FileValidationResult",
    "TokenBreakdown",
    # patterns
    "CorrelatedPR",
    "DetectedPattern",
    "IgnoreSuggestion",
    "PriorAnalysis",
    # reporting
    "CreatedIssueResult",
    "CreatedPRResult",
    "RunReport",
    # agents
    "AgentConfig",
    "AgentContext",
    "AgentResult",
    "AgentStatus",
    "AgentType",
    "create_agent_context",
    # messages
    "AgentMessage",
    "MessagePriority",
    "MessageType",
    "create_message",
    "is_control_message",
    "is_data_message",
    "is_task_message",
    # orchestration
    "ExecutionPhase",
    "PhaseResult",
    "PipelineConfig",
    "PipelineState",
    "PipelineTimestamps",
    "create_pipeline_state",
    # validation
    "IValidator",
    "LayerResult",
    "ValidationIssue",
    "ValidationLayer",
    "ValidationResult",
    "ValidationSeverity",
]
