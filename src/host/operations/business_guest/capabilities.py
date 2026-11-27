"""Host capabilities for business command guests.

These functions run in the host, after the guest has been admitted. They are not
package operations invoked in-process.
"""

from __future__ import annotations

from typing import Any

from plugins.business.automation.backend.pattern_operations import PATTERN_OPERATIONS
from plugins.business.automation.backend.playbook_operation import read_playbooks, read_verdicts
from plugins.business.automation.backend.schedule_operations import SCHEDULE_OPERATIONS
from plugins.business.automation.backend.tenant_automation_operations import (
    TENANT_AUTOMATION_OPERATIONS,
)
from plugins.business.billing.backend.account_operations import BILLING_OPERATIONS
from plugins.business.environments.backend.cluster_operations import delete_cluster, write_cluster
from plugins.business.environments.backend.cluster_runner_operations import (
    create_pool,
    issue_token,
    list_pools,
)
from plugins.business.environments.backend.deploy_operations import change_deploy, read_deploys
from plugins.business.environments.backend.instance_template_operations import (
    change_template,
    create_instance,
    read_templates,
)
from plugins.business.environments.backend.interaction_channel import (
    project_desktop,
    project_terminal,
)
from plugins.business.environments.backend.inventory_operations import inventory
from plugins.business.environments.backend.package_sandbox_operations import SANDBOX_OPERATIONS
from plugins.business.environments.backend.pool_operations import control, read, set_tier
from plugins.business.knowledge.backend.entity_queries import ENTITY_OPERATIONS
from plugins.business.knowledge.backend.graph_queries import read_graph, read_subgraph
from plugins.business.knowledge.backend.memory_maintenance import (
    delete_memory,
    optimize_content,
    read_index_task,
    reindex_memory,
)
from plugins.business.knowledge.backend.package_memory_editor import save_memory
from plugins.business.knowledge.backend.project_memory_operation import list_project_memories
from plugins.business.knowledge.backend.project_search import search
from plugins.business.workspace.backend.blackboard_surface import change_surface, read_surface
from plugins.business.workspace.backend.collaboration import WORKSPACE_COLLABORATION_OPERATIONS
from plugins.business.workspace.backend.group_chat import read_chat, send_chat
from plugins.business.workspace.backend.project_overview import read_overview
from plugins.business.workspace.backend.workspace_directory_export import (
    create_workspace_operation,
    read_directory_operation,
    read_workspace_operation,
    update_workspace_operation,
)

CAPABILITIES: dict[str, Any] = {
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
    **PATTERN_OPERATIONS,
    **TENANT_AUTOMATION_OPERATIONS,
    **SCHEDULE_OPERATIONS,
    "app.automation.playbooks.read": read_playbooks,
    "app.automation.verdicts.read": read_verdicts,
    **SANDBOX_OPERATIONS,
    "app.environments.terminal.interact": project_terminal,
    "app.environments.desktop.interact": project_desktop,
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
    **BILLING_OPERATIONS,
}
