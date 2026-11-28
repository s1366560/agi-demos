"""Map admitted command names onto guest shapers."""

from __future__ import annotations

from plugins.business.knowledge.guest.commands import OPERATIONS

__all__ = ["OPERATIONS", "TOOLS"]

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
