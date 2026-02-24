"""Startup module for MemStack application initialization.

Contains modular initialization functions for various services.
"""

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
from .llm import initialize_llm_providers
from .redis import initialize_redis_client
from .telemetry import initialize_telemetry, shutdown_telemetry_services
from .websocket import initialize_websocket_manager
from .workflow import initialize_workflow_engine

__all__ = [
    "get_channel_manager",
    "initialize_channel_manager",
    "initialize_container",
    "initialize_database_schema",
    "initialize_docker_services",
    "initialize_graph_service",
    "initialize_llm_providers",
    "initialize_redis_client",
    "initialize_telemetry",
    "initialize_websocket_manager",
    "initialize_workflow_engine",
    "reload_channel_manager_connections",
    "set_message_router",
    "shutdown_channel_manager",
    "shutdown_docker_services",
    "shutdown_telemetry_services",
]
