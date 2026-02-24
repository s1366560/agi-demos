"""Sandbox State Machine - Explicit state transitions for sandbox lifecycle.

This module defines the valid state transitions for sandbox lifecycle management,
ensuring that only valid transitions are allowed and providing clear error messages
for invalid state changes.

State Diagram:
    ┌─────────┐    ┌──────────┐    ┌─────────┐    ┌───────────┐    ┌────────────┐
    │ PENDING │───▶│ CREATING │───▶│ RUNNING │───▶│ UNHEALTHY │───▶│ TERMINATED │
    └─────────┘    └──────────┘    └─────────┘    └───────────┘    └────────────┘
         │                              │              │ ▲                 ▲
         │                              │              ▼ │                 │
         │                              │         ┌──────────┐            │
         │                              ├────────▶│  STOPPED │────────────┤
         │                              │         └──────────┘            │
         │                              │              │                  │
         │                              │              ▼                  │
         │                              │         ┌─────────┐             │
         └──────────────────────────────┴────────▶│  ERROR  │─────────────┤
                                                  └─────────┘             │
    Local Sandbox Extension:                                              │
    ┌────────────┐    ┌──────────────┐                                   │
    │ CONNECTING │───▶│ DISCONNECTED │───────────────────────────────────┘
    └────────────┘    └──────────────┘

    Orphan State (discovered containers without associations):
    ┌─────────┐
    │ ORPHAN  │──▶ (can be adopted or terminated)
    └─────────┘
"""

from dataclasses import dataclass
from enum import Enum


class ProjectSandboxStatus(Enum):
    """Status of a project-sandbox association."""

    # Cloud sandbox states
    PENDING = "pending"  # Sandbox creation requested but not yet ready
    CREATING = "creating"  # Sandbox is being created
    RUNNING = "running"  # Sandbox is running and healthy
    UNHEALTHY = "unhealthy"  # Sandbox is running but unhealthy
    STOPPED = "stopped"  # Sandbox is stopped but can be restarted
    TERMINATED = "terminated"  # Sandbox has been terminated
    ERROR = "error"  # Sandbox creation or operation failed

    # Local sandbox states
    CONNECTING = "connecting"  # Local sandbox connection in progress
    DISCONNECTED = "disconnected"  # Local sandbox disconnected

    # Orphan state (discovered containers without DB association)
    ORPHAN = "orphan"  # Container exists but no valid association


class InvalidStateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        from_status: ProjectSandboxStatus,
        to_status: ProjectSandboxStatus,
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

    from_status: ProjectSandboxStatus
    to_status: ProjectSandboxStatus
    description: str


