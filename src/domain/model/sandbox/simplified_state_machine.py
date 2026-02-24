"""Simplified Sandbox State Machine - Reduced to 4 essential states.

This module defines the simplified state machine for sandbox lifecycle management.
The original 10-state model has been reduced to 4 essential states:

Simplified State Diagram:
    ┌───────────┐
    │ STARTING  │
    └─────┬─────┘
          │
          ▼
    ┌───────────┐    error     ┌─────────┐
    │  RUNNING  │─────────────▶│  ERROR  │
    └─────┬─────┘              └────┬────┘
          │                         │
          │ terminate               │ terminate / retry
          ▼                         │
    ┌─────────────────────────────────┘
    │          TERMINATED              │
    └─────────────────────────────────┘

State Mapping (Legacy → Simplified):
- PENDING, CREATING, CONNECTING → STARTING
- RUNNING → RUNNING
- UNHEALTHY, ERROR, DISCONNECTED → ERROR
- STOPPED, TERMINATED → TERMINATED (stopped containers can't be restarted)
- ORPHAN → ERROR (with is_orphan metadata flag)
"""

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from src.domain.model.sandbox.project_sandbox import ProjectSandboxStatus


class SimplifiedSandboxState(Enum):
    """Simplified sandbox status with 4 essential states."""

    STARTING = "starting"  # Sandbox is being created or connecting
    RUNNING = "running"  # Sandbox is running and healthy
    ERROR = "error"  # Sandbox has an error (includes unhealthy, disconnected)
    TERMINATED = "terminated"  # Sandbox has been terminated


class InvalidStateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        from_status: SimplifiedSandboxState,
        to_status: SimplifiedSandboxState,
        sandbox_id: str | None = None,
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.sandbox_id = sandbox_id
        message = (
            f"Invalid state transition from {from_status.value} to {to_status.value}"
            f"{f' for sandbox {sandbox_id}' if sandbox_id else ''}"
        )
        super().__init__(message)


@dataclass(frozen=True)
class StateTransition:
    """Represents a valid state transition."""

    from_status: SimplifiedSandboxState
    to_status: SimplifiedSandboxState
    description: str


