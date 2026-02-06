# Implementation Plan: Gandalf Pattern Adoption — Multi-Agent Architecture

**Proposal**: GANDALF-001
**Date**: 2026-02-05
**Estimated Effort**: 3-4 days (Phases 1-3 parallelizable, Phase 4 depends on 1-3, Phase 5 independent)

---

## Execution Order

```
Day 1 (AM):   Phase 1 — Type System Foundation
Day 1 (PM):   Phase 2 — BaseAgent + Registry (depends on Phase 1)
              Phase 5 — Layered Validation (parallel with Phase 2, depends on Phase 1)
Day 2 (AM):   Phase 3 — Message Bus + State Manager (depends on Phase 1)
Day 2 (PM):   Phase 4a — Pipeline skeleton + Phase wiring (depends on Phases 1-3)
Day 3 (AM):   Phase 4b — Pipeline integration + run_v2() + feature flag
Day 3 (PM):   Integration testing, backward compat verification, cleanup
```

**Critical path**: Phase 1 → Phase 2 → Phase 4
**Parallel track**: Phase 1 → Phase 5

---

## Phase 1: Type System Foundation

**Goal**: Split monolithic `models.py` into domain-segmented `nightwatch/types/` package. Zero behavior change — pure structural refactor with re-export shim.

### Task 1.1: Create directory structure

```bash
mkdir -p nightwatch/types
```

### Task 1.2: Create `nightwatch/types/core.py` — base types shared across domains

Move from `models.py`:
- `Confidence` (StrEnum)
- `ErrorGroup` (dataclass)
- `TraceData` (dataclass)
- `RunContext` (dataclass with methods)

Add new enums to replace stringly-typed fields:

```python
class PatternType(StrEnum):
    """Discriminator for DetectedPattern (replaces pattern_type: str)."""
    RECURRING_ERROR = "recurring_error"
    SYSTEMIC_ISSUE = "systemic_issue"
    TRANSIENT_NOISE = "transient_noise"

class MatchType(StrEnum):
    """Discriminator for IgnoreSuggestion (replaces match: str)."""
    CONTAINS = "contains"
    EXACT = "exact"
    PREFIX = "prefix"
```

**Estimated lines**: ~130 (mostly moved, ~15 new)

### Task 1.3: Create `nightwatch/types/analysis.py` — Claude output types

Move from `models.py`:
- `FileChange` (Pydantic BaseModel)
- `Analysis` (Pydantic BaseModel)
- `ErrorAnalysisResult` (dataclass)

Import `Confidence`, `ErrorGroup`, `TraceData` from `.core`.

**Estimated lines**: ~60 (all moved)

### Task 1.4: Create `nightwatch/types/agents.py` — agent system types

New file with types for the agent framework:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class AgentType(StrEnum):
    """Agent type discriminator. Maps to concrete agent classes."""
    ANALYZER = "analyzer"
    RESEARCHER = "researcher"
    PATTERN_DETECTOR = "pattern_detector"
    REPORTER = "reporter"
    VALIDATOR = "validator"


class AgentStatus(StrEnum):
    """Agent lifecycle status."""
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentConfig:
    """Configuration for a NightWatch agent.

    Can be loaded from Markdown+YAML definitions or constructed directly.
    Preserves backward compat with existing nightwatch/agents.py AgentConfig.
    """
    name: str
    system_prompt: str = ""
    model: str = "claude-sonnet-4-5-20250929"
    thinking_budget: int = 8000
    max_tokens: int = 16384
    max_iterations: int = 15
    timeout_seconds: int = 300
    retries: int = 1
    enabled: bool = True
    tools: list[str] = field(
        default_factory=lambda: [
            "read_file", "search_code", "list_directory", "get_error_traces",
        ]
    )
    description: str = ""


@dataclass
class AgentResult(Generic[T]):
    """Generic result wrapper for any agent execution.

    Adopted from Gandalf's AgentResult<T> pattern — wraps domain-specific
    output with metadata (confidence, timing, suggestions, errors).
    """
    success: bool
    data: T | None = None
    confidence: float = 0.0
    execution_time_ms: float = 0.0
    error_message: str | None = None
    error_code: str | None = None
    recoverable: bool = True
    suggestions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentContext:
    """Execution context passed to every agent.

    Contains session identity, pipeline state reference, and
    shared data from prior phases.
    """
    session_id: str
    run_id: str
    agent_state: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False


def create_agent_context(session_id: str, run_id: str, **kwargs: Any) -> AgentContext:
    """Factory for AgentContext with sensible defaults."""
    return AgentContext(session_id=session_id, run_id=run_id, **kwargs)
```

**Estimated lines**: ~100 (all new)

### Task 1.5: Create `nightwatch/types/messages.py` — inter-agent communication

New file with typed message envelope:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any, Generic, TypeVar

from nightwatch.types.agents import AgentType

T = TypeVar("T")


class MessageType(StrEnum):
    """Message type discriminator for routing and filtering."""
    # Task lifecycle
    TASK_ASSIGNED = "task_assigned"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    # Data flow
    ERRORS_READY = "errors_ready"
    TRACES_READY = "traces_ready"
    ANALYSIS_READY = "analysis_ready"
    PATTERNS_READY = "patterns_ready"
    VALIDATION_COMPLETE = "validation_complete"
    # Control
    PHASE_COMPLETE = "phase_complete"
    ITERATION_NEEDED = "iteration_needed"


class MessagePriority(IntEnum):
    """Priority for message ordering. Lower value = higher priority."""
    HIGH = 0
    MEDIUM = 1
    LOW = 2


@dataclass
class AgentMessage(Generic[T]):
    """Typed message envelope for inter-agent communication.

    Adopted from Gandalf's AgentMessage<T> pattern with single interface
    (fixes Gandalf's dual IMessageBus problem).
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    from_agent: AgentType | None = None
    to_agent: AgentType | None = None  # None = broadcast
    type: MessageType = MessageType.TASK_ASSIGNED
    payload: T = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    priority: MessagePriority = MessagePriority.MEDIUM
    session_id: str = ""


# --- Classification helpers (from Gandalf) ---

_TASK_MESSAGES = frozenset({
    MessageType.TASK_ASSIGNED, MessageType.TASK_STARTED,
    MessageType.TASK_COMPLETED, MessageType.TASK_FAILED,
})
_DATA_MESSAGES = frozenset({
    MessageType.ERRORS_READY, MessageType.TRACES_READY,
    MessageType.ANALYSIS_READY, MessageType.PATTERNS_READY,
    MessageType.VALIDATION_COMPLETE,
})
_CONTROL_MESSAGES = frozenset({
    MessageType.PHASE_COMPLETE, MessageType.ITERATION_NEEDED,
})


def is_task_message(msg_type: MessageType) -> bool:
    return msg_type in _TASK_MESSAGES

def is_data_message(msg_type: MessageType) -> bool:
    return msg_type in _DATA_MESSAGES

def is_control_message(msg_type: MessageType) -> bool:
    return msg_type in _CONTROL_MESSAGES


# --- Factory helpers ---

def create_message(
    msg_type: MessageType,
    payload: Any = None,
    from_agent: AgentType | None = None,
    to_agent: AgentType | None = None,
    session_id: str = "",
    priority: MessagePriority = MessagePriority.MEDIUM,
) -> AgentMessage:
    """Factory for AgentMessage with sensible defaults."""
    return AgentMessage(
        from_agent=from_agent,
        to_agent=to_agent,
        type=msg_type,
        payload=payload,
        session_id=session_id,
        priority=priority,
    )
```

**Estimated lines**: ~110 (all new)

### Task 1.6: Create `nightwatch/types/orchestration.py` — pipeline types

New file with pipeline and phase types:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from nightwatch.types.agents import AgentResult, AgentType


class ExecutionPhase(StrEnum):
    """Pipeline execution phases."""
    INGESTION = "ingestion"
    ENRICHMENT = "enrichment"
    ANALYSIS = "analysis"
    SYNTHESIS = "synthesis"
    REPORTING = "reporting"
    ACTION = "action"
    LEARNING = "learning"
    COMPLETE = "complete"


class PipelineTimestamps(BaseModel, frozen=True):
    """Immutable timestamp tracking for pipeline execution."""
    started: datetime
    phase_started: datetime | None = None
    last_updated: datetime | None = None
    completed: datetime | None = None