class SandboxStateMachine:
    """
    State machine for managing sandbox lifecycle transitions.

    This class defines all valid state transitions and provides methods
    to validate and execute transitions safely.

    Usage:
        state_machine = SandboxStateMachine()

        # Check if transition is valid
        if state_machine.can_transition(current_status, new_status):
            sandbox.status = new_status

        # Or use transition method which validates and returns new status
        new_status = state_machine.transition(current_status, new_status, sandbox_id)

        # Get valid next states
        valid_states = state_machine.get_valid_transitions(current_status)
    """

    # Define all valid state transitions
    VALID_TRANSITIONS: frozenset[StateTransition] = frozenset(
        [
            # Cloud sandbox lifecycle - normal flow
            StateTransition(
                ProjectSandboxStatus.PENDING,
                ProjectSandboxStatus.CREATING,
                "Start sandbox creation",
            ),
            StateTransition(
                ProjectSandboxStatus.CREATING,
                ProjectSandboxStatus.RUNNING,
                "Sandbox created successfully",
            ),
            StateTransition(
                ProjectSandboxStatus.RUNNING,
                ProjectSandboxStatus.UNHEALTHY,
                "Health check failed",
            ),
            StateTransition(
                ProjectSandboxStatus.RUNNING,
                ProjectSandboxStatus.STOPPED,
                "Sandbox stopped",
            ),
            StateTransition(
                ProjectSandboxStatus.RUNNING,
                ProjectSandboxStatus.TERMINATED,
                "Sandbox terminated",
            ),
            StateTransition(
                ProjectSandboxStatus.UNHEALTHY,
                ProjectSandboxStatus.RUNNING,
                "Recovery succeeded",
            ),
            StateTransition(
                ProjectSandboxStatus.UNHEALTHY,
                ProjectSandboxStatus.STOPPED,
                "Sandbox stopped while unhealthy",
            ),
            StateTransition(
                ProjectSandboxStatus.UNHEALTHY,
                ProjectSandboxStatus.TERMINATED,
                "Unhealthy sandbox terminated",
            ),
            StateTransition(
                ProjectSandboxStatus.STOPPED,
                ProjectSandboxStatus.CREATING,
                "Restart stopped sandbox",
            ),
            StateTransition(
                ProjectSandboxStatus.STOPPED,
                ProjectSandboxStatus.TERMINATED,
                "Stopped sandbox terminated",
            ),
            # Error transitions - can happen from most states
            StateTransition(
                ProjectSandboxStatus.PENDING,
                ProjectSandboxStatus.ERROR,
                "Creation request failed",
            ),
            StateTransition(
                ProjectSandboxStatus.CREATING,
                ProjectSandboxStatus.ERROR,
                "Creation process failed",
            ),
            StateTransition(
                ProjectSandboxStatus.RUNNING,
                ProjectSandboxStatus.ERROR,
                "Runtime error occurred",
            ),
            StateTransition(
                ProjectSandboxStatus.UNHEALTHY,
                ProjectSandboxStatus.ERROR,
                "Recovery failed",
            ),
            StateTransition(
                ProjectSandboxStatus.ERROR,
                ProjectSandboxStatus.CREATING,
                "Retry after error",
            ),
            StateTransition(
                ProjectSandboxStatus.ERROR,
                ProjectSandboxStatus.TERMINATED,
                "Error sandbox terminated",
            ),
            # Local sandbox transitions
            StateTransition(
                ProjectSandboxStatus.PENDING,
                ProjectSandboxStatus.CONNECTING,
                "Start local sandbox connection",
            ),
            StateTransition(
                ProjectSandboxStatus.CONNECTING,
                ProjectSandboxStatus.RUNNING,
                "Local sandbox connected",
            ),
            StateTransition(
                ProjectSandboxStatus.CONNECTING,
                ProjectSandboxStatus.DISCONNECTED,
                "Connection attempt failed",
            ),
            StateTransition(
                ProjectSandboxStatus.CONNECTING,
                ProjectSandboxStatus.ERROR,
                "Connection error",
            ),
            StateTransition(
                ProjectSandboxStatus.RUNNING,
                ProjectSandboxStatus.DISCONNECTED,
                "Local sandbox disconnected",
            ),
            StateTransition(
                ProjectSandboxStatus.DISCONNECTED,
                ProjectSandboxStatus.CONNECTING,
                "Reconnection attempt",
            ),
            StateTransition(
                ProjectSandboxStatus.DISCONNECTED,
                ProjectSandboxStatus.TERMINATED,
                "Disconnected sandbox terminated",
            ),
            # Orphan state transitions
            StateTransition(
                ProjectSandboxStatus.ORPHAN,
                ProjectSandboxStatus.RUNNING,
                "Orphan adopted and running",
            ),
            StateTransition(
                ProjectSandboxStatus.ORPHAN,
                ProjectSandboxStatus.TERMINATED,
                "Orphan terminated",
            ),
            StateTransition(
                ProjectSandboxStatus.ORPHAN,
                ProjectSandboxStatus.UNHEALTHY,
                "Orphan adopted but unhealthy",
            ),
        ]
    )

    # Terminal states that cannot transition to other states
    TERMINAL_STATES: frozenset[ProjectSandboxStatus] = frozenset(
        [
            ProjectSandboxStatus.TERMINATED,
        ]
    )

    # States that indicate the sandbox can be used
    USABLE_STATES: frozenset[ProjectSandboxStatus] = frozenset(
        [
            ProjectSandboxStatus.RUNNING,
        ]
    )

    # States that indicate an active sandbox (running or in progress)
    ACTIVE_STATES: frozenset[ProjectSandboxStatus] = frozenset(
        [
            ProjectSandboxStatus.RUNNING,
            ProjectSandboxStatus.CREATING,
            ProjectSandboxStatus.CONNECTING,
            ProjectSandboxStatus.UNHEALTHY,
        ]
    )

    # States that indicate the sandbox needs recovery
    RECOVERABLE_STATES: frozenset[ProjectSandboxStatus] = frozenset(
        [
            ProjectSandboxStatus.UNHEALTHY,
            ProjectSandboxStatus.STOPPED,
            ProjectSandboxStatus.ERROR,
            ProjectSandboxStatus.DISCONNECTED,
        ]
    )

    def __init__(self) -> None:
        """Initialize the state machine with transition lookup table."""
        # Build a fast lookup table for valid transitions
        self._transition_map: dict[ProjectSandboxStatus, set[ProjectSandboxStatus]] = {}
        for transition in self.VALID_TRANSITIONS:
            if transition.from_status not in self._transition_map:
                self._transition_map[transition.from_status] = set()
            self._transition_map[transition.from_status].add(transition.to_status)

    def can_transition(
        self,
        from_status: ProjectSandboxStatus,
        to_status: ProjectSandboxStatus,
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
        from_status: ProjectSandboxStatus,
        to_status: ProjectSandboxStatus,
        sandbox_id: str | None = None,
    ) -> ProjectSandboxStatus:
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
        from_status: ProjectSandboxStatus,
    ) -> set[ProjectSandboxStatus]:
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

    def is_usable(self, status: ProjectSandboxStatus) -> bool:
        """Check if sandbox in given status can be used for operations."""
        return status in self.USABLE_STATES

    def is_active(self, status: ProjectSandboxStatus) -> bool:
        """Check if sandbox in given status is active."""
        return status in self.ACTIVE_STATES

    def is_terminal(self, status: ProjectSandboxStatus) -> bool:
        """Check if status is a terminal state."""
        return status in self.TERMINAL_STATES

    def is_recoverable(self, status: ProjectSandboxStatus) -> bool:
        """Check if sandbox in given status can potentially be recovered."""
        return status in self.RECOVERABLE_STATES

    def get_transition_description(
        self,
        from_status: ProjectSandboxStatus,
        to_status: ProjectSandboxStatus,
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


# Global state machine instance for convenience
_state_machine = SandboxStateMachine()


def get_state_machine() -> SandboxStateMachine:
    """Get the global state machine instance."""
    return _state_machine


def validate_transition(
    from_status: ProjectSandboxStatus,
    to_status: ProjectSandboxStatus,
    sandbox_id: str | None = None,
) -> ProjectSandboxStatus:
    """
    Convenience function to validate a state transition.

    Args:
        from_status: Current status
        to_status: Desired status
        sandbox_id: Optional sandbox ID for error messages

    Returns:
        The new status if transition is valid

    Raises:
        InvalidStateTransitionError: If the transition is not valid
    """
    return _state_machine.transition(from_status, to_status, sandbox_id)
