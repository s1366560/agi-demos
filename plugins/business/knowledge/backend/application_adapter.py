"""Deployment-owned cloud application operations for the signed knowledge package."""

from collections.abc import Mapping
from typing import Any

from src.host.operations.deployment_adapters import ApplicationAdapter, provide_application_adapter
from src.infrastructure.plugins.v2.runtime_context import ContextV2

from .entity_queries import ENTITY_OPERATIONS
from .graph_queries import read_graph, read_subgraph
from .memory_maintenance import delete_memory, optimize_content, read_index_task, reindex_memory
from .package_memory_editor import save_memory
from .project_memory_operation import list_project_memories
from .project_search import search


def apply(ctx: ContextV2, _config: Mapping[str, Any]) -> None:
    provide_application_adapter(
        ctx,
        ApplicationAdapter(
            plugin_id="memstack-knowledge",
            project={
                **ENTITY_OPERATIONS,
                "app.knowledge.search": search,
                "app.knowledge.graph.read": read_graph,
                "app.knowledge.graph.subgraph": read_subgraph,
                "app.knowledge.memories.read": list_project_memories,
                "app.knowledge.memories.optimize": optimize_content,
                "app.knowledge.memories.index_status": read_index_task,
                "app.knowledge.memories.delete": delete_memory,
                "app.knowledge.memories.reindex": reindex_memory,
                "app.knowledge.memories.write": save_memory,
            },
        ),
    )