class PipelineState(BaseModel, frozen=True):
    """Immutable pipeline state snapshot.

    Adopted from Gandalf's AgentState but using frozen Pydantic models
    instead of deep-clone dance. Create new instances via model_copy(update={}).
    """
    session_id: str
    current_phase: ExecutionPhase = ExecutionPhase.INGESTION
    iteration_count: int = 0
    agent_results: dict[str, Any] = {}  # AgentType -> AgentResult (serialized)
    timestamps: PipelineTimestamps = PipelineTimestamps(started=datetime.now(UTC))
    errors_data: list[Any] = []  # ErrorGroup list (set during INGESTION)
    analyses_data: list[Any] = []  # ErrorAnalysisResult list (set during ANALYSIS)
    metadata: dict[str, Any] = {}


@dataclass
class PhaseResult:
    """Result of executing a single pipeline phase."""
    phase: ExecutionPhase
    success: bool
    agent_results: dict[AgentType, AgentResult] = field(default_factory=dict)
    execution_time_ms: float = 0.0
    error_message: str | None = None


@dataclass
class PipelineConfig:
    """Configuration for pipeline execution."""
    max_iterations: int = 2
    phase_timeouts: dict[ExecutionPhase, int] = field(default_factory=lambda: {
        ExecutionPhase.INGESTION: 60,
        ExecutionPhase.ENRICHMENT: 120,
        ExecutionPhase.ANALYSIS: 300,
        ExecutionPhase.SYNTHESIS: 60,
        ExecutionPhase.REPORTING: 60,
        ExecutionPhase.ACTION: 120,
        ExecutionPhase.LEARNING: 60,
    })
    enable_fallback: bool = True
    dry_run: bool = False


def create_pipeline_state(session_id: str) -> PipelineState:
    """Factory for initial pipeline state."""
    return PipelineState(
        session_id=session_id,
        timestamps=PipelineTimestamps(started=datetime.now(UTC)),
    )
```

**Estimated lines**: ~100 (all new)

### Task 1.7: Create `nightwatch/types/validation.py` — validation layer types

New file:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationLayer(StrEnum):
    PATH_SAFETY = "path_safety"
    CONTENT = "content"
    SYNTAX = "syntax"
    SEMANTIC = "semantic"
    QUALITY = "quality"


@dataclass
class ValidationIssue:
    """A single validation finding."""
    layer: ValidationLayer
    severity: ValidationSeverity
    message: str
    file_path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class LayerResult:
    """Result from a single validation layer."""
    layer: ValidationLayer
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Aggregated result across all validation layers."""
    valid: bool
    layers: list[LayerResult] = field(default_factory=list)
    blocking_errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)


class IValidator(Protocol):
    """Protocol for validation layers. Adopted from Gandalf's stateless validator pattern."""

    def validate(
        self,
        file_changes: list[Any],
        context: dict[str, Any] | None = None,
    ) -> LayerResult: ...
```

**Estimated lines**: ~70 (all new)

### Task 1.8: Create `nightwatch/types/reporting.py` — output types

Move from `models.py`:
- `CreatedIssueResult` (dataclass)
- `CreatedPRResult` (dataclass)
- `RunReport` (dataclass with properties)

Import from `.core`, `.analysis`.

**Estimated lines**: ~60 (all moved)

### Task 1.9: Create `nightwatch/types/patterns.py` — pattern types

Move from `models.py`:
- `DetectedPattern` (dataclass) — update `pattern_type: str` to `pattern_type: PatternType`
- `IgnoreSuggestion` (dataclass) — update `match: str` to `match: MatchType`
- `CorrelatedPR` (dataclass)
- `PriorAnalysis` (dataclass)

Import `PatternType`, `MatchType` from `.core`.

**Estimated lines**: ~55 (mostly moved, 2 field type changes)

### Task 1.10: Create `nightwatch/types/__init__.py` — backward compat re-exports

```python
"""NightWatch type system — domain-segmented type modules.

All types previously in models.py are re-exported here for backward compatibility.
New code should import from specific submodules.
"""

# Core types
from nightwatch.types.core import (
    Confidence,
    ErrorGroup,
    MatchType,
    PatternType,
    RunContext,
    TraceData,
)

# Analysis types
from nightwatch.types.analysis import Analysis, ErrorAnalysisResult, FileChange

# Agent types
from nightwatch.types.agents import (
    AgentConfig,
    AgentContext,
    AgentResult,
    AgentStatus,
    AgentType,
    create_agent_context,
)

# Message types
from nightwatch.types.messages import (
    AgentMessage,
    MessagePriority,
    MessageType,
    create_message,
    is_control_message,
    is_data_message,
    is_task_message,
)

# Orchestration types
from nightwatch.types.orchestration import (
    ExecutionPhase,
    PhaseResult,
    PipelineConfig,
    PipelineState,
    PipelineTimestamps,
    create_pipeline_state,
)

# Validation types
from nightwatch.types.validation import (
    IValidator,
    LayerResult,
    ValidationIssue,
    ValidationLayer,
    ValidationResult,
    ValidationSeverity,
)

# Reporting types
from nightwatch.types.reporting import CreatedIssueResult, CreatedPRResult, RunReport

# Pattern types
from nightwatch.types.patterns import (
    CorrelatedPR,
    DetectedPattern,
    IgnoreSuggestion,
    PriorAnalysis,
)

__all__ = [
    # core
    "Confidence", "ErrorGroup", "TraceData", "RunContext", "PatternType", "MatchType",
    # analysis
    "Analysis", "FileChange", "ErrorAnalysisResult",
    # agents
    "AgentType", "AgentStatus", "AgentConfig", "AgentResult", "AgentContext",
    "create_agent_context",
    # messages
    "MessageType", "MessagePriority", "AgentMessage", "create_message",
    "is_task_message", "is_data_message", "is_control_message",
    # orchestration
    "ExecutionPhase", "PipelineState", "PipelineTimestamps", "PipelineConfig",
    "PhaseResult", "create_pipeline_state",
    # validation
    "ValidationSeverity", "ValidationLayer", "ValidationIssue",
    "LayerResult", "ValidationResult", "IValidator",
    # reporting
    "RunReport", "CreatedIssueResult", "CreatedPRResult",
    # patterns
    "DetectedPattern", "IgnoreSuggestion", "CorrelatedPR", "PriorAnalysis",
]
```

**Estimated lines**: ~80

### Task 1.11: Convert `nightwatch/models.py` to re-export shim

Replace entire file with:

```python
"""Legacy re-export shim — import from nightwatch.types instead.

This module is DEPRECATED. All types have moved to nightwatch/types/.
This file exists for backward compatibility and will be removed in a future version.
"""

# Re-export everything from the new types package
from nightwatch.types.core import *       # noqa: F401, F403
from nightwatch.types.analysis import *   # noqa: F401, F403
from nightwatch.types.reporting import *  # noqa: F401, F403
from nightwatch.types.patterns import *   # noqa: F401, F403
```

**Estimated lines**: ~10

### Task 1.12: Write `tests/types/test_core.py`

```
mkdir -p tests/types
touch tests/types/__init__.py
```

| Test | What It Validates |
|------|-------------------|
| `test_confidence_enum_values` | HIGH, MEDIUM, LOW string values |
| `test_pattern_type_enum_values` | All 3 values exist and are strings |
| `test_match_type_enum_values` | CONTAINS, EXACT, PREFIX |
| `test_error_group_defaults` | score=0.0, entity_guid=None |
| `test_run_context_to_prompt_section` | Non-empty output with entries, empty with no entries |
| `test_run_context_truncation` | Output respects max_chars |
| `test_run_context_record_analysis` | Appends to errors_analyzed |
| `test_run_context_record_file` | Stores in files_examined with truncated summary |

**Estimated lines**: ~80

### Task 1.13: Write `tests/types/test_agents.py`

| Test | What It Validates |
|------|-------------------|
| `test_agent_type_enum_values` | All 5 agent types |
| `test_agent_status_enum_values` | All 5 statuses |
| `test_agent_config_defaults` | model, thinking_budget, max_tokens, etc. |
| `test_agent_result_success` | success=True, data populated |
| `test_agent_result_failure` | success=False, error_message set |
| `test_agent_result_generic_type` | `AgentResult[Analysis]` works with Analysis data |
| `test_create_agent_context` | Factory produces valid context |

