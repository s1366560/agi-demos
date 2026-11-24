"""Deployment-owned cloud application operations for the signed environments package."""

from collections.abc import Mapping
from typing import Any

from src.host.operations.deployment_adapters import ApplicationAdapter, provide_application_adapter
from src.infrastructure.plugins.v2.runtime_context import ContextV2

from .cluster_operations import delete_cluster, write_cluster
from .interaction_channel import project_desktop, project_terminal
from .inventory_operations import inventory
from .package_sandbox_operations import SANDBOX_OPERATIONS


def apply(ctx: ContextV2, _config: Mapping[str, Any]) -> None:
    provide_application_adapter(
        ctx,
        ApplicationAdapter(
            plugin_id="memstack-environments",
            tenant={
                "app.environments.inventory.read": inventory,
                "app.environments.clusters.write": write_cluster,
                "app.environments.clusters.delete": delete_cluster,
            },
            project={
                **SANDBOX_OPERATIONS,
                "app.environments.terminal.interact": project_terminal,
                "app.environments.desktop.interact": project_desktop,
            },
        ),
    )
