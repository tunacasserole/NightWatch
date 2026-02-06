# OpenSpec Proposal: GANDALF-001c — Message Bus & State Manager

**ID**: GANDALF-001c
**Parent**: GANDALF-001 (Gandalf Pattern Adoption)
**Status**: Proposed
**Phase**: 3 of 5
**Date**: 2026-02-05
**Scope**: Build orchestration infrastructure — in-memory message bus and immutable state manager
**Dependencies**: GANDALF-001a (Type System Foundation)
**Estimated Effort**: 1-2 hours

---

## 1. Goal

Create the orchestration infrastructure for inter-agent communication and pipeline state management. These components are independently testable and will be wired by Phase 4 (Pipeline Orchestrator).

## 2. Problem

NightWatch has no orchestration infrastructure:
- No inter-agent communication mechanism
- No pipeline state management
- `runner.py:run()` passes data between steps via local variables
- No way for agents to publish results or subscribe to events
- No immutable state snapshots for debugging or replay

## 3. What Changes

### 3.1 New Package Structure

```
nightwatch/orchestration/
├── __init__.py           # Re-exports MessageBus, StateManager
├── message_bus.py        # In-memory pub/sub (~90 lines)
└── state_manager.py      # Immutable state management (~85 lines)
```

### 3.2 MessageBus (`message_bus.py`, ~90 lines)

```python
class MessageBus:
    """In-memory pub/sub with typed handlers. Single interface."""

    def subscribe(self, agent_type, msg_type, handler) -> str:
    def unsubscribe(self, subscription_id) -> None:
    def publish(self, message: AgentMessage) -> None:
    def broadcast(self, message: AgentMessage) -> None:
    def get_messages(self, session_id) -> list[AgentMessage]:
    def get_messages_by_priority(self, session_id) -> list[AgentMessage]:
    def clear_session(self, session_id) -> None:
    def clear_all(self) -> None:
```

**Improvements over Gandalf**:
- **Single interface** — Gandalf has two incompatible `IMessageBus` interfaces; we have one
- **`copy.deepcopy()` for isolation** — Gandalf uses `JSON.parse/stringify` which loses datetime objects and type information
- **Handler error isolation** — exceptions in handlers are caught and logged, not propagated
- **No unused `processingLock`** — Gandalf defined it but never used it; we skip it entirely

### 3.3 StateManager (`state_manager.py`, ~85 lines)

```python
class StateManager:
    """Pipeline state per session. Returns immutable snapshots."""

    def initialize_state(self, session_id) -> PipelineState:
    def get_state(self, session_id) -> PipelineState:
    def update_state(self, session_id, **updates) -> PipelineState:
    def set_phase(self, session_id, phase) -> PipelineState:
    def increment_iteration(self, session_id) -> PipelineState:
    def complete(self, session_id) -> PipelineState:
    def remove_state(self, session_id) -> None:
```

**Improvements over Gandalf**:
- **Frozen Pydantic models** — Gandalf uses `JSON.parse(JSON.stringify())` deep-clone dance and inconsistently mutates internal state; we use `model_copy(update={})` on frozen Pydantic models
- **Type-safe updates** — keyword arguments instead of `Record<string, unknown>` state bag
- **Immutable by default** — state is a frozen Pydantic BaseModel, mutations create new instances

## 4. What Doesn't Change

- No existing code is modified
- No existing imports change
- These are additive modules — purely new infrastructure
- `runner.py`, `analyzer.py`, etc. remain untouched

## 5. Tests

**`tests/orchestration/test_message_bus.py`** (~120 lines, 11 tests):
| Test | Validates |
|------|-----------|
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

**`tests/orchestration/test_state_manager.py`** (~90 lines, 8 tests):
| Test | Validates |
|------|-----------|
| `test_initialize_state` | Creates state with correct session_id, phase=INGESTION |
| `test_get_state_returns_frozen` | Returned state is immutable (PipelineState is frozen) |
| `test_update_state_returns_new_instance` | Old reference unchanged, new state has updates |
| `test_set_phase` | Phase and phase_started timestamp updated |
| `test_increment_iteration` | Iteration count increases by 1 |
| `test_complete` | Phase=COMPLETE, completed timestamp set |
| `test_get_state_not_found` | Raises KeyError for unknown session |
| `test_remove_state` | State no longer accessible after removal |

## 6. Validation Criteria

- [ ] MessageBus delivers targeted and broadcast messages correctly
- [ ] MessageBus uses `copy.deepcopy()` for isolation (not JSON serialize/deserialize)
- [ ] Handler exceptions are caught and logged, not propagated
- [ ] StateManager returns frozen Pydantic instances
- [ ] State updates create new instances (old references unchanged)
- [ ] All existing tests pass unchanged
- [ ] `ruff check` passes

## 7. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Over-engineering for current single-agent use | Low | Bus is ~90 lines; cost is minimal |
| Memory growth from stored messages | Low | `clear_session()` called after pipeline completes |
| Frozen model performance overhead | Negligible | `model_copy()` is fast for small models |

## 8. Commit Message

```
feat(orchestration): add message bus and state manager

In-memory pub/sub bus with single interface (fixes Gandalf's dual-interface
design). Frozen Pydantic state manager with immutable snapshots (fixes
Gandalf's inconsistent mutation pattern). copy.deepcopy() for message
isolation instead of JSON.parse/stringify.

GANDALF-001c
```
