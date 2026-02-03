"""Tests for simplified Sandbox state machine.

TDD approach: RED → GREEN → REFACTOR

This test file defines the behavior for the simplified state machine with 4 states:
- STARTING (combining PENDING, CREATING, CONNECTING)
- RUNNING (unchanged)
- ERROR (combining UNHEALTHY, ERROR, DISCONNECTED)
- TERMINATED (unchanged)
"""

from enum import Enum

import pytest

from src.domain.model.sandbox.project_sandbox import ProjectSandboxStatus
from src.domain.model.sandbox.simplified_state_machine import (
    InvalidStateTransitionError,
    SimplifiedSandboxState,
    SimplifiedSandboxStateMachine,
)


class TestSimplifiedSandboxState:
    """Test the simplified state enum."""

    def test_four_states_only(self):
        """Simplified state machine should have exactly 4 states."""
        assert len(SimplifiedSandboxState) == 4
        states = {s.value for s in SimplifiedSandboxState}
        expected = {"starting", "running", "error", "terminated"}
        assert states == expected

    def test_starting_state_exists(self):
        """STARTING state should exist."""
        assert SimplifiedSandboxState.STARTING.value == "starting"

    def test_running_state_exists(self):
        """RUNNING state should exist."""
        assert SimplifiedSandboxState.RUNNING.value == "running"

    def test_error_state_exists(self):
        """ERROR state should exist."""
        assert SimplifiedSandboxState.ERROR.value == "error"

    def test_terminated_state_exists(self):
        """TERMINATED state should exist."""
        assert SimplifiedSandboxState.TERMINATED.value == "terminated"


class TestStateMapping:
    """Test legacy state mapping to simplified states."""

    def test_pending_maps_to_starting(self):
        """PENDING should map to STARTING."""
        mapping = SimplifiedSandboxStateMachine.legacy_to_simplified(
            ProjectSandboxStatus.PENDING
        )
        assert mapping == SimplifiedSandboxState.STARTING

    def test_creating_maps_to_starting(self):
        """CREATING should map to STARTING."""
        mapping = SimplifiedSandboxStateMachine.legacy_to_simplified(
            ProjectSandboxStatus.CREATING
        )
        assert mapping == SimplifiedSandboxState.STARTING

    def test_connecting_maps_to_starting(self):
        """CONNECTING should map to STARTING."""
        mapping = SimplifiedSandboxStateMachine.legacy_to_simplified(
            ProjectSandboxStatus.CONNECTING
        )
        assert mapping == SimplifiedSandboxState.STARTING

    def test_running_maps_to_running(self):
        """RUNNING should map to RUNNING."""
        mapping = SimplifiedSandboxStateMachine.legacy_to_simplified(
            ProjectSandboxStatus.RUNNING
        )
        assert mapping == SimplifiedSandboxState.RUNNING

    def test_unhealthy_maps_to_error(self):
        """UNHEALTHY should map to ERROR."""
        mapping = SimplifiedSandboxStateMachine.legacy_to_simplified(
            ProjectSandboxStatus.UNHEALTHY
        )
        assert mapping == SimplifiedSandboxState.ERROR

    def test_error_maps_to_error(self):
        """ERROR should map to ERROR."""
        mapping = SimplifiedSandboxStateMachine.legacy_to_simplified(
            ProjectSandboxStatus.ERROR
        )
        assert mapping == SimplifiedSandboxState.ERROR

    def test_disconnected_maps_to_error(self):
        """DISCONNECTED should map to ERROR."""
        mapping = SimplifiedSandboxStateMachine.legacy_to_simplified(
            ProjectSandboxStatus.DISCONNECTED
        )
        assert mapping == SimplifiedSandboxState.ERROR

    def test_stopped_maps_to_terminated(self):
        """STOPPED should map to TERMINATED (since containers can't be restarted)."""
        mapping = SimplifiedSandboxStateMachine.legacy_to_simplified(
            ProjectSandboxStatus.STOPPED
        )
        assert mapping == SimplifiedSandboxState.TERMINATED

    def test_terminated_maps_to_terminated(self):
        """TERMINATED should map to TERMINATED."""
        mapping = SimplifiedSandboxStateMachine.legacy_to_simplified(
            ProjectSandboxStatus.TERMINATED
        )
        assert mapping == SimplifiedSandboxState.TERMINATED

    def test_orphan_maps_to_error(self):
        """ORPHAN should map to ERROR (as metadata flag, not a state)."""
        mapping = SimplifiedSandboxStateMachine.legacy_to_simplified(
            ProjectSandboxStatus.ORPHAN
        )
        assert mapping == SimplifiedSandboxState.ERROR


