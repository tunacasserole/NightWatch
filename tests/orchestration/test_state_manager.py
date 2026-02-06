"""Tests for pipeline state management."""

import pytest

from nightwatch.orchestration.state_manager import StateManager
from nightwatch.types.orchestration import ExecutionPhase


@pytest.fixture
def mgr():
    return StateManager()


def test_initialize_state(mgr):
    state = mgr.initialize_state("s1")
    assert state.session_id == "s1"
    assert state.current_phase == ExecutionPhase.INGESTION
    assert state.iteration_count == 0


def test_get_state_returns_frozen(mgr):
    mgr.initialize_state("s1")
    state = mgr.get_state("s1")
    with pytest.raises(ValueError):  # frozen model raises ValidationError
        state.iteration_count = 5


def test_update_state_returns_new_instance(mgr):
    old = mgr.initialize_state("s1")
    new = mgr.update_state("s1", iteration_count=3)
    assert old.iteration_count == 0
    assert new.iteration_count == 3
    assert old is not new


def test_set_phase(mgr):
    mgr.initialize_state("s1")
    state = mgr.set_phase("s1", ExecutionPhase.ANALYSIS)
    assert state.current_phase == ExecutionPhase.ANALYSIS
    assert state.timestamps.phase_started is not None


def test_increment_iteration(mgr):
    mgr.initialize_state("s1")
    state = mgr.increment_iteration("s1")
    assert state.iteration_count == 1
    state = mgr.increment_iteration("s1")
    assert state.iteration_count == 2


def test_complete(mgr):
    mgr.initialize_state("s1")
    state = mgr.complete("s1")
    assert state.current_phase == ExecutionPhase.COMPLETE
    assert state.timestamps.completed is not None


def test_get_state_not_found(mgr):
    with pytest.raises(KeyError):
        mgr.get_state("nonexistent")


def test_remove_state(mgr):
    mgr.initialize_state("s1")
    mgr.remove_state("s1")
    with pytest.raises(KeyError):
        mgr.get_state("s1")
