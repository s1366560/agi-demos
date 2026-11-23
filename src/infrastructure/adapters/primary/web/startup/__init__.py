"""Startup hooks are loaded only by the deployment that uses them."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .container import initialize_container
    from .database import initialize_database_schema
    from .generation_http_v2 import mount_generation_http_dispatcher_v2
    from .llm import initialize_llm_providers
    from .redis import initialize_redis_client
    from .telemetry import initialize_telemetry, shutdown_telemetry_services

__all__ = [
    "initialize_container",
    "initialize_database_schema",
    "initialize_llm_providers",
    "initialize_redis_client",
    "initialize_telemetry",
    "mount_generation_http_dispatcher_v2",
    "shutdown_telemetry_services",
]


_EXPORTS = {
    "initialize_container": ".container",
    "initialize_database_schema": ".database",
    "mount_generation_http_dispatcher_v2": ".generation_http_v2",
    "initialize_llm_providers": ".llm",
    "initialize_redis_client": ".redis",
    "initialize_telemetry": ".telemetry",
    "shutdown_telemetry_services": ".telemetry",
}


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(name)
    return getattr(import_module(_EXPORTS[name], __name__), name)