**Estimated lines**: ~70

### Task 1.14: Write `tests/types/test_messages.py`

| Test | What It Validates |
|------|-------------------|
| `test_message_type_classification` | `is_task_message`, `is_data_message`, `is_control_message` |
| `test_message_priority_ordering` | HIGH < MEDIUM < LOW |
| `test_agent_message_defaults` | uuid generated, timestamp set, priority=MEDIUM |
| `test_agent_message_generic_payload` | Typed payloads work |
| `test_create_message_factory` | Factory produces correct message |
| `test_broadcast_message_no_to_agent` | to_agent=None for broadcasts |

**Estimated lines**: ~70

### Task 1.15: Verify all existing tests still pass

```bash
uv run ruff check nightwatch/ tests/
uv run ruff format nightwatch/ tests/
uv run pytest tests/ -v
```

All imports via `from nightwatch.models import X` must continue to work through the re-export shim.

### Validation Criteria — Phase 1

- [ ] Every type previously in `models.py` is accessible via `from nightwatch.models import X`
- [ ] Every type is also accessible via `from nightwatch.types import X`
- [ ] Every type is accessible via its specific module: `from nightwatch.types.core import Confidence`
- [ ] New enums (`PatternType`, `MatchType`) replace string literals
- [ ] Generic `AgentResult[T]` works with type checking
- [ ] All 12 existing test files pass without modification
- [ ] `ruff check` and `ruff format --check` pass
- [ ] Zero circular imports

---

## Phase 2: BaseAgent Abstract Class & Registry

**Goal**: Create the agent infrastructure — abstract base class with lifecycle, registry with decorator, and 5 concrete agents wrapping existing functions.

### Task 2.1: Create `nightwatch/agents/base.py` — abstract base agent

```python
"""Abstract base agent with lifecycle management.

Adopted from Gandalf's BaseAgent pattern (Template Method with lifecycle).
Key adaptations:
- Python ABC instead of TypeScript abstract class
- async execute() for future parallelization
- copy.deepcopy() instead of JSON.parse/stringify
- Integrated with Python logging instead of custom logActivity
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable

from nightwatch.types.agents import AgentConfig, AgentContext, AgentResult, AgentStatus, AgentType
from nightwatch.types.messages import AgentMessage, MessageType, create_message

logger = logging.getLogger("nightwatch.agents")


class BaseAgent(ABC):
    """Abstract base agent with lifecycle management."""

    agent_type: AgentType  # Must be set by subclass

    def __init__(self, config: AgentConfig | None = None):
        self._config = config or AgentConfig(name=self.__class__.__name__)
        self._status = AgentStatus.IDLE
        self._message_bus: Any | None = None  # Set during initialize()
        self._subscriptions: list[str] = []

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def status(self) -> AgentStatus:
        return self._status

    # --- Lifecycle (from Gandalf BaseAgent) ---

    def initialize(self, message_bus: Any | None = None) -> None:
        """Initialize agent with optional message bus reference."""
        self._message_bus = message_bus
        self._status = AgentStatus.IDLE
        logger.debug(f"[{self.name}] initialized")

    @abstractmethod
    async def execute(self, context: AgentContext) -> AgentResult:
        """Execute agent's core logic. Must be implemented by subclasses."""
        ...

    def cleanup(self) -> None:
        """Clean up resources. Unsubscribe from bus, reset state."""
        for sub_id in self._subscriptions:
            if self._message_bus:
                self._message_bus.unsubscribe(sub_id)
        self._subscriptions.clear()
        self._status = AgentStatus.IDLE
        logger.debug(f"[{self.name}] cleaned up")

    # --- Execution wrapper (from Gandalf's executeWithTimeout) ---

    async def execute_with_timeout(
        self,
        context: AgentContext,
        operation: Callable,
    ) -> AgentResult:
        """Run operation with timeout and structured error handling."""
        self._status = AgentStatus.RUNNING
        start = time.monotonic()

        try:
            result = await asyncio.wait_for(
                operation(),
                timeout=self._config.timeout_seconds,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            self._status = AgentStatus.COMPLETED

            if isinstance(result, AgentResult):
                result.execution_time_ms = elapsed_ms
                return result

            return AgentResult(
                success=True,
                data=result,
                execution_time_ms=elapsed_ms,
            )

        except asyncio.TimeoutError:
            elapsed_ms = (time.monotonic() - start) * 1000
            self._status = AgentStatus.FAILED
            logger.warning(f"[{self.name}] timed out after {elapsed_ms:.0f}ms")
            return AgentResult(
                success=False,
                error_message=f"Agent {self.name} timed out after {self._config.timeout_seconds}s",
                error_code="TIMEOUT",
                execution_time_ms=elapsed_ms,
                recoverable=True,
            )

        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            self._status = AgentStatus.FAILED
            logger.error(f"[{self.name}] failed: {e}")
            return AgentResult(
                success=False,
                error_message=str(e),
                error_code="EXECUTION_ERROR",
                execution_time_ms=elapsed_ms,
                recoverable=True,
            )

    # --- Messaging helpers (from Gandalf) ---

    def send_message(
        self,
        msg_type: MessageType,
        payload: Any = None,
        to_agent: AgentType | None = None,
    ) -> None:
        """Publish a message to the bus."""
        if not self._message_bus:
            return
        msg = create_message(
            msg_type=msg_type,
            payload=payload,
            from_agent=self.agent_type,
            to_agent=to_agent,
        )
        self._message_bus.publish(msg)
```

**Estimated lines**: ~130

### Task 2.2: Create `nightwatch/agents/registry.py` — decorator-based registry

```python
"""Agent registry with @register_agent decorator.

Improvement over Gandalf's singleton pattern — uses a module-level dict
with a Pythonic decorator, and is actually used by the pipeline (Gandalf's
registry existed but wasn't used by its orchestrator).
"""

from __future__ import annotations

import logging
from typing import Any

from nightwatch.types.agents import AgentType

logger = logging.getLogger("nightwatch.agents")

# Module-level registry: AgentType -> agent class
_REGISTRY: dict[AgentType, type] = {}


def register_agent(agent_type: AgentType):
    """Decorator to register an agent class in the global registry."""
    def decorator(cls):
        if agent_type in _REGISTRY:
            logger.warning(
                f"Overwriting agent registration for {agent_type}: "
                f"{_REGISTRY[agent_type].__name__} -> {cls.__name__}"
            )
        _REGISTRY[agent_type] = cls
        cls.agent_type = agent_type
        return cls
    return decorator


def get_agent_class(agent_type: AgentType) -> type:
    """Get registered agent class by type. Raises KeyError if not found."""
    if agent_type not in _REGISTRY:
        raise KeyError(f"No agent registered for type: {agent_type}")
    return _REGISTRY[agent_type]


def create_agent(agent_type: AgentType, **kwargs: Any):
    """Factory: instantiate a registered agent."""
    cls = get_agent_class(agent_type)
    return cls(**kwargs)


def list_registered() -> dict[AgentType, type]:
    """Return copy of the registry."""
    return dict(_REGISTRY)


def clear_registry() -> None:
    """Clear all registrations. For testing only."""
    _REGISTRY.clear()
```

**Estimated lines**: ~55

### Task 2.3: Create `nightwatch/agents/error_analyzer.py` — AnalyzerAgent

Wraps existing `analyzer.py:analyze_error()`:

