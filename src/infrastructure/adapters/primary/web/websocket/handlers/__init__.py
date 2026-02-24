"""
WebSocket Handlers Module

Contains message handlers for different WebSocket message types:
- ChatHandler: send_message, stop_session
- SubscriptionHandler: subscribe, unsubscribe
- StatusHandler: subscribe_status, unsubscribe_status
- LifecycleHandler: subscribe_lifecycle_state, start/stop/restart_agent
- HITLHandler: clarification_respond, decision_respond, env_var_respond, permission_respond
- SandboxHandler: subscribe_sandbox, unsubscribe_sandbox
"""

from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
    SendMessageHandler,
    StopSessionHandler,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.hitl_handler import (
    ClarificationRespondHandler,
    DecisionRespondHandler,
    EnvVarRespondHandler,
    PermissionRespondHandler,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.lifecycle_handler import (
    RestartAgentHandler,
    StartAgentHandler,
    StopAgentHandler,
    SubscribeLifecycleStateHandler,
    UnsubscribeLifecycleStateHandler,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.sandbox_handler import (
    SubscribeSandboxHandler,
    UnsubscribeSandboxHandler,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.status_handler import (
    SubscribeStatusHandler,
    UnsubscribeStatusHandler,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.subscription_handler import (
    SubscribeHandler,
    UnsubscribeHandler,
)

__all__ = [
    # HITL
    "ClarificationRespondHandler",
    "DecisionRespondHandler",
    "EnvVarRespondHandler",
    "PermissionRespondHandler",
    "RestartAgentHandler",
    # Chat
    "SendMessageHandler",
    "StartAgentHandler",
    "StopAgentHandler",
    "StopSessionHandler",
    # Subscription
    "SubscribeHandler",
    # Lifecycle
    "SubscribeLifecycleStateHandler",
    # Sandbox
    "SubscribeSandboxHandler",
    # Status
    "SubscribeStatusHandler",
    "UnsubscribeHandler",
    "UnsubscribeLifecycleStateHandler",
    "UnsubscribeSandboxHandler",
    "UnsubscribeStatusHandler",
    "WebSocketMessageHandler",
]
