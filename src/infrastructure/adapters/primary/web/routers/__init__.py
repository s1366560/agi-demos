"""FastAPI routers for the MemStack API."""

from src.infrastructure.adapters.primary.web.routers import (
    admin_dlq,
    ai_tools,
    auth,
    background_tasks,
    billing,
    data_export,
    enhanced_search,
    episodes,
    graph,
    llm_providers,
    maintenance,
    memories,
    notifications,
    project_sandbox,
    projects,
    recall,
    sandbox,
    schema,
    shares,
    support,
    tasks,
    tenants,
)

# agent_websocket is imported lazily to avoid circular imports
# with the new websocket module

__all__ = [
    "admin_dlq",
    "ai_tools",
    "auth",
    "background_tasks",
    "billing",
    "data_export",
    "enhanced_search",
    "episodes",
    "graph",
    "llm_providers",
    "maintenance",
    "memories",
    "notifications",
    "project_sandbox",
    "projects",
    "recall",
    "sandbox",
    "schema",
    "shares",
    "support",
    "tasks",
    "tenants",
]
