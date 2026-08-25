"""Startup module for MemStack application initialization.

Contains modular initialization functions for various services.
"""

from .autonomy_waker import (
    initialize_autonomy_idle_waker,
    shutdown_autonomy_idle_waker,
)
from .blackboard_outbox import (
    initialize_blackboard_outbox_dispatcher,
    shutdown_blackboard_outbox_dispatcher,
)
from .container import initialize_container
from .database import initialize_database_schema
from .generation_http_v2 import mount_generation_http_dispatcher_v2
from .llm import initialize_llm_providers
from .redis import initialize_redis_client
from .telemetry import initialize_telemetry, shutdown_telemetry_services

__all__ = [
    "initialize_autonomy_idle_waker",
    "initialize_blackboard_outbox_dispatcher",
    "initialize_container",
    "initialize_database_schema",
    "initialize_llm_providers",
    "initialize_redis_client",
    "initialize_telemetry",
    "mount_generation_http_dispatcher_v2",
    "shutdown_autonomy_idle_waker",
    "shutdown_blackboard_outbox_dispatcher",
    "shutdown_telemetry_services",
]