class SimplifiedSandboxStateMachine:
    """
    Simplified state machine for managing sandbox lifecycle transitions.

    This reduces the original 10-state model to 4 essential states:
    - STARTING: Combines PENDING, CREATING, CONNECTING
    - RUNNING: Unchanged
    - ERROR: Combines UNHEALTHY, ERROR, DISCONNECTED
    - TERMINATED: Combines STOPPED, TERMINATED

    Usage:
        state_machine = SimplifiedSandboxStateMachine()

        # Check if transition is valid
        if state_machine.can_transition(current_status, new_status):
            sandbox.status = new_status

        # Map legacy status to simplified
        simplified = SimplifiedSandboxStateMachine.legacy_to_simplified(
            ProjectSandboxStatus.CREATING
        )
        # simplified == SimplifiedSandboxState.STARTING
    """

    # Define all valid state transitions for simplified model
    VALID_TRANSITIONS: frozenset[StateTransition] = frozenset(
        [
            # STARTING → RUNNING (successful creation/connection)
            StateTransition(
                SimplifiedSandboxState.STARTING,
                SimplifiedSandboxState.RUNNING,
                "Sandbox started successfully",
            ),
            # STARTING → ERROR (creation/connection failed)
            StateTransition(
                SimplifiedSandboxState.STARTING,
                SimplifiedSandboxState.ERROR,
                "Sandbox start failed",
            ),
            # RUNNING → ERROR (runtime error or became unhealthy)
            StateTransition(
                SimplifiedSandboxState.RUNNING,
                SimplifiedSandboxState.ERROR,
                "Runtime error or health check failed",
            ),
            # RUNNING → TERMINATED (clean shutdown)
            StateTransition(
                SimplifiedSandboxState.RUNNING,
                SimplifiedSandboxState.TERMINATED,
                "Sandbox terminated",
            ),
            # ERROR → STARTING (retry after error)
            StateTransition(
                SimplifiedSandboxState.ERROR,
                SimplifiedSandboxState.STARTING,
                "Retrying after error",
            ),
            # ERROR → TERMINATED (give up on error)
            StateTransition(
                SimplifiedSandboxState.ERROR,
                SimplifiedSandboxState.TERMINATED,
                "Error sandbox terminated",
            ),
        ]
    )

    # Terminal states that cannot transition to other states
    TERMINAL_STATES: frozenset[SimplifiedSandboxState] = frozenset(
        [
            SimplifiedSandboxState.TERMINATED,
        ]
    )

    # States that indicate the sandbox can be used
    USABLE_STATES: frozenset[SimplifiedSandboxState] = frozenset(
        [
            SimplifiedSandboxState.RUNNING,
        ]
    )

    # States that indicate an active sandbox (running or in progress)
    ACTIVE_STATES: frozenset[SimplifiedSandboxState] = frozenset(
        [
            SimplifiedSandboxState.STARTING,
            SimplifiedSandboxState.RUNNING,
        ]
    )

    # States that indicate the sandbox needs recovery
    RECOVERABLE_STATES: frozenset[SimplifiedSandboxState] = frozenset(
        [
            SimplifiedSandboxState.ERROR,
        ]
    )

    # Mapping from legacy ProjectSandboxStatus to SimplifiedSandboxState
    _LEGACY_TO_SIMPLIFIED_MAP: ClassVar[dict[ProjectSandboxStatus, SimplifiedSandboxState]] = {
        # STARTING states
        ProjectSandboxStatus.PENDING: SimplifiedSandboxState.STARTING,
        ProjectSandboxStatus.CREATING: SimplifiedSandboxState.STARTING,
        ProjectSandboxStatus.CONNECTING: SimplifiedSandboxState.STARTING,
        # RUNNING states
        ProjectSandboxStatus.RUNNING: SimplifiedSandboxState.RUNNING,
        # ERROR states
        ProjectSandboxStatus.UNHEALTHY: SimplifiedSandboxState.ERROR,
        ProjectSandboxStatus.ERROR: SimplifiedSandboxState.ERROR,
        ProjectSandboxStatus.DISCONNECTED: SimplifiedSandboxState.ERROR,
        # TERMINATED states
        ProjectSandboxStatus.STOPPED: SimplifiedSandboxState.TERMINATED,
        ProjectSandboxStatus.TERMINATED: SimplifiedSandboxState.TERMINATED,
        # ORPHAN is treated as ERROR (with metadata flag)
        ProjectSandboxStatus.ORPHAN: SimplifiedSandboxState.ERROR,
    }

    # Mapping from SimplifiedSandboxState to most specific legacy ProjectSandboxStatus
    _SIMPLIFIED_TO_LEGACY_MAP: ClassVar[dict[SimplifiedSandboxState, ProjectSandboxStatus]] = {
        SimplifiedSandboxState.STARTING: ProjectSandboxStatus.CREATING,
        SimplifiedSandboxState.RUNNING: ProjectSandboxStatus.RUNNING,
        SimplifiedSandboxState.ERROR: ProjectSandboxStatus.ERROR,
        SimplifiedSandboxState.TERMINATED: ProjectSandboxStatus.TERMINATED,
    }

    def __init__(self) -> None:
        """Initialize the state machine with transition lookup table."""
        # Build a fast lookup table for valid transitions
        self._transition_map: dict[SimplifiedSandboxState, set[SimplifiedSandboxState]] = {}
        for transition in self.VALID_TRANSITIONS:
            if transition.from_status not in self._transition_map:
                self._transition_map[transition.from_status] = set()
            self._transition_map[transition.from_status].add(transition.to_status)

    def can_transition(
        self,
        from_status: SimplifiedSandboxState,
        to_status: SimplifiedSandboxState,
    ) -> bool:
        """
        Check if a transition from one status to another is valid.

        Args:
            from_status: Current status
            to_status: Desired status

        Returns:
            True if the transition is valid, False otherwise
        """
        # Same status transition is always allowed (no-op)
        if from_status == to_status:
            return True

        # Check if from_status is a terminal state
        if from_status in self.TERMINAL_STATES:
            return False

        # Check if transition is in valid transitions
        valid_targets = self._transition_map.get(from_status, set())
        return to_status in valid_targets

    def transition(
        self,
        from_status: SimplifiedSandboxState,
        to_status: SimplifiedSandboxState,
        sandbox_id: str | None = None,
    ) -> SimplifiedSandboxState:
        """
        Validate and execute a state transition.

        Args:
            from_status: Current status
            to_status: Desired status
            sandbox_id: Optional sandbox ID for error messages

        Returns:
            The new status if transition is valid

        Raises:
            InvalidStateTransitionError: If the transition is not valid
        """
        if not self.can_transition(from_status, to_status):
            raise InvalidStateTransitionError(from_status, to_status, sandbox_id)
        return to_status

    def get_valid_transitions(
        self,
        from_status: SimplifiedSandboxState,
    ) -> set[SimplifiedSandboxState]:
        """
        Get all valid target states from a given status.

        Args:
            from_status: Current status

        Returns:
            Set of valid target statuses
        """
        if from_status in self.TERMINAL_STATES:
            return set()
        return self._transition_map.get(from_status, set()).copy()

    def is_usable(self, status: SimplifiedSandboxState) -> bool:
        """Check if sandbox in given status can be used for operations."""
        return status in self.USABLE_STATES

    def is_active(self, status: SimplifiedSandboxState) -> bool:
        """Check if sandbox in given status is active."""
        return status in self.ACTIVE_STATES

    def is_terminal(self, status: SimplifiedSandboxState) -> bool:
        """Check if status is a terminal state."""
        return status in self.TERMINAL_STATES

    def is_recoverable(self, status: SimplifiedSandboxState) -> bool:
        """Check if sandbox in given status can potentially be recovered."""
        return status in self.RECOVERABLE_STATES

    def get_transition_description(
        self,
        from_status: SimplifiedSandboxState,
        to_status: SimplifiedSandboxState,
    ) -> str | None:
        """
        Get the description of a state transition.

        Args:
            from_status: Current status
            to_status: Target status

        Returns:
            Description string if transition exists, None otherwise
        """
        for transition in self.VALID_TRANSITIONS:
            if transition.from_status == from_status and transition.to_status == to_status:
                return transition.description
        return None

    @classmethod
    def legacy_to_simplified(cls, legacy_status: ProjectSandboxStatus) -> SimplifiedSandboxState:
        """
        Convert legacy ProjectSandboxStatus to SimplifiedSandboxState.

        Args:
            legacy_status: The legacy status to convert

        Returns:
            The corresponding simplified state

        Raises:
            ValueError: If the legacy status is unknown
        """
        try:
            return cls._LEGACY_TO_SIMPLIFIED_MAP[legacy_status]
        except KeyError as e:
            raise ValueError(f"Unknown legacy status: {legacy_status}") from e

    @classmethod
    def simplified_to_legacy(
        cls, simplified_status: SimplifiedSandboxState
    ) -> ProjectSandboxStatus:
        """
        Convert SimplifiedSandboxState to most specific legacy ProjectSandboxStatus.

        Args:
            simplified_status: The simplified status to convert

        Returns:
            The most specific corresponding legacy status

        Raises:
            ValueError: If the simplified status is unknown
        """
        try:
            return cls._SIMPLIFIED_TO_LEGACY_MAP[simplified_status]
        except KeyError as e:
            raise ValueError(f"Unknown simplified status: {simplified_status}") from e


# Global state machine instance for convenience
_simplified_state_machine = SimplifiedSandboxStateMachine()


def get_simplified_state_machine() -> SimplifiedSandboxStateMachine:
    """Get the global simplified state machine instance."""
    return _simplified_state_machine
