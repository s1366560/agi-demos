"""
Agent Pool 生命周期管理模块.
"""

from .state_machine import (
    VALID_TRANSITIONS,
    InvalidStateTransitionError,
    LifecycleStateMachine,
    StateTransition,
)

__all__ = [
    "LifecycleStateMachine",
    "StateTransition",
    "InvalidStateTransitionError",
    "VALID_TRANSITIONS",
]
