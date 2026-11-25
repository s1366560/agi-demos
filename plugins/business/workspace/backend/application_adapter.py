"""Deployment-owned cloud application operations for the signed workspace package."""

from collections.abc import Mapping
from typing import Any

from src.host.operations.deployment_adapters import ApplicationAdapter, provide_application_adapter
from src.infrastructure.plugins.v2.runtime_context import ContextV2

from .blackboard_surface import change_surface, read_surface
from .collaboration import WORKSPACE_COLLABORATION_OPERATIONS
from .group_chat import read_chat, send_chat
from .project_overview import read_overview
from .workspace_directory_export import (
    create_workspace_operation,
    read_directory_operation,
    read_workspace_operation,
    update_workspace_operation,
)


def apply(ctx: ContextV2, _config: Mapping[str, Any]) -> None:
    provide_application_adapter(
        ctx,
        ApplicationAdapter(
            plugin_id="memstack-workspace",
            project={
                **WORKSPACE_COLLABORATION_OPERATIONS,
                "app.workspace.chat.read": read_chat,
                "app.workspace.chat.send": send_chat,
                "app.workspace.overview.read": read_overview,
                "app.workspace.blackboard.read": read_surface,
                "app.workspace.blackboard.write": change_surface,
                "app.workspace.create": create_workspace_operation,
                "app.workspace.settings.update": update_workspace_operation,
                "app.workspace.directory.read": read_directory_operation,
                "app.workspace.detail.read": read_workspace_operation,
            },
        ),
    )
