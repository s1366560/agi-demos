"""
Human-in-the-Loop (HITL) infrastructure.

This module provides the base framework for HITL tools that require
human input during agent execution.

Architecture:
- BaseHITLManager: Abstract base class for all HITL managers
- BaseHITLRequest: Abstract base class for HITL request objects
- Concrete implementations: DecisionManager, ClarificationManager, EnvVarManager
- HITLHandler: Unified handler for HITL tool execution

Features:
- Redis Streams for reliable cross-process communication
- Database persistence for recovery after page refresh
- Consumer groups for at-least-once delivery
- Automatic cleanup and timeout handling
"""

from src.infrastructure.agent.hitl.base_manager import (
    BaseHITLManager,
    BaseHITLRequest,
    HITLManagerConfig,
)
from src.infrastructure.agent.hitl.clarification_manager import (
    ClarificationManager,
    ClarificationOption,
    ClarificationRequest,
    ClarificationType,
    get_clarification_manager,
    set_clarification_manager,
)
from src.infrastructure.agent.hitl.decision_manager import (
    DecisionManager,
    DecisionOption,
    DecisionRequest,
    DecisionType,
    get_decision_manager,
    set_decision_manager,
)
from src.infrastructure.agent.hitl.env_var_manager import (
    EnvVarField,
    EnvVarInputType,
    EnvVarManager,
    EnvVarRequest,
    get_env_var_manager,
    set_env_var_manager,
)
from src.infrastructure.agent.hitl.handler import (
    HITLHandler,
    HITLContext,
    HITLToolType,
    ToolPartLike,
    get_hitl_handler,
    set_hitl_handler,
)

__all__ = [
    # Base classes
    "BaseHITLManager",
    "BaseHITLRequest",
    "HITLManagerConfig",
    # Decision
    "DecisionManager",
    "DecisionOption",
    "DecisionRequest",
    "DecisionType",
    "get_decision_manager",
    "set_decision_manager",
    # Clarification
    "ClarificationManager",
    "ClarificationOption",
    "ClarificationRequest",
    "ClarificationType",
    "get_clarification_manager",
    "set_clarification_manager",
    # Environment Variables
    "EnvVarManager",
    "EnvVarField",
    "EnvVarInputType",
    "EnvVarRequest",
    "get_env_var_manager",
    "set_env_var_manager",
    # HITL Handler
    "HITLHandler",
    "HITLContext",
    "HITLToolType",
    "ToolPartLike",
    "get_hitl_handler",
    "set_hitl_handler",
]
