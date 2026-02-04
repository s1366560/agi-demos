"""
High Availability (HA) module for Agent Pool.

Provides:
- StateRecoveryService: Checkpoint-based state persistence
- FailureRecoveryService: Automatic failure detection and recovery
- AutoScalingService: Dynamic scaling based on load

These services work together to ensure high availability:
1. StateRecoveryService periodically checkpoints instance state
2. FailureRecoveryService detects failures and triggers recovery
3. AutoScalingService adjusts capacity based on demand
"""

from .auto_scaling import (
    AutoScalingService,
    ScalingDecision,
    ScalingDirection,
    ScalingEvent,
    ScalingMetrics,
    ScalingPolicy,
    ScalingReason,
)
from .failure_recovery import (
    FailureEvent,
    FailurePattern,
    FailureRecoveryService,
    FailureType,
    RecoveryAction,
    RecoveryStatus,
    RecoveryStrategy,
)
from .state_recovery import (
    CheckpointType,
    RecoveryResult,
    StateCheckpoint,
    StateRecoveryService,
)

__all__ = [
    # State Recovery
    "StateRecoveryService",
    "StateCheckpoint",
    "CheckpointType",
    "RecoveryResult",
    # Failure Recovery
    "FailureRecoveryService",
    "FailureEvent",
    "FailurePattern",
    "FailureType",
    "RecoveryAction",
    "RecoveryStatus",
    "RecoveryStrategy",
    # Auto Scaling
    "AutoScalingService",
    "ScalingPolicy",
    "ScalingMetrics",
    "ScalingDecision",
    "ScalingEvent",
    "ScalingDirection",
    "ScalingReason",
]