```python
"""AnalyzerAgent — wraps the existing Claude agentic analysis loop.

This agent encapsulates the entire analyze_error() flow from analyzer.py
as a BaseAgent subclass. The internal implementation is unchanged — this
is a structural wrapper, not a rewrite.
"""

from __future__ import annotations

from nightwatch.agents.base import BaseAgent
from nightwatch.agents.registry import register_agent
from nightwatch.types.agents import AgentContext, AgentResult, AgentType


@register_agent(AgentType.ANALYZER)
class AnalyzerAgent(BaseAgent):
    """Wraps analyzer.py:analyze_error() as an agent."""

    async def execute(self, context: AgentContext) -> AgentResult:
        async def _run():
            from nightwatch.analyzer import analyze_error

            # Extract inputs from agent_state (set by pipeline)
            state = context.agent_state
            error = state["error"]
            traces = state["traces"]
            github_client = state["github_client"]
            newrelic_client = state["newrelic_client"]
            run_context = state.get("run_context")
            prior_analyses = state.get("prior_analyses")
            research_context = state.get("research_context")
            agent_name = state.get("agent_name", "base-analyzer")
            prior_context = state.get("prior_context")

            result = analyze_error(
                error=error,
                traces=traces,
                github_client=github_client,
                newrelic_client=newrelic_client,
                run_context=run_context,
                prior_analyses=prior_analyses,
                research_context=research_context,
                agent_name=agent_name,
                prior_context=prior_context,
            )

            return AgentResult(
                success=True,
                data=result,
                confidence=_confidence_to_float(result.analysis.confidence),
            )

        return await self.execute_with_timeout(context, _run)


def _confidence_to_float(confidence) -> float:
    """Convert Confidence enum to float for AgentResult."""
    mapping = {"high": 0.9, "medium": 0.6, "low": 0.3}
    return mapping.get(str(confidence).lower(), 0.5)
```

**Estimated lines**: ~55

### Task 2.4: Create remaining agent wrappers

Each follows the same pattern as AnalyzerAgent. Thin wrappers around existing functions:

**`nightwatch/agents/researcher.py`** — wraps `research.py:research_error()`

```python
@register_agent(AgentType.RESEARCHER)
class ResearcherAgent(BaseAgent):
    async def execute(self, context: AgentContext) -> AgentResult:
        async def _run():
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
```

**Estimated lines**: ~25

**`nightwatch/agents/pattern_detector.py`** — wraps `patterns.py:detect_patterns_with_knowledge()`

**Estimated lines**: ~30

**`nightwatch/agents/reporter.py`** — wraps `slack.py:send_run_report()` + `github.py` issue creation

**Estimated lines**: ~40

**`nightwatch/agents/validator.py`** — wraps `validation.py:validate_file_changes()`

**Estimated lines**: ~30

### Task 2.5: Move existing agent definitions

```bash
mv nightwatch/agents nightwatch/agents_old_dir  # Backup existing agents/ dir with .md files
# ... restructure ...
mkdir -p nightwatch/agents/definitions
mv nightwatch/agents_old_dir/base-analyzer.md nightwatch/agents/definitions/
```

Update `nightwatch/agents/__init__.py` to re-export `load_agent`, `list_agents`, `AgentConfig` from old `agents.py` for backward compat.

### Task 2.6: Convert `nightwatch/agents.py` (module) to `nightwatch/agents/` (package)

The tricky migration: `nightwatch/agents.py` (file) becomes `nightwatch/agents/` (package).

1. Rename `nightwatch/agents.py` → `nightwatch/agents/_legacy.py`
2. Create `nightwatch/agents/__init__.py` that re-exports from `_legacy.py`:

```python
"""NightWatch agent system.

Re-exports legacy API for backward compatibility.
New code should use: from nightwatch.agents.base import BaseAgent
"""
from nightwatch.agents._legacy import AgentConfig, list_agents, load_agent

__all__ = ["AgentConfig", "load_agent", "list_agents"]
```

3. Update `_legacy.py` to look for definitions in `definitions/` subdirectory:

```python
AGENTS_DIR = Path(__file__).parent / "definitions"
```

### Task 2.7: Write `tests/agents/test_base.py`

```
mkdir -p tests/agents
touch tests/agents/__init__.py
```

| Test | What It Validates |
|------|-------------------|
| `test_base_agent_is_abstract` | Cannot instantiate BaseAgent directly |
| `test_agent_lifecycle` | initialize → execute → cleanup state transitions |
| `test_execute_with_timeout_success` | Returns AgentResult with timing |
| `test_execute_with_timeout_timeout` | Returns failure result on timeout |
| `test_execute_with_timeout_exception` | Returns failure result with error message |
| `test_agent_status_transitions` | IDLE → RUNNING → COMPLETED or FAILED |
| `test_cleanup_resets_state` | Status returns to IDLE |
| `test_send_message_without_bus` | No-op when bus is None |

**Estimated lines**: ~100

### Task 2.8: Write `tests/agents/test_registry.py`

| Test | What It Validates |
|------|-------------------|
| `test_register_agent_decorator` | Class is in registry after decoration |
| `test_get_agent_class` | Returns correct class |
| `test_get_agent_class_not_found` | Raises KeyError |
| `test_create_agent_factory` | Instantiates correct class |
| `test_overwrite_warning` | Re-registration logs warning |
| `test_list_registered` | Returns copy of registry |
| `test_clear_registry` | Registry is empty after clear |

**Estimated lines**: ~70

### Task 2.9: Write `tests/agents/test_error_analyzer.py`

| Test | What It Validates |
|------|-------------------|
| `test_analyzer_agent_registered` | AnalyzerAgent is in registry |
| `test_analyzer_agent_execute_success` | Returns AgentResult with ErrorAnalysisResult data |
| `test_analyzer_agent_execute_missing_state` | Graceful failure on missing context keys |
| `test_analyzer_agent_confidence_mapping` | HIGH→0.9, MEDIUM→0.6, LOW→0.3 |

**Estimated lines**: ~60

### Task 2.10: Verify backward compatibility

```bash
uv run ruff check nightwatch/ tests/
uv run pytest tests/ -v
```

Specifically verify:
- `from nightwatch.agents import load_agent, AgentConfig` still works
- `load_agent("base-analyzer")` finds `definitions/base-analyzer.md`
- All existing tests pass without modification

### Validation Criteria — Phase 2

- [ ] `BaseAgent` is abstract (cannot instantiate)
- [ ] `@register_agent` populates the global registry
- [ ] `create_agent(AgentType.ANALYZER)` returns `AnalyzerAgent` instance
- [ ] `AnalyzerAgent.execute()` produces same results as `analyze_error()` directly
- [ ] `from nightwatch.agents import load_agent, AgentConfig` still works
- [ ] `load_agent("base-analyzer")` loads from `nightwatch/agents/definitions/`
- [ ] All 12 existing test files pass without modification
- [ ] `ruff check` passes

---

## Phase 3: Message Bus & State Manager

**Goal**: Build the orchestration infrastructure. These components are wired by Phase 4 but are independently testable.

### Task 3.1: Create directory structure

```bash
mkdir -p nightwatch/orchestration
touch nightwatch/orchestration/__init__.py
```

### Task 3.2: Create `nightwatch/orchestration/message_bus.py`

```python
"""In-memory pub/sub message bus for inter-agent communication.

Single interface design (fixes Gandalf's dual IMessageBus problem).
Uses copy.deepcopy() for message isolation instead of JSON.parse/stringify.
"""

from __future__ import annotations

import copy
import logging
import uuid
from collections import defaultdict
from typing import Any, Callable

from nightwatch.types.agents import AgentType
from nightwatch.types.messages import AgentMessage, MessagePriority, MessageType

logger = logging.getLogger("nightwatch.orchestration.bus")

MessageHandler = Callable[[AgentMessage], None]


class MessageBus:
    """In-memory pub/sub with typed handlers."""

    def __init__(self) -> None:
        self._subscribers: dict[str, tuple[AgentType, MessageType | None, MessageHandler]] = {}
        self._messages: dict[str, list[AgentMessage]] = defaultdict(list)

    def subscribe(
        self,
        agent_type: AgentType,
        msg_type: MessageType | None,
        handler: MessageHandler,
    ) -> str:
        """Subscribe to messages. msg_type=None subscribes to all types."""
        sub_id = str(uuid.uuid4())
        self._subscribers[sub_id] = (agent_type, msg_type, handler)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription."""
        self._subscribers.pop(subscription_id, None)

    def publish(self, message: AgentMessage) -> None:
        """Publish message to targeted agent or broadcast."""
        # Store copy for history
        self._messages[message.session_id].append(copy.deepcopy(message))

        # Deliver to matching subscribers
        for sub_id, (agent_type, msg_type, handler) in self._subscribers.items():
            # Check agent targeting
            if message.to_agent is not None and message.to_agent != agent_type:
                continue
            # Check message type filter
            if msg_type is not None and message.type != msg_type:
                continue
            # Deliver deep copy to prevent mutation
            try:
                handler(copy.deepcopy(message))
            except Exception as e:
                logger.error(f"Handler error for subscription {sub_id}: {e}")

    def broadcast(self, message: AgentMessage) -> None:
        """Broadcast message to all subscribers (sets to_agent=None)."""
        msg = copy.deepcopy(message)
        msg = AgentMessage(
            id=msg.id, from_agent=msg.from_agent, to_agent=None,
            type=msg.type, payload=msg.payload, timestamp=msg.timestamp,
            priority=msg.priority, session_id=msg.session_id,
        )
        self.publish(msg)

    def get_messages(self, session_id: str) -> list[AgentMessage]:
        """Get all messages for a session (copies)."""
        return [copy.deepcopy(m) for m in self._messages.get(session_id, [])]

    def get_messages_by_priority(self, session_id: str) -> list[AgentMessage]:
        """Get messages sorted by priority (HIGH first)."""
        msgs = self.get_messages(session_id)
        return sorted(msgs, key=lambda m: m.priority)

    def clear_session(self, session_id: str) -> None:
        """Clear all stored messages for a session."""
        self._messages.pop(session_id, None)

    def clear_all(self) -> None:
        """Clear all messages and subscriptions. For testing."""
        self._subscribers.clear()
        self._messages.clear()
```

