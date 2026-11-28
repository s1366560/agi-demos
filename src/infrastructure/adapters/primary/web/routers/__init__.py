"""FastAPI route modules are imported individually by their contributing package."""

from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import (
        acp,
        admin_dlq,
        ai_tools,
        auth,
        background_tasks,
        blackboard,
        clusters,
        data_export,
        deploy,
        enhanced_search,
        episodes,
        genes,
        graph,
        instance_channels,
        instance_files,
        instance_templates,
        instances,
        llm_providers,
        maintenance,
        memories,
        notifications,
        project_sandbox,
        projects,
        recall,
        reflection,
        sandbox,
        schema,
        shares,
        support,
        tasks,
        tenants,
        topology,
        workspace_autonomy,
        workspace_plans,
        workspace_tasks,
        workspaces,
    )

__all__ = [
    "acp",
    "admin_dlq",
    "ai_tools",
    "auth",
    "background_tasks",
    "blackboard",
    "clusters",
    "data_export",
    "deploy",
    "enhanced_search",
    "episodes",
    "genes",
    "graph",
    "instance_channels",
    "instance_files",
    "instance_templates",
    "instances",
    "llm_providers",
    "maintenance",
    "memories",
    "notifications",
    "project_sandbox",
    "projects",
    "recall",
    "reflection",
    "sandbox",
    "schema",
    "shares",
    "support",
    "tasks",
    "tenants",
    "topology",
    "workspace_autonomy",
    "workspace_plans",
    "workspace_tasks",
    "workspaces",
]


def __getattr__(name: str) -> ModuleType:
    if name not in __all__:
        raise AttributeError(name)
    return import_module(f".{name}", __name__)
