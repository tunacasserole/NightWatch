# OpenSpec Proposal: GANDALF-001b — BaseAgent Abstract Class & Registry

**ID**: GANDALF-001b
**Parent**: GANDALF-001 (Gandalf Pattern Adoption)
**Status**: Proposed
**Phase**: 2 of 5
**Date**: 2026-02-05
**Scope**: Create agent infrastructure — abstract base class with lifecycle, registry with decorator, 5 concrete agent wrappers
**Dependencies**: GANDALF-001a (Type System Foundation)
**Estimated Effort**: 2-3 hours

---

## 1. Goal

Replace the config-only agent system (agents are Markdown+YAML definitions with no behavior) with a proper agent hierarchy: abstract `BaseAgent` with lifecycle management, `@register_agent` decorator for a module-level registry, and 5 concrete agents wrapping existing functions. Zero behavior change — structural wrapper, not a rewrite.

## 2. Problem

Current `nightwatch/agents.py` (133 lines) defines `AgentConfig` and functions to load Markdown agent definitions. Agents are configuration, not behavior:
- Only one agent exists (`base-analyzer.md`)
- Agent logic lives entirely in `analyzer.py._single_pass()` — monolithic function
- No lifecycle management (initialization, timeout, cleanup)
- No way to compose specialized agents
- No registry to look up agents by type

## 3. What Changes

### 3.1 New Package Structure

Migrate `nightwatch/agents.py` (file) → `nightwatch/agents/` (package):

```
nightwatch/agents/
├── __init__.py              # Re-exports load_agent, list_agents, AgentConfig for backward compat
├── _legacy.py               # Original agents.py content (renamed)
├── base.py                  # BaseAgent ABC with lifecycle
├── registry.py              # @register_agent decorator + factory
├── error_analyzer.py        # AnalyzerAgent — wraps analyzer.py:analyze_error()
├── researcher.py            # ResearcherAgent — wraps research.py:research_error()
├── pattern_detector.py      # PatternDetectorAgent — wraps patterns.py:detect_patterns_with_knowledge()
├── reporter.py              # ReporterAgent — wraps slack.py + github.py issue/PR creation
├── validator.py             # ValidatorAgent — wraps validation.py:validate_file_changes()
└── definitions/
    └── base-analyzer.md     # Existing agent definition (moved from agents/)
```

### 3.2 BaseAgent ABC (`base.py`, ~130 lines)

```python
class BaseAgent(ABC):
    agent_type: AgentType  # Set by @register_agent decorator

    def __init__(self, config: AgentConfig | None = None): ...

    # Lifecycle (from Gandalf's BaseAgent Template Method)
    def initialize(self, message_bus: Any | None = None) -> None: ...
    @abstractmethod
    async def execute(self, context: AgentContext) -> AgentResult: ...
    def cleanup(self) -> None: ...

    # Execution wrapper (from Gandalf's executeWithTimeout)
    async def execute_with_timeout(self, context, operation) -> AgentResult: ...

    # Messaging helpers
    def send_message(self, msg_type, payload, to_agent=None) -> None: ...
```

Key design decisions:
- Python ABC instead of TypeScript abstract class
- `async def execute()` for future parallelization
- `copy.deepcopy()` instead of `JSON.parse/stringify`
- Integrated with Python `logging` instead of custom `logActivity`

### 3.3 Registry (`registry.py`, ~55 lines)

```python
_REGISTRY: dict[AgentType, type] = {}

def register_agent(agent_type: AgentType):  # Decorator
def get_agent_class(agent_type: AgentType) -> type:
def create_agent(agent_type: AgentType, **kwargs) -> BaseAgent:
def list_registered() -> dict[AgentType, type]:
def clear_registry() -> None:  # Testing only
```

