"""Map admitted command names onto host capabilities."""

from __future__ import annotations

from plugins.business.guest_runtime.binding import bind_operation

OPERATIONS = {
    name: bind_operation(name)
    for name in (
        "app.knowledge.memories.read",
        "app.knowledge.memories.write",
        "app.knowledge.entities.list",
        "app.knowledge.entities.types",
        "app.knowledge.entities.relationships",
        "app.knowledge.memories.delete",
        "app.knowledge.memories.reindex",
        "app.knowledge.memories.index_status",
        "app.knowledge.memories.optimize",
        "app.knowledge.graph.read",
        "app.knowledge.graph.subgraph",
        "app.knowledge.search",
    )
}

TOOLS = {
    "knowledge.list-memories": "app.knowledge.memories.read",
    "knowledge.read-memory": "app.knowledge.memories.read",
    "knowledge.save-memory": "app.knowledge.memories.write",
    "knowledge.list-entities": "app.knowledge.entities.list",
    "knowledge.entity-types": "app.knowledge.entities.types",
    "knowledge.entity-relationships": "app.knowledge.entities.relationships",
    "knowledge.delete-memory": "app.knowledge.memories.delete",
    "knowledge.reindex-memory": "app.knowledge.memories.reindex",
    "knowledge.index-status": "app.knowledge.memories.index_status",
    "knowledge.optimize-content": "app.knowledge.memories.optimize",
    "knowledge.read-graph": "app.knowledge.graph.read",
    "knowledge.read-subgraph": "app.knowledge.graph.subgraph",
    "knowledge.search-project": "app.knowledge.search",
}
