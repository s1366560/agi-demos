"""Deferred HTTP registration keeps application composition independent of routes."""

from __future__ import annotations

from .cloud_knowledge_sync_services import cloud_knowledge_sync_service_definitions_v2
from .runtime import PluginDefinitionV2


def cloud_knowledge_sync_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    from .builtin_cloud_knowledge_sync_http_routes import (
        builtin_cloud_knowledge_sync_http_routes_definition_v2,
    )

    return (
        *cloud_knowledge_sync_service_definitions_v2(),
        builtin_cloud_knowledge_sync_http_routes_definition_v2(),
    )