**Estimated lines**: ~90

### Task 3.3: Create `nightwatch/orchestration/state_manager.py`

```python
"""Pipeline state management with immutable Pydantic snapshots.

Improvement over Gandalf: frozen Pydantic models instead of deep-clone dance.
State updates create new instances via model_copy(update={}).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from nightwatch.types.orchestration import (
    ExecutionPhase,
    PipelineState,
    PipelineTimestamps,
    create_pipeline_state,
)

logger = logging.getLogger("nightwatch.orchestration.state")


class StateManager:
    """Manages pipeline state per session. Returns immutable snapshots."""

    def __init__(self) -> None:
        self._states: dict[str, PipelineState] = {}

    def initialize_state(self, session_id: str) -> PipelineState:
        """Create and store initial pipeline state."""
        state = create_pipeline_state(session_id)
        self._states[session_id] = state
        logger.debug(f"Initialized state for session {session_id}")
        return state

    def get_state(self, session_id: str) -> PipelineState:
        """Get current state snapshot (immutable)."""
        if session_id not in self._states:
            raise KeyError(f"No state for session: {session_id}")
        return self._states[session_id]

    def update_state(self, session_id: str, **updates) -> PipelineState:
        """Apply updates and return new frozen state."""
        current = self.get_state(session_id)

        # Handle nested timestamp updates
        if "timestamps" not in updates:
            updates["timestamps"] = current.timestamps.model_copy(
                update={"last_updated": datetime.now(UTC)}
            )

        new_state = current.model_copy(update=updates)
        self._states[session_id] = new_state
        return new_state

    def set_phase(self, session_id: str, phase: ExecutionPhase) -> PipelineState:
        """Convenience: update current phase with timestamp."""
        return self.update_state(
            session_id,
            current_phase=phase,
            timestamps=self.get_state(session_id).timestamps.model_copy(
                update={
                    "phase_started": datetime.now(UTC),
                    "last_updated": datetime.now(UTC),
                }
            ),
        )

    def increment_iteration(self, session_id: str) -> PipelineState:
        """Convenience: increment iteration count."""
        current = self.get_state(session_id)
        return self.update_state(
            session_id,
            iteration_count=current.iteration_count + 1,
        )

    def complete(self, session_id: str) -> PipelineState:
        """Mark pipeline as complete."""
        return self.update_state(
            session_id,
            current_phase=ExecutionPhase.COMPLETE,
            timestamps=self.get_state(session_id).timestamps.model_copy(
                update={
                    "completed": datetime.now(UTC),
                    "last_updated": datetime.now(UTC),
                }
            ),
        )

    def remove_state(self, session_id: str) -> None:
        """Remove state for a session. For cleanup."""
        self._states.pop(session_id, None)
```

**Estimated lines**: ~85

### Task 3.4: Write `tests/orchestration/test_message_bus.py`

```
mkdir -p tests/orchestration
touch tests/orchestration/__init__.py
```

| Test | What It Validates |
|------|-------------------|
| `test_publish_delivers_to_targeted_subscriber` | Message with to_agent reaches correct handler |
| `test_publish_skips_non_targeted_subscriber` | Other agents don't receive targeted message |
| `test_broadcast_delivers_to_all` | All subscribers receive broadcast |
| `test_subscribe_with_type_filter` | Only matching MessageType delivered |
| `test_subscribe_without_filter` | All message types delivered |
| `test_unsubscribe_stops_delivery` | Handler not called after unsubscribe |
| `test_messages_are_deep_copied` | Mutating delivered message doesn't affect stored copy |
| `test_handler_error_doesnt_propagate` | Exception in handler doesn't crash bus |
| `test_get_messages_returns_copies` | Returned messages are independent copies |
| `test_get_messages_by_priority` | HIGH messages first |
| `test_clear_session` | Messages removed for session |

**Estimated lines**: ~120

### Task 3.5: Write `tests/orchestration/test_state_manager.py`

| Test | What It Validates |
|------|-------------------|
| `test_initialize_state` | Creates state with correct session_id and phase=INGESTION |
| `test_get_state_returns_frozen_copy` | Returned state is immutable |
| `test_update_state_returns_new_instance` | Old reference unchanged, new state has updates |
| `test_set_phase` | Phase and phase_started timestamp updated |
| `test_increment_iteration` | Iteration count increases by 1 |
| `test_complete` | Phase=COMPLETE, completed timestamp set |
| `test_get_state_not_found` | Raises KeyError for unknown session |
| `test_remove_state` | State no longer accessible after removal |

**Estimated lines**: ~90

### Task 3.6: Verify

```bash
uv run ruff check nightwatch/ tests/
uv run pytest tests/ -v
```

### Validation Criteria — Phase 3

- [ ] MessageBus delivers targeted and broadcast messages correctly
- [ ] MessageBus uses `copy.deepcopy()` for isolation (not JSON serialize/deserialize)
- [ ] Handler exceptions are caught and logged, not propagated
- [ ] StateManager returns frozen Pydantic instances
- [ ] State updates create new instances (old references unchanged)
- [ ] All existing tests pass

---

## Phase 4: Pipeline Orchestrator

**Goal**: Replace `runner.py:run()` with a phase-based pipeline behind a feature flag.

### Task 4.1: Create `nightwatch/orchestration/pipeline.py`

The pipeline is the core orchestration engine. It wires agents, bus, and state together:

