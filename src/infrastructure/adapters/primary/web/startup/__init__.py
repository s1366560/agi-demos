"""Startup module for MemStack application initialization.

Contains modular initialization functions for various services.
"""

from .artifact_content_orphan_gc import (
    initialize_artifact_content_orphan_gc_worker,
    shutdown_artifact_content_orphan_gc_worker,
)
from .autonomy_waker import (
    initialize_autonomy_idle_waker,
    shutdown_autonomy_idle_waker,
)
from .blackboard_outbox import (
    initialize_blackboard_outbox_dispatcher,
    shutdown_blackboard_outbox_dispatcher,
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
from .shadow_rollout import (
    initialize_shadow_rollout_worker,
    record_initial_http_route_inventory_shadow,
    shutdown_shadow_rollout_worker,
)
from .telemetry import initialize_telemetry, shutdown_telemetry_services
from .websocket import initialize_websocket_manager
from .workflow import initialize_workflow_engine

__all__ = [
    "get_channel_manager",
    "initialize_artifact_content_orphan_gc_worker",
    "initialize_autonomy_idle_waker",
    "initialize_blackboard_outbox_dispatcher",
    "initialize_channel_manager",
    "initialize_container",
    "initialize_database_schema",
    "initialize_docker_services",
    "initialize_graph_service",
    "initialize_llm_providers",
    "initialize_redis_client",
    "initialize_sandbox_idle_reaper",
    "initialize_shadow_rollout_worker",
    "initialize_telemetry",
    "initialize_websocket_manager",
    "initialize_workflow_engine",
    "record_initial_http_route_inventory_shadow",
    "reload_channel_manager_connections",
    "set_message_router",
    "shutdown_artifact_content_orphan_gc_worker",
    "shutdown_autonomy_idle_waker",
    "shutdown_blackboard_outbox_dispatcher",
    "shutdown_channel_manager",
    "shutdown_docker_services",
    "shutdown_sandbox_idle_reaper",
    "shutdown_shadow_rollout_worker",
    "shutdown_telemetry_services",
    "sync_health_checker_providers",
]
