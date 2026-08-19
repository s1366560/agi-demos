"""Declarative service binding table for the DI composition root migration.

Iteration I1 of the full-pluginization roadmap migrates ``DIContainer``
accessors onto :class:`ServiceRegistry` (key/inject/dispose), grouped into
domain batches. Pure delegates bind to their sub-container *target path*
(``_memory.memory_service``) instead of the facade so the facade can later
switch to registry delegation without recursion; main-class accessors with
real logic bind to the facade itself and remain the implementation.

Parameterized factories (``agent_service(llm)``, use cases taking ``llm``,
``react_loop``...) and constructor-injected properties (``graph_service``,
``redis_client``, ``neo4j_client``) are intentionally not service rows: the
former stay facade factories, the latter are constructor state.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from src.infrastructure.plugins.service_registry import (
    ServiceContext,
    ServiceDeclaration,
    ServiceDependencyError,
    ServiceRegistry,
)

__all__ = [
    "BINDING_GROUPS",
    "CONTAINER_SERVICE_BINDINGS",
    "ContainerServiceBinding",
    "declare_container_services",
]

_OWNER = "di-container"


@dataclass(frozen=True)
class ContainerServiceBinding:
    """Map one zero-arg container accessor onto a service key."""

    key: str
    group: str
    target: str  # facade method name, or "_sub.delegate" path for pure delegates
    inject: tuple[str, ...] = ()
    allow_none: bool = False  # accessor legitimately returns None when unconfigured


BINDING_GROUPS: tuple[str, ...] = (
    "infra",
    "memory",
    "auth",
    "task",
    "workspace",
    "instance",
    "agent",
)

CONTAINER_SERVICE_BINDINGS: tuple[ContainerServiceBinding, ...] = (
    # --- infra ---
    ContainerServiceBinding(
        key="ai_service_factory", group="infra", target="ai_service_factory", inject=()
    ),
    ContainerServiceBinding(
        key="redis", group="infra", target="_infra.redis", inject=(), allow_none=True
    ),
    ContainerServiceBinding(
        key="sequence_service",
        group="infra",
        target="_infra.sequence_service",
        inject=(),
        allow_none=True,
    ),
    ContainerServiceBinding(
        key="hitl_message_bus",
        group="infra",
        target="_infra.hitl_message_bus",
        inject=(),
        allow_none=True,
    ),
    ContainerServiceBinding(
        key="agent_message_bus",
        group="infra",
        target="_infra.agent_message_bus",
        inject=(),
        allow_none=True,
    ),
    ContainerServiceBinding(
        key="storage_service", group="infra", target="_infra.storage_service", inject=()
    ),
    ContainerServiceBinding(
        key="distributed_lock_adapter",
        group="infra",
        target="_infra.distributed_lock_adapter",
        inject=(),
        allow_none=True,
    ),
    ContainerServiceBinding(
        key="workflow_engine_port",
        group="infra",
        target="_infra.workflow_engine_port",
        inject=(),
        allow_none=True,
    ),
    ContainerServiceBinding(
        key="sandbox_adapter", group="infra", target="_infra.sandbox_adapter", inject=()
    ),
    ContainerServiceBinding(
        key="sandbox_event_publisher",
        group="infra",
        target="_infra.sandbox_event_publisher",
        inject=(),
    ),
    # --- memory ---
    ContainerServiceBinding(
        key="memory_repository", group="memory", target="_memory.memory_repository", inject=()
    ),
    ContainerServiceBinding(
        key="memory_service", group="memory", target="_memory.memory_service", inject=()
    ),
    ContainerServiceBinding(
        key="search_service", group="memory", target="_memory.search_service", inject=()
    ),
    ContainerServiceBinding(
        key="create_memory_use_case",
        group="memory",
        target="_memory.create_memory_use_case",
        inject=(),
    ),
    ContainerServiceBinding(
        key="get_memory_use_case", group="memory", target="_memory.get_memory_use_case", inject=()
    ),
    ContainerServiceBinding(
        key="list_memories_use_case",
        group="memory",
        target="_memory.list_memories_use_case",
        inject=(),
    ),
    ContainerServiceBinding(
        key="delete_memory_use_case",
        group="memory",
        target="_memory.delete_memory_use_case",
        inject=(),
    ),
    ContainerServiceBinding(
        key="search_memory_use_case",
        group="memory",
        target="_memory.search_memory_use_case",
        inject=(),
    ),
    # --- auth ---
    ContainerServiceBinding(
        key="user_repository", group="auth", target="_auth.user_repository", inject=()
    ),
    ContainerServiceBinding(
        key="api_key_repository", group="auth", target="_auth.api_key_repository", inject=()
    ),
    ContainerServiceBinding(
        key="tenant_repository", group="auth", target="_auth.tenant_repository", inject=()
    ),
    # --- task ---
    ContainerServiceBinding(
        key="task_repository", group="task", target="_task.task_repository", inject=()
    ),
    ContainerServiceBinding(
        key="task_service", group="task", target="_task.task_service", inject=()
    ),
    ContainerServiceBinding(
        key="create_task_use_case", group="task", target="_task.create_task_use_case", inject=()
    ),
    ContainerServiceBinding(
        key="get_task_use_case", group="task", target="_task.get_task_use_case", inject=()
    ),
    ContainerServiceBinding(
        key="list_tasks_use_case", group="task", target="_task.list_tasks_use_case", inject=()
    ),
    ContainerServiceBinding(
        key="update_task_use_case", group="task", target="_task.update_task_use_case", inject=()
    ),
    ContainerServiceBinding(
        key="cron_job_service", group="task", target="_cron.cron_job_service", inject=()
    ),
    ContainerServiceBinding(
        key="reflection_runner", group="task", target="reflection_runner", inject=("redis",)
    ),
    # --- workspace ---
    ContainerServiceBinding(
        key="project_repository", group="workspace", target="_project.project_repository", inject=()
    ),
    ContainerServiceBinding(
        key="project_service", group="workspace", target="_project.project_service", inject=()
    ),
    ContainerServiceBinding(
        key="tenant_service", group="workspace", target="_project.tenant_service", inject=()
    ),
    ContainerServiceBinding(
        key="workspace_repository",
        group="workspace",
        target="_project.workspace_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="workspace_member_repository",
        group="workspace",
        target="_project.workspace_member_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="workspace_agent_repository",
        group="workspace",
        target="_project.workspace_agent_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="blackboard_repository",
        group="workspace",
        target="_project.blackboard_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="blackboard_service", group="workspace", target="_project.blackboard_service", inject=()
    ),
    ContainerServiceBinding(
        key="blackboard_file_repository",
        group="workspace",
        target="_project.blackboard_file_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="blackboard_file_service",
        group="workspace",
        target="_project.blackboard_file_service",
        inject=(),
    ),
    ContainerServiceBinding(
        key="workspace_task_repository",
        group="workspace",
        target="_project.workspace_task_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="workspace_task_session_attempt_repository",
        group="workspace",
        target="_project.workspace_task_session_attempt_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="workspace_task_session_attempt_service",
        group="workspace",
        target="_project.workspace_task_session_attempt_service",
        inject=(),
    ),
    ContainerServiceBinding(
        key="topology_repository",
        group="workspace",
        target="_project.topology_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="topology_service", group="workspace", target="_project.topology_service", inject=()
    ),
    ContainerServiceBinding(
        key="cyber_objective_repository",
        group="workspace",
        target="_project.cyber_objective_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="cyber_gene_repository",
        group="workspace",
        target="_project.cyber_gene_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="workspace_orchestrator", group="workspace", target="workspace_orchestrator", inject=()
    ),
    # --- instance ---
    ContainerServiceBinding(
        key="instance_repository",
        group="instance",
        target="_instance.instance_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="instance_member_repository",
        group="instance",
        target="_instance.instance_member_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="deploy_record_repository",
        group="instance",
        target="_instance.deploy_record_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="cluster_repository", group="instance", target="_instance.cluster_repository", inject=()
    ),
    ContainerServiceBinding(
        key="gene_repository", group="instance", target="_instance.gene_repository", inject=()
    ),
    ContainerServiceBinding(
        key="genome_repository", group="instance", target="_instance.genome_repository", inject=()
    ),
    ContainerServiceBinding(
        key="instance_gene_repository",
        group="instance",
        target="_instance.instance_gene_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="gene_rating_repository",
        group="instance",
        target="_instance.gene_rating_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="gene_review_repository",
        group="instance",
        target="_instance.gene_review_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="evolution_event_repository",
        group="instance",
        target="_instance.evolution_event_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="instance_template_repository",
        group="instance",
        target="_instance.instance_template_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="instance_service", group="instance", target="_instance.instance_service", inject=()
    ),
    ContainerServiceBinding(
        key="deploy_service", group="instance", target="_instance.deploy_service", inject=()
    ),
    ContainerServiceBinding(
        key="cluster_service", group="instance", target="_instance.cluster_service", inject=()
    ),
    ContainerServiceBinding(
        key="gene_service", group="instance", target="_instance.gene_service", inject=()
    ),
    ContainerServiceBinding(
        key="instance_template_service",
        group="instance",
        target="_instance.instance_template_service",
        inject=(),
    ),
    ContainerServiceBinding(
        key="instance_file_service",
        group="instance",
        target="_instance.instance_file_service",
        inject=(),
    ),
    ContainerServiceBinding(
        key="instance_channel_service",
        group="instance",
        target="_instance.instance_channel_service",
        inject=(),
    ),
    # --- agent ---
    ContainerServiceBinding(
        key="conversation_repository",
        group="agent",
        target="_agent.conversation_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="agent_execution_repository",
        group="agent",
        target="_agent.agent_execution_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="tool_execution_record_repository",
        group="agent",
        target="_agent.tool_execution_record_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="agent_execution_event_repository",
        group="agent",
        target="_agent.agent_execution_event_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="execution_checkpoint_repository",
        group="agent",
        target="_agent.execution_checkpoint_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="workflow_pattern_repository",
        group="agent",
        target="_agent.workflow_pattern_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="context_summary_adapter",
        group="agent",
        target="_agent.context_summary_adapter",
        inject=(),
    ),
    ContainerServiceBinding(
        key="tool_composition_repository",
        group="agent",
        target="_agent.tool_composition_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="tool_environment_variable_repository",
        group="agent",
        target="_agent.tool_environment_variable_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="hitl_request_repository",
        group="agent",
        target="_agent.hitl_request_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="tenant_agent_config_repository",
        group="agent",
        target="_agent.tenant_agent_config_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="skill_repository", group="agent", target="_agent.skill_repository", inject=()
    ),
    ContainerServiceBinding(
        key="skill_version_repository",
        group="agent",
        target="_agent.skill_version_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="tenant_skill_config_repository",
        group="agent",
        target="_agent.tenant_skill_config_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="subagent_repository", group="agent", target="_agent.subagent_repository", inject=()
    ),
    ContainerServiceBinding(
        key="subagent_template_repository",
        group="agent",
        target="_agent.subagent_template_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="agent_registry", group="agent", target="_agent.agent_registry", inject=()
    ),
    ContainerServiceBinding(
        key="agent_binding_repository",
        group="agent",
        target="_agent.agent_binding_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="binding_router", group="agent", target="_agent.binding_router", inject=()
    ),
    ContainerServiceBinding(
        key="attachment_repository", group="agent", target="_agent.attachment_repository", inject=()
    ),
    ContainerServiceBinding(
        key="attachment_service", group="agent", target="_agent.attachment_service", inject=()
    ),
    ContainerServiceBinding(
        key="artifact_service", group="agent", target="_agent.artifact_service", inject=()
    ),
    ContainerServiceBinding(
        key="skill_service", group="agent", target="_agent.skill_service", inject=()
    ),
    ContainerServiceBinding(
        key="workspace_manager", group="agent", target="_agent.workspace_manager", inject=()
    ),
    ContainerServiceBinding(
        key="agent_session_registry",
        group="agent",
        target="_agent.agent_session_registry",
        inject=(),
    ),
    ContainerServiceBinding(
        key="spawn_manager", group="agent", target="_agent.spawn_manager", inject=()
    ),
    ContainerServiceBinding(
        key="subagent_run_registry", group="agent", target="_agent.subagent_run_registry", inject=()
    ),
    ContainerServiceBinding(
        key="agent_orchestrator", group="agent", target="_agent.agent_orchestrator", inject=()
    ),
    ContainerServiceBinding(
        key="graph_repository", group="agent", target="_agent.graph_repository", inject=()
    ),
    ContainerServiceBinding(
        key="graph_run_repository", group="agent", target="_agent.graph_run_repository", inject=()
    ),
    ContainerServiceBinding(
        key="graph_orchestrator", group="agent", target="_agent.graph_orchestrator", inject=()
    ),
    ContainerServiceBinding(
        key="event_converter", group="agent", target="_agent.event_converter", inject=()
    ),
    ContainerServiceBinding(
        key="attachment_processor", group="agent", target="_agent.attachment_processor", inject=()
    ),
    ContainerServiceBinding(
        key="artifact_extractor", group="agent", target="_agent.artifact_extractor", inject=()
    ),
    ContainerServiceBinding(
        key="message_builder", group="agent", target="_agent.message_builder", inject=()
    ),
    ContainerServiceBinding(
        key="attachment_injector", group="agent", target="_agent.attachment_injector", inject=()
    ),
    ContainerServiceBinding(
        key="find_similar_pattern_use_case",
        group="agent",
        target="_agent.find_similar_pattern_use_case",
        inject=(),
    ),
    ContainerServiceBinding(
        key="learn_pattern_use_case",
        group="agent",
        target="_agent.learn_pattern_use_case",
        inject=(),
    ),
    ContainerServiceBinding(
        key="workflow_learner", group="agent", target="_agent.workflow_learner", inject=()
    ),
    ContainerServiceBinding(
        key="span_service", group="agent", target="_agent.span_service", inject=()
    ),
    ContainerServiceBinding(
        key="fork_merge_service", group="agent", target="_agent.fork_merge_service", inject=()
    ),
    ContainerServiceBinding(
        key="layered_tool_policy_service",
        group="agent",
        target="_agent.layered_tool_policy_service",
        inject=(),
    ),
    ContainerServiceBinding(
        key="default_message_router",
        group="agent",
        target="_agent.default_message_router",
        inject=(),
    ),
    ContainerServiceBinding(
        key="message_binding_repository",
        group="agent",
        target="_agent.message_binding_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="agent_router_service", group="agent", target="_agent.agent_router_service", inject=()
    ),
    ContainerServiceBinding(
        key="redis_agent_namespace", group="agent", target="_agent.redis_agent_namespace", inject=()
    ),
    ContainerServiceBinding(
        key="redis_agent_credential_scope",
        group="agent",
        target="_agent.redis_agent_credential_scope",
        inject=(),
    ),
    ContainerServiceBinding(
        key="project_sandbox_repository",
        group="agent",
        target="_sandbox.project_sandbox_repository",
        inject=(),
    ),
    ContainerServiceBinding(
        key="sandbox_orchestrator", group="agent", target="_sandbox.sandbox_orchestrator", inject=()
    ),
    ContainerServiceBinding(
        key="sandbox_tool_registry",
        group="agent",
        target="_sandbox.sandbox_tool_registry",
        inject=(),
    ),
    ContainerServiceBinding(
        key="sandbox_resource", group="agent", target="_sandbox.sandbox_resource", inject=()
    ),
    ContainerServiceBinding(
        key="project_sandbox_lifecycle_service",
        group="agent",
        target="_sandbox.project_sandbox_lifecycle_service",
        inject=(),
    ),
    ContainerServiceBinding(
        key="sandbox_mcp_server_manager",
        group="agent",
        target="_sandbox.sandbox_mcp_server_manager",
        inject=(),
    ),
    ContainerServiceBinding(
        key="mcp_app_service", group="agent", target="_sandbox.mcp_app_service", inject=()
    ),
    ContainerServiceBinding(
        key="mcp_runtime_service", group="agent", target="_sandbox.mcp_runtime_service", inject=()
    ),
    ContainerServiceBinding(
        key="dependency_orchestrator",
        group="agent",
        target="_sandbox.dependency_orchestrator",
        inject=(),
    ),
    ContainerServiceBinding(
        key="skill_evolution_plugin",
        group="agent",
        target="skill_evolution_plugin",
        inject=("skill_service",),
        allow_none=True,
    ),
    ContainerServiceBinding(
        key="event_log_repository", group="agent", target="event_log_repository", inject=()
    ),
    ContainerServiceBinding(
        key="event_log_service",
        group="agent",
        target="event_log_service",
        inject=("event_log_repository",),
    ),
    ContainerServiceBinding(
        key="webhook_repository", group="agent", target="webhook_repository", inject=()
    ),
    ContainerServiceBinding(
        key="webhook_service",
        group="agent",
        target="webhook_service",
        inject=("webhook_repository",),
    ),
)


def declare_container_services(
    registry: ServiceRegistry,
    container: object,
    *,
    groups: Iterable[str] | None = None,
    replace: bool = False,
) -> tuple[str, ...]:
    """Declare container accessors as lazy services and return declared keys.

    Declarations are lazy: nothing is constructed until ``get_or_activate``
    or ``activate_all``. The registry caches per *registry* instance, so a
    request-scoped container (``with_db``) caches per request while the
    process-global container caches singletons, matching facade semantics.
    """
    selected = set(groups) if groups is not None else None
    declared: list[str] = []
    for binding in CONTAINER_SERVICE_BINDINGS:
        if selected is not None and binding.group not in selected:
            continue
        registry.declare(
            ServiceDeclaration(
                key=binding.key,
                factory=_binding_factory(container, binding),
                inject=binding.inject,
                owner=_OWNER,
                allow_none=binding.allow_none,
            ),
            replace=replace,
        )
        declared.append(binding.key)
    return tuple(declared)


def _binding_factory(
    container: object, binding: ContainerServiceBinding
) -> Callable[[ServiceContext], object]:
    target = binding.target

    def factory(_ctx: ServiceContext) -> object:
        if "." in target:
            sub_name, method_name = target.split(".", 1)
            sub = getattr(container, sub_name, None)
            method = getattr(sub, method_name, None)
        else:
            method = getattr(container, target, None)
        if not callable(method):
            raise ServiceDependencyError(
                f"container binding {binding.key} has no callable target {target}"
            )
        return method()

    return factory