```python
"""Phase-based execution pipeline.

Adopted from Gandalf's AgentOrchestrator pattern with these differences:
- Phases are data-driven (config), not hardcoded in a 918-line class
- Feature-flagged alongside existing run()
- Async-ready but uses asyncio.run() wrapper for sync callers
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from nightwatch.agents.base import BaseAgent
from nightwatch.agents.registry import create_agent
from nightwatch.orchestration.message_bus import MessageBus
from nightwatch.orchestration.state_manager import StateManager
from nightwatch.types.agents import AgentContext, AgentResult, AgentType
from nightwatch.types.orchestration import (
    ExecutionPhase,
    PhaseResult,
    PipelineConfig,
    PipelineState,
)

logger = logging.getLogger("nightwatch.orchestration.pipeline")


@dataclass
class Phase:
    """A single pipeline phase definition."""
    name: ExecutionPhase
    agent_types: list[AgentType] = field(default_factory=list)
    per_error: bool = False  # Run once per error in state.errors_data
    parallel: bool = False   # Run agents in parallel (asyncio.gather)
    custom_handler: Callable | None = None  # For non-agent phases (INGESTION, LEARNING)


class Pipeline:
    """Phase-based execution pipeline with agent coordination."""

    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig()
        self.bus = MessageBus()
        self.state_manager = StateManager()
        self._agents: dict[AgentType, BaseAgent] = {}
        self._phases = self._build_phases()

    def _build_phases(self) -> list[Phase]:
        """Define pipeline phases. Mirrors implicit steps in runner.py:run()."""
        return [
            Phase(ExecutionPhase.INGESTION, custom_handler=self._run_ingestion),
            Phase(ExecutionPhase.ENRICHMENT, agent_types=[AgentType.RESEARCHER]),
            Phase(ExecutionPhase.ANALYSIS, agent_types=[AgentType.ANALYZER], per_error=True),
            Phase(ExecutionPhase.SYNTHESIS, agent_types=[AgentType.PATTERN_DETECTOR]),
            Phase(ExecutionPhase.REPORTING, agent_types=[AgentType.REPORTER]),
            Phase(ExecutionPhase.ACTION, agent_types=[AgentType.VALIDATOR, AgentType.REPORTER]),
            Phase(ExecutionPhase.LEARNING, custom_handler=self._run_learning),
        ]

    async def execute(self, **run_kwargs) -> Any:
        """Execute the full pipeline."""
        session_id = str(uuid.uuid4())
        state = self.state_manager.initialize_state(session_id)

        # Initialize agents
        self._initialize_agents()

        try:
            for phase_def in self._phases:
                state = self.state_manager.set_phase(session_id, phase_def.name)
                logger.info(f"[Pipeline] Starting phase: {phase_def.name}")

                start = time.monotonic()
                phase_result = await self._execute_phase(phase_def, session_id, run_kwargs)
                elapsed = (time.monotonic() - start) * 1000

                if not phase_result.success:
                    logger.error(f"[Pipeline] Phase {phase_def.name} failed: {phase_result.error_message}")
                    if self.config.enable_fallback:
                        return await self._fallback(run_kwargs)
                    raise RuntimeError(f"Pipeline phase {phase_def.name} failed")

                logger.info(f"[Pipeline] Phase {phase_def.name} completed in {elapsed:.0f}ms")

            self.state_manager.complete(session_id)
            return self._build_run_report(session_id)

        finally:
            self._cleanup_agents()

    async def _execute_phase(self, phase_def: Phase, session_id: str, run_kwargs: dict) -> PhaseResult:
        """Execute a single phase."""
        # Custom handler phases (INGESTION, LEARNING)
        if phase_def.custom_handler:
            return await phase_def.custom_handler(session_id, run_kwargs)

        # Agent-driven phases
        state = self.state_manager.get_state(session_id)
        results: dict[AgentType, AgentResult] = {}

        if phase_def.per_error:
            # Run agent once per error
            for error_data in state.errors_data:
                for agent_type in phase_def.agent_types:
                    agent = self._agents.get(agent_type)
                    if agent:
                        context = AgentContext(
                            session_id=session_id,
                            run_id=session_id,
                            agent_state={**run_kwargs, "error": error_data},
                        )
                        result = await agent.execute(context)
                        results[agent_type] = result
        else:
            # Run agents (sequentially or in parallel)
            for agent_type in phase_def.agent_types:
                agent = self._agents.get(agent_type)
                if agent:
                    context = AgentContext(session_id=session_id, run_id=session_id, agent_state=run_kwargs)
                    result = await agent.execute(context)
                    results[agent_type] = result

        success = all(r.success for r in results.values()) if results else True
        return PhaseResult(
            phase=phase_def.name,
            success=success,
            agent_results=results,
        )

    # ... custom handlers, fallback, report builder, init/cleanup helpers ...
```

**Note**: The full implementation will be ~250-300 lines. The custom handlers (`_run_ingestion`, `_run_learning`) encapsulate the non-agent steps from `runner.py` (NewRelic fetching, knowledge compounding).

**Estimated lines**: ~300

### Task 4.2: Add feature flag to `nightwatch/config.py`

```python
# Pipeline V2
nightwatch_pipeline_v2: bool = False
nightwatch_pipeline_fallback: bool = True
```

**Estimated lines**: +4

### Task 4.3: Add `run_v2()` to `nightwatch/runner.py`

Add at the bottom of runner.py, after existing `run()`:

```python
async def _run_v2_async(
    since: str | None = None,
    max_errors: int | None = None,
    max_issues: int | None = None,
    dry_run: bool = False,
    agent_name: str = "base-analyzer",
) -> RunReport:
    """Pipeline V2 entry point (async)."""
    from nightwatch.orchestration.pipeline import Pipeline, PipelineConfig

    config = PipelineConfig(dry_run=dry_run, enable_fallback=settings.nightwatch_pipeline_fallback)
    pipeline = Pipeline(config=config)
    return await pipeline.execute(
        since=since, max_errors=max_errors, max_issues=max_issues,
        dry_run=dry_run, agent_name=agent_name,
    )


def run_v2(**kwargs) -> RunReport:
    """Sync wrapper for Pipeline V2."""
    return asyncio.run(_run_v2_async(**kwargs))
```

### Task 4.4: Modify entry point dispatch in `nightwatch/__main__.py`

```python
# In _run() function, add dispatch logic:
settings = get_settings()
if settings.nightwatch_pipeline_v2:
    from nightwatch.runner import run_v2
    report = run_v2(since=since, max_errors=max_errors, ...)
else:
    report = run(since=since, max_errors=max_errors, ...)
```

**Estimated lines modified**: ~10

### Task 4.5: Write `tests/orchestration/test_pipeline.py`

| Test | What It Validates |
|------|-------------------|
| `test_pipeline_executes_all_phases` | All 7 phases execute in order |
| `test_pipeline_state_transitions` | State moves through INGESTION→...→COMPLETE |
| `test_pipeline_per_error_phase` | ANALYSIS phase runs agent per error |
| `test_pipeline_fallback_on_failure` | Falls back to run() when enable_fallback=True |
| `test_pipeline_raises_on_failure_no_fallback` | Raises RuntimeError when fallback disabled |
| `test_pipeline_feature_flag_off` | run_v2 not called when pipeline_v2=False |
| `test_pipeline_produces_run_report` | Output is a valid RunReport |

**Estimated lines**: ~150

### Task 4.6: Write `tests/integration/test_pipeline_e2e.py`

Full integration test with mocked clients:

| Test | What It Validates |
|------|-------------------|
| `test_pipeline_v2_matches_run_v1` | Same inputs produce equivalent RunReport |
| `test_pipeline_v2_with_dry_run` | No side effects in dry run mode |
| `test_pipeline_v2_fallback_to_v1` | On pipeline error, falls back to run() |

**Estimated lines**: ~120

### Validation Criteria — Phase 4

- [ ] Pipeline executes all 7 phases in order
- [ ] Pipeline produces a RunReport identical to `run()` for same inputs
- [ ] Feature flag `NIGHTWATCH_PIPELINE_V2=false` uses existing `run()`
- [ ] Feature flag `NIGHTWATCH_PIPELINE_V2=true` uses pipeline
- [ ] Fallback works: pipeline failure falls back to `run()`
- [ ] Per-error phase runs AnalyzerAgent once per error
- [ ] All existing tests pass (feature flag is off by default)

---

## Phase 5: Layered Validation

**Goal**: Replace `validation.py:validate_file_changes()` with composable validators following Gandalf's layered pattern.

### Task 5.1: Create directory structure

```bash
mkdir -p nightwatch/validation/layers
touch nightwatch/validation/__init__.py
touch nightwatch/validation/layers/__init__.py
```

### Task 5.2: Create `nightwatch/validation/layers/path_safety.py`

Extract from existing `validation.py`:

```python
"""Path safety validator — prevents path traversal and absolute paths.

Short-circuits the validation pipeline: if paths are unsafe, no further
validation is meaningful (adopted from Gandalf's syntax short-circuit pattern).
"""

from nightwatch.types.validation import (
    IValidator, LayerResult, ValidationIssue, ValidationLayer, ValidationSeverity,
)


class PathSafetyValidator:
    """Validates file paths are safe for PR creation."""

    def validate(self, file_changes, context=None) -> LayerResult:
        issues = []
        for change in file_changes:
            path = change.path if hasattr(change, 'path') else change.get('path', '')
            if path.startswith('/'):
                issues.append(ValidationIssue(
                    layer=ValidationLayer.PATH_SAFETY,
                    severity=ValidationSeverity.ERROR,
                    message=f"Absolute path not allowed: {path}",
                    file_path=path,
                ))
            if '..' in path:
                issues.append(ValidationIssue(
                    layer=ValidationLayer.PATH_SAFETY,
                    severity=ValidationSeverity.ERROR,
                    message=f"Path traversal not allowed: {path}",
                    file_path=path,
                ))
        return LayerResult(
            layer=ValidationLayer.PATH_SAFETY,
            passed=not any(i.severity == ValidationSeverity.ERROR for i in issues),
            issues=issues,
        )
```

**Estimated lines**: ~40

### Task 5.3: Create `nightwatch/validation/layers/content.py`

