"""Deployment-owned cloud application operations for the signed knowledge package."""

from collections.abc import Mapping
from typing import Any

from src.host.operations.deployment_adapters import ApplicationAdapter, provide_application_adapter
from src.infrastructure.plugins.v2.runtime_context import ContextV2

from .entity_queries import ENTITY_OPERATIONS
from .package_memory_editor import save_memory
from .project_memory_operation import list_project_memories


def apply(ctx: ContextV2, _config: Mapping[str, Any]) -> None:
    provide_application_adapter(
        ctx,
        ApplicationAdapter(
            plugin_id="memstack-knowledge",
            project={
                **ENTITY_OPERATIONS,
                "app.knowledge.memories.read": list_project_memories,
                "app.knowledge.memories.write": save_memory,
            },
        ),
    )