Improvement over Gandalf: `@register_agent` decorator is Pythonic and actually used by the pipeline (Gandalf's registry existed but its orchestrator never used it).

### 3.4 Concrete Agents (5 thin wrappers)

Each wraps an existing function with zero behavior change:

| Agent | Wraps | Lines |
|-------|-------|-------|
| `AnalyzerAgent` | `analyzer.py:analyze_error()` | ~55 |
| `ResearcherAgent` | `research.py:research_error()` | ~25 |
| `PatternDetectorAgent` | `patterns.py:detect_patterns_with_knowledge()` | ~30 |
| `ReporterAgent` | `slack.py:send_run_report()` + `github.py` issue creation | ~40 |
| `ValidatorAgent` | `validation.py:validate_file_changes()` | ~30 |

All use lazy imports (`from nightwatch.analyzer import analyze_error` inside `execute()`) to avoid circular imports.

### 3.5 Module-to-Package Migration

1. Rename `nightwatch/agents.py` → `nightwatch/agents/_legacy.py`
2. Move `nightwatch/agents/` directory (containing `base-analyzer.md`) → `nightwatch/agents/definitions/`
3. Update `_legacy.py`: `AGENTS_DIR = Path(__file__).parent / "definitions"`
4. Create `nightwatch/agents/__init__.py` that re-exports from `_legacy.py`:

```python
from nightwatch.agents._legacy import AgentConfig, list_agents, load_agent
__all__ = ["AgentConfig", "load_agent", "list_agents"]
```

## 4. What Doesn't Change

- `from nightwatch.agents import load_agent, AgentConfig` continues to work
- `load_agent("base-analyzer")` finds `definitions/base-analyzer.md`
- All existing agent definition `.md` files work unchanged
- No consumer code changes required
- `analyzer.py`, `research.py`, `patterns.py`, `validation.py`, `slack.py` unchanged

## 5. Tests

**`tests/agents/test_base.py`** (~100 lines, 8 tests):
| Test | Validates |
|------|-----------|
| `test_base_agent_is_abstract` | Cannot instantiate BaseAgent directly |
| `test_agent_lifecycle` | initialize → execute → cleanup state transitions |
| `test_execute_with_timeout_success` | Returns AgentResult with timing |
| `test_execute_with_timeout_timeout` | Returns failure result on timeout |
| `test_execute_with_timeout_exception` | Returns failure result with error message |
| `test_agent_status_transitions` | IDLE → RUNNING → COMPLETED or FAILED |
| `test_cleanup_resets_state` | Status returns to IDLE |
| `test_send_message_without_bus` | No-op when bus is None |

**`tests/agents/test_registry.py`** (~70 lines, 7 tests):
| Test | Validates |
|------|-----------|
| `test_register_agent_decorator` | Class is in registry after decoration |
| `test_get_agent_class` | Returns correct class |
| `test_get_agent_class_not_found` | Raises KeyError |
| `test_create_agent_factory` | Instantiates correct class |
| `test_overwrite_warning` | Re-registration logs warning |
| `test_list_registered` | Returns copy of registry |
| `test_clear_registry` | Registry is empty after clear |

**`tests/agents/test_error_analyzer.py`** (~60 lines, 4 tests):
| Test | Validates |
|------|-----------|
| `test_analyzer_agent_registered` | AnalyzerAgent is in registry |
| `test_analyzer_agent_execute_success` | Returns AgentResult with data |
| `test_analyzer_agent_execute_missing_state` | Graceful failure on missing context |
| `test_analyzer_agent_confidence_mapping` | HIGH→0.9, MEDIUM→0.6, LOW→0.3 |

## 6. Validation Criteria

- [ ] `BaseAgent` is abstract (cannot instantiate)
- [ ] `@register_agent` populates the global registry
- [ ] `create_agent(AgentType.ANALYZER)` returns `AnalyzerAgent` instance
- [ ] `from nightwatch.agents import load_agent, AgentConfig` still works
- [ ] `load_agent("base-analyzer")` loads from `nightwatch/agents/definitions/`
- [ ] All existing tests pass without modification
- [ ] `ruff check` passes

## 7. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Module-to-package migration breaks imports | Medium | Re-export shim + comprehensive import test |
| Circular import via lazy imports in agents | Low | All wrapped functions use lazy imports inside execute() |
| AGENTS_DIR path change breaks load_agent | Medium | Update to `definitions/` subdirectory + test |

## 8. Commit Message

```
feat(agents): add BaseAgent ABC and decorator registry

Implement Gandalf's Template Method lifecycle as Python ABC.
@register_agent decorator replaces Gandalf's unused singleton registry.
5 concrete agents wrap existing functions (zero behavior change).
Migrate agents.py → agents/ package with backward compat.

GANDALF-001b
```