class TestBackwardCompatibility:
    """Test backward compatibility methods."""

    def test_simplified_to_legacy_mapping(self):
        """Test conversion from simplified to legacy status."""
        # Starting can map back to CREATING (most specific)
        assert SimplifiedSandboxStateMachine.simplified_to_legacy(
            SimplifiedSandboxState.STARTING
        ) in [
            ProjectSandboxStatus.CREATING,
            ProjectSandboxStatus.PENDING,
            ProjectSandboxStatus.CONNECTING,
        ]

        # Running maps to RUNNING
        assert (
            SimplifiedSandboxStateMachine.simplified_to_legacy(
                SimplifiedSandboxState.RUNNING
            )
            == ProjectSandboxStatus.RUNNING
        )

        # Error maps to ERROR (most generic)
        assert (
            SimplifiedSandboxStateMachine.simplified_to_legacy(
                SimplifiedSandboxState.ERROR
            )
            == ProjectSandboxStatus.ERROR
        )

        # Terminated maps to TERMINATED
        assert (
            SimplifiedSandboxStateMachine.simplified_to_legacy(
                SimplifiedSandboxState.TERMINATED
            )
            == ProjectSandboxStatus.TERMINATED
        )


class TestValidTransitions:
    """Test valid state transitions in simplified state machine."""

    def test_starting_to_running(self):
        """STARTING can transition to RUNNING."""
        sm = SimplifiedSandboxStateMachine()
        assert sm.can_transition(
            SimplifiedSandboxState.STARTING, SimplifiedSandboxState.RUNNING
        )

    def test_starting_to_error(self):
        """STARTING can transition to ERROR."""
        sm = SimplifiedSandboxStateMachine()
        assert sm.can_transition(
            SimplifiedSandboxState.STARTING, SimplifiedSandboxState.ERROR
        )

    def test_running_to_error(self):
        """RUNNING can transition to ERROR."""
        sm = SimplifiedSandboxStateMachine()
        assert sm.can_transition(
            SimplifiedSandboxState.RUNNING, SimplifiedSandboxState.ERROR
        )

    def test_running_to_terminated(self):
        """RUNNING can transition to TERMINATED."""
        sm = SimplifiedSandboxStateMachine()
        assert sm.can_transition(
            SimplifiedSandboxState.RUNNING, SimplifiedSandboxState.TERMINATED
        )

    def test_error_to_starting(self):
        """ERROR can transition to STARTING (retry)."""
        sm = SimplifiedSandboxStateMachine()
        assert sm.can_transition(
            SimplifiedSandboxState.ERROR, SimplifiedSandboxState.STARTING
        )

    def test_error_to_terminated(self):
        """ERROR can transition to TERMINATED."""
        sm = SimplifiedSandboxStateMachine()
        assert sm.can_transition(
            SimplifiedSandboxState.ERROR, SimplifiedSandboxState.TERMINATED
        )

    def test_terminated_is_terminal(self):
        """TERMINATED cannot transition to any other state."""
        sm = SimplifiedSandboxStateMachine()
        for state in SimplifiedSandboxState:
            if state != SimplifiedSandboxState.TERMINATED:
                assert not sm.can_transition(
                    SimplifiedSandboxState.TERMINATED, state
                )


class TestInvalidTransitions:
    """Test invalid state transitions raise errors."""

    def test_invalid_transition_raises_error(self):
        """Invalid transition should raise InvalidStateTransitionError."""
        sm = SimplifiedSandboxStateMachine()
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            sm.transition(
                SimplifiedSandboxState.TERMINATED,
                SimplifiedSandboxState.RUNNING,
                "test-sandbox",
            )
        assert "test-sandbox" in str(exc_info.value)

    def test_same_state_is_allowed(self):
        """Transition to same state should be allowed (no-op)."""
        sm = SimplifiedSandboxStateMachine()
        assert sm.can_transition(
            SimplifiedSandboxState.RUNNING, SimplifiedSandboxState.RUNNING
        )


