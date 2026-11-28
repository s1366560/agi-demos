"""Deployment-owned cloud application operations for the signed environments package."""

from collections.abc import Mapping
from typing import Any

from src.host.operations.deployment_adapters import ApplicationAdapter, provide_application_adapter
from src.infrastructure.plugins.v2.runtime_context import ContextV2

from .cluster_operations import delete_cluster, write_cluster
from .cluster_runner_operations import create_pool, issue_token, list_pools
from .deploy_operations import change_deploy, read_deploys
from .instance_template_operations import change_template, create_instance, read_templates
from .interaction_channel import project_desktop, project_terminal
from .inventory_operations import inventory
from .package_sandbox_operations import SANDBOX_OPERATIONS
from .pool_operations import control, read, set_tier


def apply(ctx: ContextV2, _config: Mapping[str, Any]) -> None:
    provide_application_adapter(
        ctx,
        ApplicationAdapter(
            plugin_id="memstack-environments",
            tenant={
                "app.environments.pool.read": read,
                "app.environments.pool.control": control,
                "app.environments.pool.tier": set_tier,
                "app.environments.deploys.read": read_deploys,
                "app.environments.deploys.write": change_deploy,
                "app.environments.templates.read": read_templates,
                "app.environments.templates.write": change_template,
                "app.environments.instances.create": create_instance,
                "app.environments.inventory.read": inventory,
                "app.environments.runners.read": list_pools,
                "app.environments.runners.create": create_pool,
                "app.environments.runners.register": issue_token,
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