Extract from existing `validation.py`:

```python
class ContentValidator:
    """Validates file change content is present and reasonable."""

    def validate(self, file_changes, context=None) -> LayerResult:
        issues = []
        for change in file_changes:
            action = change.action if hasattr(change, 'action') else change.get('action')
            content = change.content if hasattr(change, 'content') else change.get('content')
            path = change.path if hasattr(change, 'path') else change.get('path', '')

            if action in ("modify", "create") and not (content and content.strip()):
                issues.append(ValidationIssue(
                    layer=ValidationLayer.CONTENT,
                    severity=ValidationSeverity.ERROR,
                    message=f"Empty content for {action} action: {path}",
                    file_path=path,
                ))
            if content and len(content.strip()) < 20 and action == "modify":
                issues.append(ValidationIssue(
                    layer=ValidationLayer.CONTENT,
                    severity=ValidationSeverity.WARNING,
                    message=f"Suspiciously short content ({len(content.strip())} chars): {path}",
                    file_path=path,
                ))
        return LayerResult(
            layer=ValidationLayer.CONTENT,
            passed=not any(i.severity == ValidationSeverity.ERROR for i in issues),
            issues=issues,
        )
```

**Estimated lines**: ~40

### Task 5.4: Create `nightwatch/validation/layers/syntax.py`

Extract Ruby block counting from existing `validation.py`:

**Estimated lines**: ~50

### Task 5.5: Create `nightwatch/validation/layers/semantic.py` (NEW)

New validator not in existing code:

```python
class SemanticValidator:
    """Validates file changes are semantically consistent with the analysis.

    Checks:
    - Modified files relate to the identified root cause modules
    - File changes don't contradict the analysis reasoning
    - Number of changes is proportional to the described fix scope
    """
```

**Estimated lines**: ~60

### Task 5.6: Create `nightwatch/validation/layers/quality.py` (NEW)

New validator:

```python
class QualityValidator:
    """Validates analysis quality meets thresholds for PR creation.

    Checks:
    - Confidence meets minimum threshold (default: MEDIUM)
    - File change count doesn't exceed maximum (default: 5)
    - Analysis has non-empty reasoning and root_cause
    """
```

**Estimated lines**: ~45

### Task 5.7: Create `nightwatch/validation/orchestrator.py`

```python
"""Validation orchestrator — runs layers in sequence with short-circuit.

Adopted from Gandalf's ValidationOrchestrator pattern:
- Layers run in order
- PATH_SAFETY failure short-circuits remaining layers
- Results aggregated into ValidationResult
"""

from nightwatch.types.validation import (
    LayerResult, ValidationIssue, ValidationLayer, ValidationResult, ValidationSeverity,
)
from nightwatch.validation.layers.path_safety import PathSafetyValidator
from nightwatch.validation.layers.content import ContentValidator
from nightwatch.validation.layers.syntax import SyntaxValidator
from nightwatch.validation.layers.semantic import SemanticValidator
from nightwatch.validation.layers.quality import QualityValidator


class ValidationOrchestrator:
    """Runs validation layers in sequence."""

    def __init__(self, layers=None):
        self.layers = layers or [
            PathSafetyValidator(),
            ContentValidator(),
            SyntaxValidator(),
            SemanticValidator(),
            QualityValidator(),
        ]

    def validate(self, file_changes, context=None) -> ValidationResult:
        all_layers: list[LayerResult] = []
        blocking: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []

        for validator in self.layers:
            result = validator.validate(file_changes, context)
            all_layers.append(result)

            for issue in result.issues:
                if issue.severity == ValidationSeverity.ERROR:
                    blocking.append(issue)
                elif issue.severity == ValidationSeverity.WARNING:
                    warnings.append(issue)

            # Short-circuit on PATH_SAFETY failure
            if result.layer == ValidationLayer.PATH_SAFETY and not result.passed:
                break

        return ValidationResult(
            valid=len(blocking) == 0,
            layers=all_layers,
            blocking_errors=blocking,
            warnings=warnings,
        )
```

**Estimated lines**: ~55

### Task 5.8: Create `nightwatch/validation/__init__.py` — backward compat

```python
"""NightWatch validation system.

Re-exports the ValidationOrchestrator as the primary interface.
Legacy validate_file_changes() still available from nightwatch.validation.
"""

from nightwatch.validation.orchestrator import ValidationOrchestrator

__all__ = ["ValidationOrchestrator"]
```

### Task 5.9: Convert `nightwatch/validation.py` (file) to `nightwatch/validation/` (package)

Similar to the agents migration:
1. Rename `nightwatch/validation.py` → `nightwatch/validation/_legacy.py`
2. `nightwatch/validation/__init__.py` re-exports `validate_file_changes` from `_legacy.py` for backward compat
3. Update `_legacy.py` internal imports if needed

### Task 5.10: Write tests

```
mkdir -p tests/validation/layers
touch tests/validation/__init__.py
touch tests/validation/layers/__init__.py
```

**`tests/validation/test_orchestrator.py`**:

| Test | What It Validates |
|------|-------------------|
| `test_all_layers_run_on_valid_input` | 5 LayerResults in output |
| `test_short_circuit_on_path_safety` | Only 1 LayerResult when path is absolute |
| `test_custom_layer_order` | Constructor accepts custom layer list |
| `test_blocking_errors_aggregated` | Errors from multiple layers in blocking_errors |
| `test_valid_true_when_no_errors` | All warnings → valid=True |

**`tests/validation/layers/test_path_safety.py`**:

| Test | What It Validates |
|------|-------------------|
| `test_absolute_path_fails` | `/etc/passwd` → ERROR |
| `test_path_traversal_fails` | `../../etc` → ERROR |
| `test_relative_path_passes` | `app/models/user.rb` → pass |

**`tests/validation/layers/test_syntax.py`**:

| Test | What It Validates |
|------|-------------------|
| `test_balanced_ruby_blocks` | Equal def/end → pass |
| `test_unbalanced_ruby_blocks` | Missing end → ERROR |
| `test_non_ruby_skipped` | `.py` file → pass (no Ruby check) |

**`tests/validation/layers/test_semantic.py`**:

| Test | What It Validates |
|------|-------------------|
| `test_changes_match_root_cause_modules` | Modified files in root cause path → pass |
| `test_too_many_changes_warns` | >5 file changes → WARNING |

**Total test lines**: ~200

### Validation Criteria — Phase 5

- [ ] `ValidationOrchestrator` runs all 5 layers in order
- [ ] PATH_SAFETY failure short-circuits remaining layers
- [ ] `from nightwatch.validation import validate_file_changes` still works (legacy compat)
- [ ] New `ValidationOrchestrator().validate()` produces same pass/fail as old function for same inputs
- [ ] SemanticValidator catches unrelated file changes
- [ ] QualityValidator enforces confidence thresholds
- [ ] All existing tests pass

---

## Final Integration

### Task F.1: Full backward compatibility verification

Run existing tests with both pipeline modes:

```bash
# V1 mode (default)
NIGHTWATCH_PIPELINE_V2=false uv run pytest tests/ -v

# V2 mode
NIGHTWATCH_PIPELINE_V2=true uv run pytest tests/ -v
```

### Task F.2: Verify import compatibility

Create a temporary test that imports everything the old way:

```python
# Verify all legacy imports work
from nightwatch.models import (
    Analysis, Confidence, ErrorGroup, TraceData, RunContext,
    FileChange, ErrorAnalysisResult, CreatedIssueResult,
    CreatedPRResult, RunReport, DetectedPattern, IgnoreSuggestion,
    CorrelatedPR, PriorAnalysis, FileValidationResult,
)
from nightwatch.agents import load_agent, AgentConfig, list_agents
from nightwatch.validation import validate_file_changes
```

### Task F.3: Run full lint + test suite

```bash
uv run ruff check nightwatch/ tests/
uv run ruff format nightwatch/ tests/
uv run pytest tests/ -v --tb=short
```

### Task F.4: Commit strategy

One commit per phase:

