"""Sandbox domain models.

This module provides domain models for sandbox lifecycle management:
- ProjectSandbox: Entity representing a project-sandbox association
- ProjectSandboxStatus: Status enum including ORPHAN status
- SandboxType: Cloud vs Local sandbox types
- SandboxStateMachine: Explicit state transition validation
"""

from src.domain.model.sandbox.project_sandbox import (
    LocalSandboxConfig,
    ProjectSandbox,
    ProjectSandboxStatus,
    SandboxTransport,
    SandboxType,
)
from src.domain.model.sandbox.state_machine import (
    InvalidStateTransitionError,
    SandboxStateMachine,
    StateTransition,
    get_state_machine,
    validate_transition,
)

__all__ = [
    # Entity and value objects
    "ProjectSandbox",
    "ProjectSandboxStatus",
    "SandboxType",
    "SandboxTransport",
    "LocalSandboxConfig",
    # State machine
    "SandboxStateMachine",
    "InvalidStateTransitionError",
    "StateTransition",
    "get_state_machine",
    "validate_transition",
]