class TestStateQueries:
    """Test state query methods."""

    def test_is_usable(self):
        """Only RUNNING state is usable."""
        sm = SimplifiedSandboxStateMachine()
        assert sm.is_usable(SimplifiedSandboxState.RUNNING)
        assert not sm.is_usable(SimplifiedSandboxState.STARTING)
        assert not sm.is_usable(SimplifiedSandboxState.ERROR)
        assert not sm.is_usable(SimplifiedSandboxState.TERMINATED)

    def test_is_active(self):
        """STARTING and RUNNING are active states."""
        sm = SimplifiedSandboxStateMachine()
        assert sm.is_active(SimplifiedSandboxState.STARTING)
        assert sm.is_active(SimplifiedSandboxState.RUNNING)
        assert not sm.is_active(SimplifiedSandboxState.ERROR)
        assert not sm.is_active(SimplifiedSandboxState.TERMINATED)

    def test_is_terminal(self):
        """Only TERMINATED is a terminal state."""
        sm = SimplifiedSandboxStateMachine()
        assert sm.is_terminal(SimplifiedSandboxState.TERMINATED)
        assert not sm.is_terminal(SimplifiedSandboxState.STARTING)
        assert not sm.is_terminal(SimplifiedSandboxState.RUNNING)
        assert not sm.is_terminal(SimplifiedSandboxState.ERROR)

    def test_is_recoverable(self):
        """ERROR state is recoverable."""
        sm = SimplifiedSandboxStateMachine()
        assert sm.is_recoverable(SimplifiedSandboxState.ERROR)
        assert not sm.is_recoverable(SimplifiedSandboxState.TERMINATED)
        assert not sm.is_recoverable(SimplifiedSandboxState.RUNNING)


class TestTransitionExecution:
    """Test transition execution."""

    def test_successful_transition(self):
        """Valid transition should return new state."""
        sm = SimplifiedSandboxStateMachine()
        new_state = sm.transition(
            SimplifiedSandboxState.STARTING, SimplifiedSandboxState.RUNNING
        )
        assert new_state == SimplifiedSandboxState.RUNNING

    def test_transition_with_sandbox_id(self):
        """Transition should include sandbox_id in error message."""
        sm = SimplifiedSandboxStateMachine()
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            sm.transition(
                SimplifiedSandboxState.ERROR,
                SimplifiedSandboxState.RUNNING,
                "my-sandbox",
            )
        assert "my-sandbox" in str(exc_info.value)


class TestGetValidTransitions:
    """Test getting valid transition targets."""

    def test_valid_transitions_from_starting(self):
        """From STARTING, can go to RUNNING or ERROR."""
        sm = SimplifiedSandboxStateMachine()
        valid = sm.get_valid_transitions(SimplifiedSandboxState.STARTING)
        assert SimplifiedSandboxState.RUNNING in valid
        assert SimplifiedSandboxState.ERROR in valid

    def test_valid_transitions_from_running(self):
        """From RUNNING, can go to ERROR or TERMINATED."""
        sm = SimplifiedSandboxStateMachine()
        valid = sm.get_valid_transitions(SimplifiedSandboxState.RUNNING)
        assert SimplifiedSandboxState.ERROR in valid
        assert SimplifiedSandboxState.TERMINATED in valid

    def test_valid_transitions_from_error(self):
        """From ERROR, can go to STARTING or TERMINATED."""
        sm = SimplifiedSandboxStateMachine()
        valid = sm.get_valid_transitions(SimplifiedSandboxState.ERROR)
        assert SimplifiedSandboxState.STARTING in valid
        assert SimplifiedSandboxState.TERMINATED in valid

    def test_valid_transitions_from_terminal(self):
        """From TERMINATED, no transitions are possible."""
        sm = SimplifiedSandboxStateMachine()
        valid = sm.get_valid_transitions(SimplifiedSandboxState.TERMINATED)
        assert len(valid) == 0


class TestTransitionDescription:
    """Test getting transition descriptions."""

    def test_get_valid_transition_description(self):
        """Get description for valid transition."""
        sm = SimplifiedSandboxStateMachine()
        desc = sm.get_transition_description(
            SimplifiedSandboxState.STARTING, SimplifiedSandboxState.RUNNING
        )
        assert desc == "Sandbox started successfully"

    def test_get_invalid_transition_description(self):
        """Get None for invalid transition."""
        sm = SimplifiedSandboxStateMachine()
        desc = sm.get_transition_description(
            SimplifiedSandboxState.TERMINATED, SimplifiedSandboxState.RUNNING
        )
        assert desc is None


class TestInvalidMappingInputs:
    """Test error handling for invalid inputs."""

    def test_invalid_legacy_status_raises_error(self):
        """Mapping invalid legacy status should raise ValueError."""
        # Create a mock enum value that doesn't exist
        class FakeStatus(Enum):
            FAKE = "fake"

        with pytest.raises(ValueError, match="Unknown legacy status"):
            SimplifiedSandboxStateMachine.legacy_to_simplified(FakeStatus.FAKE)  # type: ignore

    def test_invalid_simplified_status_raises_error(self):
        """Mapping invalid simplified status should raise ValueError."""
        # Create a mock enum value that doesn't exist
        class FakeState(Enum):
            FAKE = "fake"

        with pytest.raises(ValueError, match="Unknown simplified status"):
            SimplifiedSandboxStateMachine.simplified_to_legacy(FakeState.FAKE)  # type: ignore