```
git commit -m "refactor(types): Phase 1 — domain-segmented type system

Split monolithic models.py into nightwatch/types/ package with 8 domain
modules. All existing imports work via re-export shim. New generic types
AgentResult[T], AgentMessage[T] for agent framework. StrEnum replaces
string literals for PatternType and MatchType.

New: nightwatch/types/ (8 modules), tests/types/ (3 test files)
Modified: nightwatch/models.py (re-export shim)"


git commit -m "feat(agents): Phase 2 — BaseAgent ABC and decorator registry

Implement Gandalf's Template Method lifecycle pattern as Python ABC.
@register_agent decorator replaces Gandalf's unused singleton registry.
5 concrete agents wrap existing functions (zero behavior change).

New: nightwatch/agents/base.py, registry.py, error_analyzer.py, researcher.py,
     pattern_detector.py, reporter.py, validator.py
Migrated: nightwatch/agents.py → nightwatch/agents/_legacy.py"


git commit -m "feat(orchestration): Phase 3 — message bus and state manager

In-memory pub/sub bus with single interface (fixes Gandalf's dual-interface
design). Frozen Pydantic state manager with immutable snapshots (fixes
Gandalf's inconsistent mutation pattern).

New: nightwatch/orchestration/message_bus.py, state_manager.py"


git commit -m "feat(pipeline): Phase 4 — phase-based execution pipeline

7-phase pipeline replacing monolithic run(). Feature-flagged via
NIGHTWATCH_PIPELINE_V2. Falls back to existing run() on failure.
Per-error analysis phase runs AnalyzerAgent per error.

New: nightwatch/orchestration/pipeline.py
Modified: nightwatch/runner.py, nightwatch/config.py, nightwatch/__main__.py"


git commit -m "refactor(validation): Phase 5 — layered validation pipeline

5 composable validators with short-circuit on path safety failure.
New SemanticValidator and QualityValidator. Adopts Gandalf's stateless
validator pattern with IValidator protocol.

New: nightwatch/validation/ (orchestrator + 5 layers)
Migrated: nightwatch/validation.py → nightwatch/validation/_legacy.py"
```

---

## Checklist

### Phase 1 — Type System Foundation
- [ ] Create `nightwatch/types/` directory
- [ ] Create `core.py` with moved types + new `PatternType`, `MatchType` enums
- [ ] Create `analysis.py` with moved types
- [ ] Create `agents.py` with new `AgentType`, `AgentStatus`, `AgentConfig`, `AgentResult[T]`
- [ ] Create `messages.py` with new `MessageType`, `AgentMessage[T]`, factories
- [ ] Create `orchestration.py` with new `ExecutionPhase`, `PipelineState`, `PhaseResult`
- [ ] Create `validation.py` with new `ValidationSeverity`, `IValidator` protocol
- [ ] Create `reporting.py` with moved types
- [ ] Create `patterns.py` with moved types + updated field types
- [ ] Create `__init__.py` with full re-exports
- [ ] Convert `models.py` to re-export shim
- [ ] Create `tests/types/test_core.py` (8 tests)
- [ ] Create `tests/types/test_agents.py` (7 tests)
- [ ] Create `tests/types/test_messages.py` (6 tests)
- [ ] `uv run ruff check && uv run pytest` — all green

### Phase 2 — BaseAgent & Registry
- [ ] Create `nightwatch/agents/base.py` — abstract base with lifecycle
- [ ] Create `nightwatch/agents/registry.py` — `@register_agent` + factory
- [ ] Create `nightwatch/agents/error_analyzer.py` — AnalyzerAgent
- [ ] Create `nightwatch/agents/researcher.py` — ResearcherAgent
- [ ] Create `nightwatch/agents/pattern_detector.py` — PatternAgent
- [ ] Create `nightwatch/agents/reporter.py` — ReporterAgent
- [ ] Create `nightwatch/agents/validator.py` — ValidatorAgent
- [ ] Migrate `agents.py` → `agents/_legacy.py` + package `__init__.py`
- [ ] Move `.md` definitions to `agents/definitions/`
- [ ] Create `tests/agents/test_base.py` (8 tests)
- [ ] Create `tests/agents/test_registry.py` (7 tests)
- [ ] Create `tests/agents/test_error_analyzer.py` (4 tests)
- [ ] Verify `from nightwatch.agents import load_agent` still works
- [ ] `uv run ruff check && uv run pytest` — all green

### Phase 3 — Message Bus & State Manager
- [ ] Create `nightwatch/orchestration/__init__.py`
- [ ] Create `nightwatch/orchestration/message_bus.py`
- [ ] Create `nightwatch/orchestration/state_manager.py`
- [ ] Create `tests/orchestration/test_message_bus.py` (11 tests)
- [ ] Create `tests/orchestration/test_state_manager.py` (8 tests)
- [ ] `uv run ruff check && uv run pytest` — all green

### Phase 4 — Pipeline Orchestrator
- [ ] Create `nightwatch/orchestration/pipeline.py`
- [ ] Add `nightwatch_pipeline_v2` + `nightwatch_pipeline_fallback` to `config.py`
- [ ] Add `run_v2()` to `runner.py`
- [ ] Add dispatch logic to `__main__.py`
- [ ] Create `tests/orchestration/test_pipeline.py` (7 tests)
- [ ] Create `tests/integration/test_pipeline_e2e.py` (3 tests)
- [ ] `uv run ruff check && uv run pytest` — all green

### Phase 5 — Layered Validation
- [ ] Create `nightwatch/validation/` package
- [ ] Create `layers/path_safety.py`
- [ ] Create `layers/content.py`
- [ ] Create `layers/syntax.py`
- [ ] Create `layers/semantic.py`
- [ ] Create `layers/quality.py`
- [ ] Create `orchestrator.py`
- [ ] Migrate `validation.py` → `validation/_legacy.py` + package `__init__.py`
- [ ] Create `tests/validation/test_orchestrator.py` (5 tests)
- [ ] Create `tests/validation/layers/test_path_safety.py` (3 tests)
- [ ] Create `tests/validation/layers/test_syntax.py` (3 tests)
- [ ] Create `tests/validation/layers/test_semantic.py` (2 tests)
- [ ] Verify `from nightwatch.validation import validate_file_changes` still works
- [ ] `uv run ruff check && uv run pytest` — all green

### Final
- [ ] Full backward compat verification (both V1 and V2 mode)
- [ ] Import compatibility test
- [ ] Full lint + test suite
- [ ] One commit per phase

---

## Cost & Performance Impact

| Metric | Current | After GANDALF-001 (V2 off) | After GANDALF-001 (V2 on) |
|--------|---------|---------------------------|--------------------------|
| Startup time | ~50ms | ~60ms (+types import) | ~80ms (+agent init) |
| Per-error analysis | ~12K tokens | ~12K tokens (unchanged) | ~12K tokens (same AnalyzerAgent) |
| Memory overhead | ~10MB | ~12MB (+type modules) | ~15MB (+bus, state, agents) |
| Test count | ~85 | ~150 (+65 new) | ~150 |
| Test suite time | ~5s | ~8s | ~8s |

**Key insight**: With V2 feature flag OFF, the only cost is the extra type modules in memory. The pipeline, agents, bus, and state manager are not loaded or instantiated.

---

## Risk Assessment

| Risk | Likelihood | Severity | Mitigation |
|------|-----------|----------|------------|
| Module-to-package migration breaks imports | Medium | High | Re-export shims + comprehensive import tests |
| Async adds complexity for sync callers | Low | Medium | `asyncio.run()` wrapper; agents can use sync internally |
| Pipeline V2 produces different results than V1 | Medium | High | Integration test comparing V1 vs V2 output |
| Phase 4 takes longer than estimated | Medium | Low | Phases 1-3+5 deliver value independently |
| Over-abstraction slows development | Low | Medium | Agents are thin wrappers; unwrap if abstraction hurts |
| Circular imports in types/ package | Low | Medium | Types depend on nothing; strict one-way dependency flow |

---

## Decision Required

- [ ] **Approve all 5 phases** (3-4 days) — Full Gandalf architecture adoption
- [ ] **Approve Phases 1-3** (2 days) — Type system + agents + infrastructure, defer pipeline
- [ ] **Approve Phase 1 only** (0.5 days) — Type system cleanup, lowest risk
- [ ] **Defer all** — Current architecture is sufficient

**Recommended**: Approve all 5 phases. Each phase is independently valuable and shippable. Phase 1 alone improves code organization. Phases 1-2 enable future multi-agent work. Phase 4 with feature flag is zero-risk to production. The total investment is 3-4 days for an architecture that will support NightWatch's next year of growth.
