"""Startup module for MemStack application initialization.

Contains modular initialization functions for various services.
"""

from .attempt_recovery import (
    initialize_attempt_recovery,
    shutdown_attempt_recovery,
)
from .autonomy_waker import (
    initialize_autonomy_idle_waker,
    shutdown_autonomy_idle_waker,
)
from .channels import (
    get_channel_manager,
    initialize_channel_manager,
    reload_channel_manager_connections,
    set_message_router,
    shutdown_channel_manager,
)
from .container import initialize_container
from .database import initialize_database_schema
from .docker import initialize_docker_services, shutdown_docker_services
from .graph import initialize_graph_service
from .llm import initialize_llm_providers, sync_health_checker_providers
from .redis import initialize_redis_client
from .sandbox_reaper import initialize_sandbox_idle_reaper, shutdown_sandbox_idle_reaper
from .telemetry import initialize_telemetry, shutdown_telemetry_services
from .websocket import initialize_websocket_manager
from .workflow import initialize_workflow_engine
from .workspace_plan_outbox import (
    initialize_workspace_plan_outbox_worker,
    shutdown_workspace_plan_outbox_worker,
)

__all__ = [
    "get_channel_manager",
    "initialize_attempt_recovery",
    "initialize_autonomy_idle_waker",
    "initialize_channel_manager",
    "initialize_container",
    "initialize_database_schema",
    "initialize_docker_services",
    "initialize_graph_service",
    "initialize_llm_providers",
    "initialize_redis_client",
    "initialize_sandbox_idle_reaper",
    "initialize_telemetry",
    "initialize_websocket_manager",
    "initialize_workflow_engine",
    "initialize_workspace_plan_outbox_worker",
    "reload_channel_manager_connections",
    "set_message_router",
    "shutdown_attempt_recovery",
    "shutdown_autonomy_idle_waker",
    "shutdown_channel_manager",
    "shutdown_docker_services",
    "shutdown_sandbox_idle_reaper",
    "shutdown_telemetry_services",
    "shutdown_workspace_plan_outbox_worker",
    "sync_health_checker_providers",
]
