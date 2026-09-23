# pyright: reportUninitializedInstanceVariable=false
"""Stream-pipeline mixin extracted from ``react_agent.py``.

Hosts the private ``_stream_*`` orchestration helpers that the public
:meth:`ReActAgent.stream` coroutine drives. Pure code move — no behavior
change. ``ReActAgent`` composes this mixin via multiple inheritance.

Out of scope (deferred):
- ``stream`` itself (HIGH risk, requires dedicated commit)
- ``_stream_inject_subagent_tools`` (strongly coupled to subagent runner;
  belongs with PR-7d)
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Protocol, cast
from uuid import uuid4

from src.domain.events.agent_events import (
    AgentCompleteEvent,
    AgentContextCompressedEvent,
    AgentContextStatusEvent,
    AgentContextSummaryGeneratedEvent,
    AgentDomainEvent,
    AgentErrorEvent,
    AgentPlanSuggestedEvent,
    AgentPolicyFilteredEvent,
    AgentSelectionTraceEvent,
    AgentSkillExecutionCompleteEvent,
    AgentSkillExecutionStartEvent,
    AgentSkillMatchedEvent,
    AgentThoughtEvent,
)
from src.domain.model.agent.skill import Skill
from src.domain.ports.agent.context_manager_port import ContextBuildRequest
from src.infrastructure.agent.model_route import ModelRouteRef
from src.infrastructure.plugins.v2.agent_capabilities import AgentCapabilitySetV2
from src.infrastructure.plugins.v2.agent_operation_tool_contributions import (
    OPERATION_SUBAGENT_TOOL_SOURCE_V2,
    SkillMCPManagerProtocolV2,
    activate_skill_mcp_operation_tools_v2,
    contribute_operation_tool_definitions_v2,
    parse_skill_mcp_configs_v2,
)
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error
from src.infrastructure.plugins.v2.tool_set import (
    ToolSetContributionCatalogProtocolV2,
    ToolSetV2,
    bind_operation_tool_set_catalog_v2,
    bind_prepared_tool_provider_v2,
    restrict_tool_set_v2,
)

from ..i18n import directive_for, resolve_response_language
from ..plugins.selection_pipeline import ToolSelectionContext, ToolSelectionTraceStep
from ..routing import ExecutionPath, RoutingDecision
from ..skill import SkillProtocol
from ..workspace.runtime_role_contract import (
    WORKSPACE_ROLE_CONTRACT,
    WORKSPACE_ROLE_LEADER,
    WORKSPACE_SESSION_ROLE_KEY,
    WORKSPACE_TOOL_MODE_KEY,
    WORKSPACE_TURN_TYPE_KEY,
)
from ..workspace.workspace_metadata_keys import (
    ACTIVE_EXECUTION_ROOT,
    ATTEMPT_WORKTREE,
    PREFERRED_LANGUAGE,
    WORKTREE_SETUP,
)

# Runtime imports (not TYPE_CHECKING) — used to construct values inside ``stream``.
from .processor import ToolDefinition
from .react_agent_profile import (
    _register_selected_agent_session,
)
from .react_agent_tool_policy import (
    filter_non_workspace_conversation_tools,
    filter_tools_by_name_policy,
    filter_workspace_root_tools,
)
from .subagent_tool_set_v2 import SubAgentToolSetBindingV2

if TYPE_CHECKING:
    from .processor import ProcessorConfig, SessionProcessor

logger = logging.getLogger(__name__)


def _resolve_model_route_override(
    *,
    model_override: str | None,
    model_route_override: ModelRouteRef | None,
) -> ModelRouteRef | None:
    """Validate that a model override carries explicit provider identity."""
    normalized_model_override = (model_override or "").strip() or None
    if model_route_override is None:
        if normalized_model_override is not None:
            raise RuntimeV2Error(
                "model_override_route_missing",
                f"model override {normalized_model_override} has no provider route",
            )
        return None
    if (
        normalized_model_override is not None
        and model_route_override.model_id != normalized_model_override
    ):
        raise RuntimeV2Error(
            "model_override_route_mismatch",
            f"model override {normalized_model_override} does not match route model "
            f"{model_route_override.model_id}",
        )
    return model_route_override


def _provider_config_matches_exact_route(provider: object, route: ModelRouteRef) -> bool:
    """Return whether one active LLM config exactly owns a route identity."""
    if not bool(getattr(provider, "is_active", False)) or not bool(
        getattr(provider, "is_enabled", False)
    ):
        return False
    provider_type = getattr(provider, "provider_type", "")
    provider_id = str(getattr(provider_type, "value", provider_type)).strip()
    if route.provider_id not in {provider_id, str(getattr(provider, "id", ""))}:
        return False
    operation_type = getattr(provider, "operation_type", "llm")
    operation_id = str(getattr(operation_type, "value", operation_type)).strip()
    if operation_id != "llm":
        return False
    is_model_allowed = getattr(provider, "is_model_allowed", None)
    return callable(is_model_allowed) and bool(is_model_allowed(route.model_id))


async def _resolve_exact_provider_config_for_route(
    *,
    tenant_id: str,
    route: ModelRouteRef,
) -> Any:
    """Resolve one provider config by exact explicit identity, without model inference."""
    from src.application.services.provider_resolution_service import (
        get_provider_resolution_service,
    )
    from src.domain.llm_providers.models import OperationType

    repository = get_provider_resolution_service().repository
    if tenant_id:
        tenant_provider = await repository.find_tenant_provider(tenant_id, OperationType.LLM)
        if tenant_provider is not None and _provider_config_matches_exact_route(
            tenant_provider,
            route,
        ):
            return tenant_provider

    default_provider = await repository.find_default_provider(OperationType.LLM)
    if default_provider is not None and _provider_config_matches_exact_route(
        default_provider,
        route,
    ):
        return default_provider

    active_providers = await repository.list_active()
    candidates: dict[str, Any] = {}
    for provider in active_providers:
        if not _provider_config_matches_exact_route(provider, route):
            continue
        provider_identity = str(getattr(provider, "id", id(provider)))
        candidates[provider_identity] = provider
    if len(candidates) == 1:
        return next(iter(candidates.values()))
    if not candidates:
        raise RuntimeV2Error(
            "model_route_provider_unavailable",
            f"no active provider config matches route {route.provider_id}/{route.model_id}",
        )
    raise RuntimeV2Error(
        "model_route_provider_ambiguous",
        f"multiple active provider configs match route {route.provider_id}/{route.model_id}",
    )


async def _bind_processor_model_route(
    *,
    config: ProcessorConfig,
    route: ModelRouteRef,
    tenant_id: str,
    revalidate: bool = False,
) -> None:
    """Bind exact route identity and, when needed, its unambiguous LLM client."""
    if revalidate or config.provider_id.strip() != route.provider_id:
        from src.infrastructure.llm.provider_factory import get_ai_service_factory

        provider_config = await _resolve_exact_provider_config_for_route(
            tenant_id=tenant_id,
            route=route,
        )
        service_factory = get_ai_service_factory()
        config.llm_client = service_factory.create_llm_client(provider_config)
        config.api_key = ""
        config.base_url = provider_config.base_url
    config.provider_id = route.provider_id
    config.model = route.model_id


def _resolve_current_tools_from_runtime_v2(
    agent: object,
    selection_context: ToolSelectionContext,
    *,
    operation_catalog: ToolSetContributionCatalogProtocolV2,
) -> ToolSetV2:
    """Resolve tools through the required service in the pinned v2 operation."""
    from src.infrastructure.plugins.v2.boundary import current_operation_context_v2
    from src.infrastructure.plugins.v2.tool_set import (
        TOOL_SET_RESOLVER_SERVICE_V2,
        ToolSetResolverProtocolV2,
    )

    operation = current_operation_context_v2()
    resolver = operation.require(TOOL_SET_RESOLVER_SERVICE_V2)
    if not isinstance(resolver, ToolSetResolverProtocolV2):
        raise RuntimeError("v2 tool-set resolver has an invalid implementation")
    prepared_tool_provider = bind_prepared_tool_provider_v2(agent, operation)
    raw_tool_set: object = resolver.resolve(
        agent=agent,
        selection_context=selection_context,
        prepared_tool_provider=prepared_tool_provider,
        operation_catalog=operation_catalog,
    )
    if not isinstance(raw_tool_set, ToolSetV2):
        raise RuntimeV2Error(
            "invalid_tool_set",
            "service:tool-set-resolver returned an invalid immutable ToolSet",
        )
    return raw_tool_set


def _pin_selection_context_tools_v2(
    selection_context: ToolSelectionContext,
    tool_names: Sequence[str],
) -> ToolSelectionContext:
    """Return a context with stable, de-duplicated model-visible tool pins."""
    raw_existing = selection_context.metadata.get("skill_pinned_tools", ())
    existing = (
        raw_existing
        if isinstance(raw_existing, Sequence) and not isinstance(raw_existing, (str, bytes))
        else ()
    )
    pinned: list[str] = []
    for name in (*existing, *tool_names):
        if isinstance(name, str) and name and name not in pinned:
            pinned.append(name)
    if not pinned:
        return selection_context
    metadata = dict(selection_context.metadata)
    metadata["skill_pinned_tools"] = tuple(pinned)
    return replace(selection_context, metadata=metadata)


def _finalize_turn_tool_set_v2(
    tool_set: ToolSetV2,
    *,
    is_forced: bool,
    matched_skill: Skill | None,
    workspace_root_task: object | None,
    is_workspace_conversation: bool,
    allow_tools: Sequence[str] | None,
    deny_tools: Sequence[str] | None,
    forced_operation_tool_names: Sequence[str] = (),
) -> ToolSetV2:
    """Apply objective turn-scope filters once before every model consumer."""
    definitions = list(tool_set.definitions)
    before_names = tuple(definition.name for definition in definitions)

    if is_forced and matched_skill:
        skill_tools: set[str] = {
            name for name in matched_skill.tools if isinstance(name, str) and name
        }
        skill_tools.update(
            name for name in forced_operation_tool_names if isinstance(name, str) and name
        )
        if skill_tools:
            allowed = skill_tools | {"todowrite", "todoread"}
            definitions = [definition for definition in definitions if definition.name in allowed]
        else:
            definitions = [
                definition for definition in definitions if definition.name != "skill_loader"
            ]

    definitions = filter_workspace_root_tools(definitions, workspace_root_task)
    definitions = filter_non_workspace_conversation_tools(
        definitions,
        is_workspace_conversation=is_workspace_conversation,
    )
    definitions = filter_tools_by_name_policy(
        definitions,
        allow_tools=allow_tools,
        deny_tools=deny_tools,
    )

    after_names = tuple(definition.name for definition in definitions)
    selection_trace = tool_set.selection_trace
    if before_names != after_names:
        before_set = set(before_names)
        after_set = set(after_names)
        selection_trace = (
            *selection_trace,
            ToolSelectionTraceStep(
                stage="turn_scope_filter",
                before_count=len(before_names),
                after_count=len(after_names),
                removed_tools=tuple(sorted(before_set - after_set)),
                added_tools=tuple(sorted(after_set - before_set)),
                explain={
                    "forced_skill": bool(is_forced and matched_skill),
                    "workspace_root": workspace_root_task is not None,
                    "workspace_conversation": is_workspace_conversation,
                },
            ),
        )
    return restrict_tool_set_v2(
        tool_set,
        definitions,
        selection_trace=selection_trace,
    )


async def _resolve_agent_capabilities_from_runtime_v2(
    agent: object,
    *,
    tenant_id: str,
    project_id: str,
) -> AgentCapabilitySetV2:
    """Resolve Skills and SubAgents through the required pinned v2 service."""
    from src.infrastructure.plugins.v2.agent_capabilities import (
        AGENT_CAPABILITY_RESOLVER_SERVICE_V2,
        AgentCapabilityResolverProtocolV2,
    )
    from src.infrastructure.plugins.v2.boundary import current_operation_context_v2

    operation = current_operation_context_v2()
    resolver = operation.require(AGENT_CAPABILITY_RESOLVER_SERVICE_V2)
    if not isinstance(resolver, AgentCapabilityResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_capability_resolver",
            "service:agent-capability-resolver has an invalid implementation",
        )
    return await resolver.resolve(
        agent=agent,
        tenant_id=tenant_id,
        project_id=project_id,
    )


def _normalize_preferred_language(value: object) -> str | None:
    return value if isinstance(value, str) and value in {"en-US", "zh-CN"} else None


def _preferred_language_from_payload(payload: Mapping[str, Any] | None) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    return _normalize_preferred_language(payload.get(PREFERRED_LANGUAGE))


def _workspace_runtime_forwarded_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Forward non-identity workspace runtime fields needed by tools."""
    forwarded: dict[str, Any] = {}
    additional_instructions = payload.get("additional_instructions")
    if isinstance(additional_instructions, str) and additional_instructions.strip():
        forwarded["additional_instructions"] = additional_instructions
    root_override = payload.get("workspace_root_override")
    if isinstance(root_override, Mapping):
        forwarded["workspace_root_override"] = dict(root_override)
    attempt_worktree = payload.get(ATTEMPT_WORKTREE)
    if isinstance(attempt_worktree, Mapping):
        forwarded[ATTEMPT_WORKTREE] = dict(attempt_worktree)
    active_execution_root = payload.get(ACTIVE_EXECUTION_ROOT)
    if isinstance(active_execution_root, str) and active_execution_root.strip():
        forwarded[ACTIVE_EXECUTION_ROOT] = active_execution_root
    worktree_setup = payload.get(WORKTREE_SETUP)
    if isinstance(worktree_setup, Mapping):
        forwarded[WORKTREE_SETUP] = dict(worktree_setup)
    verification_integrity = payload.get("workspace_verification_integrity")
    if isinstance(verification_integrity, Mapping):
        forwarded["workspace_verification_integrity"] = dict(verification_integrity)
    return forwarded


def _workspace_runtime_limit_overrides(
    payload: Mapping[str, Any] | None,
) -> dict[str, int]:
    """Return positive runtime limit overrides from workspace app context."""
    if not isinstance(payload, Mapping):
        return {}
    if payload.get(WORKSPACE_SESSION_ROLE_KEY) != WORKSPACE_ROLE_CONTRACT:
        return {}
    raw_limits = payload.get("runtime_limits")
    if not isinstance(raw_limits, Mapping):
        return {}
    limits: dict[str, int] = {}
    value = raw_limits.get("max_tokens")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        limits["max_tokens"] = value
    return limits


def _selected_agent_can_spawn(selected_agent: Any | None) -> bool:
    if selected_agent is None:
        return True
    return bool(getattr(selected_agent, "can_spawn", True))


def _selected_agent_spawn_limits(
    selected_agent: Any | None,
    *,
    default_depth: int,
    default_active_runs: int,
    default_children_per_requester: int,
    default_active_runs_per_lineage: int,
) -> dict[str, int]:
    spawn_policy = (
        getattr(selected_agent, "spawn_policy", None) if selected_agent is not None else None
    )
    legacy_depth = getattr(selected_agent, "max_spawn_depth", default_depth)
    policy_depth = getattr(spawn_policy, "max_depth", legacy_depth)
    max_depth = min(default_depth, int(policy_depth))
    max_active_runs = min(
        default_active_runs,
        int(getattr(spawn_policy, "max_active_runs", default_active_runs)),
    )
    max_children_per_requester = min(
        default_children_per_requester,
        int(
            getattr(
                spawn_policy,
                "max_children_per_requester",
                default_children_per_requester,
            )
        ),
    )
    return {
        "max_delegation_depth": max_depth,
        "max_active_runs": max(1, max_active_runs),
        "max_active_runs_per_lineage": max(
            1, min(default_active_runs_per_lineage, max_active_runs)
        ),
        "max_children_per_requester": max(1, max_children_per_requester),
    }


def _filter_subagents_for_selected_agent_policy(
    enabled_subagents: list[Any],
    selected_agent: Any | None,
) -> list[Any]:
    spawn_policy = (
        getattr(selected_agent, "spawn_policy", None) if selected_agent is not None else None
    )
    allowed_subagents = getattr(spawn_policy, "allowed_subagents", None)
    if allowed_subagents is None:
        return enabled_subagents
    allowed = {str(item).strip() for item in allowed_subagents if str(item).strip()}
    if not allowed:
        return []
    return [
        subagent
        for subagent in enabled_subagents
        if any(
            str(identifier).strip() in allowed
            for identifier in (
                getattr(subagent, "id", None),
                getattr(subagent, "name", None),
                getattr(subagent, "display_name", None),
            )
            if identifier is not None
        )
    ]


class _StreamAgent(Protocol):
    """Subset of ``ReActAgent`` state used by :class:`StreamMixin`."""

    skills: Any
    agent_mode: Any
    skill_match_threshold: Any
    subagents: Any
    permission_manager: Any
    context_facade: Any
    config: Any
    model: Any
    _plan_detector: Any
    _resource_sync_service: Any
    _llm_client: Any
    _last_tool_selection_trace: Any
    _tool_selection_max_tools: Any
    _use_dynamic_tools: Any
    _tool_provider: Any
    _processor_factory: Any
    _heartbeat_runner: Any
    _max_subagent_delegation_depth: Any
    _max_subagent_active_runs: Any
    _max_subagent_children_per_requester: Any
    _max_subagent_active_runs_per_lineage: Any
    _enable_subagent_as_tool: Any
    _tool_builder: Any

    # mutable stream-phase state set by these helpers and consumed by ``stream``
    _stream_skill_state: Any
    _stream_context_result: Any
    _stream_messages: Any
    _stream_cached_summary: Any
    _stream_tools_to_use: Any
    _stream_final_content: Any
    _stream_execution_summary: dict[str, Any] | None
    _stream_success: Any

    # delegated methods (live on ReActAgent or sibling mixins)
    def _match_skill(
        self,
        query: str,
        available_skills: list[SkillProtocol] | None = None,
    ) -> tuple[SkillProtocol | None, float]: ...

    def _get_current_tools(
        self,
        selection_context: ToolSelectionContext | None = None,
    ) -> tuple[dict[str, Any], list[ToolDefinition]]: ...

    def _decide_execution_path(
        self,
        *,
        message: str,
        conversation_context: list[dict[str, str]],
        forced_subagent_name: str | None = ...,
        forced_skill_name: str | None = ...,
        plan_mode_requested: bool = ...,
    ) -> RoutingDecision: ...

    def _build_tool_selection_context(
        self,
        *,
        tenant_id: str,
        project_id: str,
        user_message: str,
        conversation_context: list[dict[str, str]],
        effective_mode: str,
        routing_metadata: Any = ...,
        allow_tools: list[str] | None = ...,
        deny_tools: list[str] | None = ...,
    ) -> ToolSelectionContext: ...

    def _extract_sandbox_id_from_tools(self, *, tool_set: ToolSetV2) -> str | None: ...

    def _convert_domain_event(
        self,
        domain_event: AgentDomainEvent | dict[str, Any],
        *,
        agent_id: str | None = ...,
    ) -> dict[str, Any] | None: ...

    async def _notify_context_overflow_hook(
        self,
        *,
        tenant_id: str,
        project_id: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        context_result: Any,
    ) -> list[dict[str, Any]]: ...

    async def _notify_after_turn_complete_hook(
        self,
        *,
        processed_user_message: str,
        final_content: str,
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        matched_skill: Skill | None,
        success: bool,
        execution_time_ms: int = ...,
        tool_call_count: int = ...,
        llm_client_override: Any | None = ...,
    ) -> list[dict[str, Any]]: ...

    # Methods used by ``stream`` and ``_stream_inject_subagent_tools``;
    # live on ReActAgent or sibling mixins.
    def _reset_stream_state(self) -> None: ...

    async def _load_filesystem_skills(self, tenant_id: str, project_id: str) -> None: ...

    async def _load_selected_agent(
        self,
        *,
        agent_id: str,
        tenant_id: str,
        project_id: str,
    ) -> Any: ...

    def _build_runtime_profile(
        self,
        *,
        tenant_id: str,
        tenant_agent_config_data: dict[str, Any] | None,
        selected_agent: Any,
        selected_agent_model_route: ModelRouteRef | None,
        is_workspace_worker_runtime: bool,
        available_skills: Sequence[Skill],
    ) -> Any: ...

    def _with_workspace_leader_replan_tool_allowlist(self, runtime_profile: Any) -> Any: ...

    def _with_workspace_worker_tool_allowlist(self, runtime_profile: Any) -> Any: ...

    def _build_runtime_workspace_manager(self, selected_agent: Any) -> Any: ...

    async def _apply_before_prompt_build_hook(
        self,
        *,
        processed_user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        effective_mode: str,
        matched_skill: Skill | None,
        selected_agent: Any,
    ) -> tuple[Any, list[dict[str, Any]]]: ...

    def _build_primary_agent_prompt(
        self,
        *,
        runtime_profile: Any,
        selection_context: ToolSelectionContext,
        tool_set: ToolSetV2,
        available_subagents: Sequence[Any],
    ) -> str: ...

    async def _build_system_prompt(self, *args: Any, **kwargs: Any) -> str: ...

    @classmethod
    def _filter_workspace_root_tools(
        cls,
        tools_to_use: list[ToolDefinition],
        workspace_root_task: Any | None,
    ) -> list[ToolDefinition]: ...

    @staticmethod
    def _filter_tools_by_name_policy(
        tools_to_use: list[ToolDefinition],
        *,
        allow_tools: Any,
        deny_tools: Any,
    ) -> list[ToolDefinition]: ...

    @classmethod
    def _workspace_runtime_context(cls, conversation_context: Any) -> Any: ...

    @staticmethod
    def _is_workspace_leader_replan_context(payload: Any) -> bool: ...

    @staticmethod
    def _normalize_workspace_binding(raw: Any) -> dict[str, str] | None: ...

    @classmethod
    def _workspace_binding_from_text(cls, text: str | None) -> dict[str, str] | None: ...

    async def _inject_lane_jit_guidance(
        self,
        *,
        processor: Any,
        tenant_id: str,
        project_id: str,
        workspace_task: Any,
    ) -> None: ...

    def _execute_subagent(self, *args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]: ...

    async def _launch_subagent_session(self, *args: Any, **kwargs: Any) -> Any: ...

    async def _cancel_subagent_session(self, run_id: str) -> bool: ...

    def _build_subagent_tool_definitions(
        self, *args: Any, **kwargs: Any
    ) -> list[ToolDefinition]: ...

    # Sibling helpers within ``StreamMixin`` itself (declared here so that
    # ``stream`` can call them through ``self: _StreamAgent`` under strict
    # type checking).
    def _stream_detect_plan_mode(
        self, user_message: str, conversation_id: str
    ) -> AsyncIterator[dict[str, Any]]: ...

    def _stream_parse_forced_subagent(self, user_message: str) -> tuple[str | None, str]: ...

    def _stream_decide_route(
        self, *args: Any, **kwargs: Any
    ) -> tuple[RoutingDecision, str, str, dict[str, Any], str | None, dict[str, Any]]: ...

    def _stream_match_skill(self, *args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]: ...

    async def _stream_sync_skill_resources(
        self,
        matched_skill: Skill,
        *,
        tool_set: ToolSetV2,
    ) -> None: ...

    def _stream_resolve_mode(
        self, *args: Any, **kwargs: Any
    ) -> tuple[str, ToolSelectionContext]: ...

    def _stream_build_context(self, *args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]: ...

    def _stream_prepare_tools(self, *args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]: ...

    def _stream_inject_subagent_tools(self, *args: Any, **kwargs: Any) -> list[ToolDefinition]: ...

    def _stream_create_processor_config(self, *args: Any, **kwargs: Any) -> ProcessorConfig: ...

    def _stream_process_events(
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]: ...

    def _stream_post_process(self, *args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]: ...

    def _stream_record_skill_usage(self, matched_skill: Any, success: bool) -> None: ...

    def stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]: ...


class StreamMixin:
    """Stream-pipeline orchestration helpers."""

    async def _stream_detect_plan_mode(
        self: _StreamAgent,
        user_message: str,
        conversation_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Detect plan mode and yield suggestion event if appropriate."""
        suggestion = self._plan_detector.detect(user_message)
        if suggestion.should_suggest:
            yield cast(
                dict[str, Any],
                AgentPlanSuggestedEvent(
                    plan_id="",
                    conversation_id=conversation_id,
                    reason=suggestion.reason,
                    confidence=suggestion.confidence,
                ).to_event_dict(),
            )
            logger.info(
                f"[ReActAgent] Plan Mode suggested (confidence={suggestion.confidence:.2f})"
            )

    def _stream_parse_forced_subagent(
        self: _StreamAgent,
        user_message: str,
    ) -> tuple[str | None, str]:
        """Parse forced SubAgent delegation from system instruction prefix.

        Returns:
            Tuple of (forced_subagent_name or None, processed_user_message).
        """
        forced_prefix = '[System Instruction: Delegate this task strictly to SubAgent "'
        if not user_message.startswith(forced_prefix):
            return None, user_message

        try:
            match = re.match(
                r'^\[System Instruction: Delegate this task strictly to SubAgent "([^"]+)"\]',
                user_message,
            )
            if match:
                forced_name = match.group(1)
                processed = user_message.replace(match.group(0), "", 1).strip()
                return forced_name, processed if processed else user_message
        except Exception as e:
            logger.warning(f"[ReActAgent] Failed to parse forced subagent instruction: {e}")

        return None, user_message

    def _stream_match_skill(
        self: _StreamAgent,
        processed_user_message: str,
        forced_skill_name: str | None,
        available_skills: Sequence[SkillProtocol],
    ) -> Iterator[dict[str, Any]]:
        """Match skill by forced slash command, else no match.

        Implicit / semantic skill matching has been removed. The only
        activation paths are:
          - Forced via slash command (this method)
          - LLM-invoked ``skill_loader`` tool (not handled here)

        Sets self._stream_skill_state with matched_skill info.
        """
        _ = processed_user_message  # no longer used for matching
        matched_skill: SkillProtocol | None = None
        skill_score = 0.0
        is_forced = False
        should_inject_prompt = False

        if forced_skill_name:
            name_lower = forced_skill_name.strip().lower()
            for skill in available_skills:
                if skill.name.lower() == name_lower and skill.status.value == "active":
                    matched_skill = skill
                    skill_score = 1.0
                    is_forced = True
                    should_inject_prompt = True
                    logger.info(f"[ReActAgent] Forced skill found: {skill.name}")
                    break
            if matched_skill is None:
                yield cast(
                    dict[str, Any],
                    AgentThoughtEvent(
                        content=(
                            f"Forced skill '{forced_skill_name}' not found; ignoring slash command."
                        ),
                    ).to_event_dict(),
                )

        if matched_skill:
            logger.info(
                f"[ReActAgent] Skill matched: name={matched_skill.name}, mode=forced, "
                f"prompt_len={len(matched_skill.full_content or '')}, "
                f"tools={list(matched_skill.tools)}"
            )
            yield cast(
                dict[str, Any],
                AgentSkillMatchedEvent(
                    skill_id=matched_skill.id,
                    skill_name=matched_skill.name,
                    tools=list(matched_skill.tools),
                    match_score=skill_score,
                    execution_mode="forced",
                ).to_event_dict(),
            )

        self._stream_skill_state = {
            "matched_skill": matched_skill,
            "skill_score": skill_score,
            "is_forced": is_forced,
            "should_inject_prompt": should_inject_prompt,
        }

    async def _stream_sync_skill_resources(
        self: _StreamAgent,
        matched_skill: Skill,
        *,
        tool_set: ToolSetV2,
    ) -> None:
        """Sync skill resources to sandbox before prompt injection."""
        if not self._resource_sync_service:
            return
        sandbox_id = self._extract_sandbox_id_from_tools(tool_set=tool_set)
        if not sandbox_id:
            return
        try:
            await self._resource_sync_service.sync_for_skill(
                skill_name=matched_skill.name,
                sandbox_id=sandbox_id,
                skill_content=matched_skill.full_content,
            )
        except Exception as e:
            logger.warning(
                f"Skill resource sync failed for INJECT mode (skill={matched_skill.name}): {e}"
            )

    async def _stream_build_context(
        self: _StreamAgent,
        *,
        system_prompt: str,
        conversation_context: list[dict[str, str]],
        processed_user_message: str,
        attachment_metadata: list[dict[str, Any]] | None,
        attachment_content: list[dict[str, Any]] | None,
        context_summary_data: dict[str, Any] | None,
        tenant_id: str,
        project_id: str,
        conversation_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Build context via ContextFacade, yield compression/flush events.

        Sets self._stream_context_result and self._stream_messages.
        """
        cached_summary = None
        if context_summary_data:
            from src.domain.model.agent.conversation.context_summary import ContextSummary

            try:
                cached_summary = ContextSummary.from_dict(context_summary_data)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"[ReActAgent] Invalid context summary data: {e}")

        context_request = ContextBuildRequest(
            system_prompt=system_prompt,
            conversation_context=conversation_context,
            user_message=processed_user_message,
            attachment_metadata=attachment_metadata,
            attachment_content=attachment_content,
            is_hitl_resume=False,
            context_summary=cached_summary,
            llm_client=self._llm_client,
        )
        context_result = await self.context_facade.build_context(context_request)
        self._stream_context_result = context_result
        self._stream_messages = context_result.messages
        self._stream_cached_summary = cached_summary

        if attachment_metadata:
            logger.info(
                f"[ReActAgent] Context built with {len(attachment_metadata)} attachments: "
                f"{[m.get('filename') for m in attachment_metadata]}"
            )
        if attachment_content:
            logger.info(f"[ReActAgent] Added {len(attachment_content)} multimodal attachments")

        # Emit context_compressed event if compression occurred
        if context_result.was_compressed:
            yield cast(
                dict[str, Any],
                AgentContextCompressedEvent(**context_result.to_event_data()).to_event_dict(),
            )
            logger.info(
                f"Context compressed: {context_result.original_message_count} -> "
                f"{context_result.final_message_count} messages, "
                f"strategy: {context_result.compression_strategy.value}"
            )

            if context_result.summary and not cached_summary:
                yield cast(
                    dict[str, Any],
                    AgentContextSummaryGeneratedEvent(
                        summary_text=context_result.summary,
                        summary_tokens=(context_result.estimated_tokens),
                        messages_covered_count=(context_result.summarized_message_count),
                        compression_level=(context_result.compression_strategy.value),
                    ).to_event_dict(),
                )

            hook_events = await self._notify_context_overflow_hook(
                tenant_id=tenant_id,
                project_id=project_id,
                conversation_id=conversation_id,
                conversation_context=conversation_context,
                context_result=context_result,
            )
            for event in hook_events:
                yield event

        # Emit initial context_status
        compression_level = context_result.metadata.get("compression_level", "none")
        yield cast(
            dict[str, Any],
            AgentContextStatusEvent(
                current_tokens=(context_result.estimated_tokens),
                token_budget=context_result.token_budget,
                occupancy_pct=round(
                    context_result.budget_utilization_pct,
                    1,
                ),
                compression_level=compression_level,
                token_distribution={},
                compression_history_summary=(
                    context_result.metadata.get("compression_history", {})
                ),
                from_cache=cached_summary is not None,
                messages_in_summary=(
                    cached_summary.messages_covered_count if cached_summary else 0
                ),
            ).to_event_dict(),
        )

    def _stream_prepare_tools(
        self: _StreamAgent,
        selection_context: ToolSelectionContext,
        is_forced: bool,
        matched_skill: Skill | None,
        *,
        tool_set: ToolSetV2,
    ) -> Iterator[dict[str, Any]]:
        """Emit trace events for the already finalized immutable turn ToolSet."""
        _ = (is_forced, matched_skill)
        selection_trace = tool_set.selection_trace
        if selection_trace:
            removed_total = sum(len(step.removed_tools) for step in selection_trace)
            route_id = selection_context.metadata.get("route_id")
            trace_id = selection_context.metadata.get("trace_id", route_id)
            trace_data = [
                {
                    "stage": step.stage,
                    "before_count": step.before_count,
                    "after_count": step.after_count,
                    "removed_count": len(step.removed_tools),
                    "duration_ms": step.duration_ms,
                    "explain": dict(step.explain),
                }
                for step in selection_trace
            ]
            semantic_stage = next(
                (stage for stage in trace_data if stage["stage"] == "semantic_ranker_stage"),
                None,
            )
            semantic_explain = semantic_stage.get("explain") if semantic_stage else None
            tool_budget_value = (
                semantic_explain.get("max_tools") if isinstance(semantic_explain, Mapping) else None
            )
            tool_budget = (
                int(tool_budget_value)
                if isinstance(tool_budget_value, (int, float))
                else self._tool_selection_max_tools
            )
            budget_exceeded_stages: list[str] = []
            for stage in trace_data:
                explain = stage.get("explain")
                if isinstance(explain, Mapping) and explain.get("budget_exceeded"):
                    budget_exceeded_stages.append(str(stage["stage"]))
            yield cast(
                dict[str, Any],
                AgentSelectionTraceEvent(
                    route_id=route_id,
                    trace_id=trace_id,
                    initial_count=cast(int, trace_data[0]["before_count"]),
                    final_count=cast(int, trace_data[-1]["after_count"]),
                    removed_total=removed_total,
                    domain_lane=(selection_context.metadata.get("domain_lane")),
                    tool_budget=tool_budget,
                    budget_exceeded_stages=[str(s) for s in budget_exceeded_stages],
                    stages=trace_data,
                ).to_event_dict(),
            )
            if removed_total > 0:
                yield cast(
                    dict[str, Any],
                    AgentPolicyFilteredEvent(
                        route_id=route_id,
                        trace_id=trace_id,
                        removed_total=removed_total,
                        stage_count=len(trace_data),
                        domain_lane=(selection_context.metadata.get("domain_lane")),
                        tool_budget=tool_budget,
                        budget_exceeded_stages=[str(s) for s in budget_exceeded_stages],
                    ).to_event_dict(),
                )

    def _stream_create_processor_config(
        self: _StreamAgent,
        config: ProcessorConfig,
        selection_context: ToolSelectionContext,
        *,
        tool_set: ToolSetV2,
    ) -> ProcessorConfig:
        """Create a request config pinned to the already resolved turn ToolSet."""
        from src.infrastructure.plugins.v2.agent_runtime_dispatcher import (
            AGENT_RUNTIME_DISPATCHER_SERVICE_V2,
            AgentRuntimeDispatcherProtocolV2,
        )
        from src.infrastructure.plugins.v2.boundary import current_operation_context_v2

        from .processor import ProcessorConfig as _ProcessorConfig

        _ = tool_set

        dispatcher = current_operation_context_v2().require(AGENT_RUNTIME_DISPATCHER_SERVICE_V2)
        if not isinstance(dispatcher, AgentRuntimeDispatcherProtocolV2):
            raise RuntimeV2Error(
                "invalid_agent_runtime_dispatcher",
                "service:agent-runtime-dispatcher has an invalid implementation",
            )

        new_config = _ProcessorConfig(
            model=config.model,
            api_key=config.api_key,
            api_auth_token=config.api_auth_token,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            max_steps=config.max_steps,
            max_tool_calls_per_step=config.max_tool_calls_per_step,
            enable_parallel_tool_execution=config.enable_parallel_tool_execution,
            parallel_tool_batch_size=config.parallel_tool_batch_size,
            doom_loop_threshold=config.doom_loop_threshold,
            max_no_progress_steps=config.max_no_progress_steps,
            max_attempts=config.max_attempts,
            initial_delay_ms=config.initial_delay_ms,
            permission_timeout=config.permission_timeout,
            continue_on_deny=config.continue_on_deny,
            context_limit=config.context_limit,
            max_cost_per_request=config.max_cost_per_request,
            max_cost_per_session=config.max_cost_per_session,
            llm_client=config.llm_client,
            plugin_event_dispatcher=dispatcher,
            runtime_context={
                **dict(config.runtime_context),
                "effective_mode": selection_context.metadata.get("effective_mode"),
            },
            tool_provider=None,
            forced_skill_name=config.forced_skill_name,
            forced_skill_tools=(
                list(config.forced_skill_tools) if config.forced_skill_tools else None
            ),
            skill_names=list(config.skill_names),
            provider_options=dict(config.provider_options),
            message_bus=config.message_bus,
            control_channel=config.control_channel,
            run_id=config.run_id,
            provider_id=config.provider_id,
            loop_resolver=config.loop_resolver,
        )
        return new_config

    async def _stream_process_events(
        self: _StreamAgent,
        processor: SessionProcessor,
        messages: list[dict[str, Any]],
        langfuse_context: dict[str, Any],
        abort_signal: asyncio.Event | None,
        matched_skill: Skill | None,
        agent_id: str | None = None,
        plugin_generation: dict[str, str | int] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Process events from SessionProcessor and yield converted events.

        Sets self._stream_final_content and self._stream_success.
        """
        from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2

        from .processor import RunContext as _RunContext

        self._stream_final_content = ""
        self._stream_success = True

        try:
            run_ctx = _RunContext(
                abort_signal=abort_signal,
                langfuse_context=langfuse_context,
                conversation_id=langfuse_context.get("conversation_id")
                if langfuse_context
                else None,
                agent_id=agent_id,
                plugin_generation=(
                    PluginGenerationDescriptorV2.from_payload(plugin_generation)
                    if plugin_generation is not None
                    else None
                ),
            )
            async for domain_event in processor.process(
                session_id=langfuse_context["conversation_id"],
                messages=messages,
                run_ctx=run_ctx,
            ):
                if isinstance(domain_event, AgentCompleteEvent):
                    self._stream_execution_summary = domain_event.execution_summary
                event = self._convert_domain_event(domain_event, agent_id=agent_id)
                if event:
                    if event.get("type") == "text_delta":
                        self._stream_final_content += event.get("data", {}).get("delta", "")
                    elif event.get("type") == "text_end":
                        text_end_content = event.get("data", {}).get("full_text", "")
                        if text_end_content:
                            self._stream_final_content = text_end_content

                    yield event

        except Exception as e:
            logger.error(f"[ReActAgent] Error in stream: {e}", exc_info=True)
            self._stream_success = False
            error_code = e.code if isinstance(e, RuntimeV2Error) else type(e).__name__
            yield cast(
                dict[str, Any],
                AgentErrorEvent(
                    message=str(e),
                    code=error_code,
                ).to_event_dict(),
            )

    async def _stream_post_process(
        self: _StreamAgent,
        *,
        processed_user_message: str,
        final_content: str,
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        matched_skill: Skill | None,
        success: bool,
        execution_time_ms: int = 0,
        tool_call_count: int = 0,
        llm_client_override: Any | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Post-process: memory capture, conversation indexing, final complete event."""
        hook_events = await self._notify_after_turn_complete_hook(
            processed_user_message=processed_user_message,
            final_content=final_content,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            conversation_context=conversation_context,
            matched_skill=matched_skill,
            success=success,
            execution_time_ms=execution_time_ms,
            tool_call_count=tool_call_count,
            llm_client_override=llm_client_override,
        )
        for event in hook_events:
            yield event

        # Yield final complete event
        yield cast(
            dict[str, Any],
            AgentCompleteEvent(
                content=final_content,
                skill_used=(matched_skill.name if matched_skill else None),
                execution_summary=self._stream_execution_summary,
            ).to_event_dict(),
        )

    def _stream_decide_route(
        self: _StreamAgent,
        *,
        processed_user_message: str,
        conversation_context: list[dict[str, str]],
        forced_subagent_name: str | None,
        forced_skill_name: str | None,
        plan_mode: bool,
    ) -> tuple[RoutingDecision, str, str, dict[str, Any], str | None, dict[str, Any]]:
        """Compute routing decision and build the execution_path_decided event.

        Returns:
            (routing_decision, route_id, trace_id, routing_metadata,
             forced_skill_name, event_dict)
        """
        routing_decision = self._decide_execution_path(
            message=processed_user_message,
            conversation_context=conversation_context,
            forced_subagent_name=forced_subagent_name,
            forced_skill_name=forced_skill_name,
            plan_mode_requested=plan_mode,
        )
        route_id = uuid4().hex
        trace_id = route_id
        routing_metadata = dict(routing_decision.metadata or {})
        routing_metadata["route_id"] = route_id
        routing_metadata["trace_id"] = trace_id
        event_dict = {
            "type": "execution_path_decided",
            "data": {
                "route_id": route_id,
                "trace_id": trace_id,
                "path": routing_decision.path.value,
                "confidence": routing_decision.confidence,
                "reason": routing_decision.reason,
                "target": routing_decision.target,
                "metadata": routing_metadata,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if (
            not forced_skill_name
            and routing_decision.path == ExecutionPath.DIRECT_SKILL
            and routing_decision.target
        ):
            forced_skill_name = routing_decision.target
        return routing_decision, route_id, trace_id, routing_metadata, forced_skill_name, event_dict

    def _stream_resolve_mode(
        self: _StreamAgent,
        *,
        plan_mode: bool,
        routing_decision: RoutingDecision,
        routing_metadata: dict[str, Any],
        tenant_id: str,
        project_id: str,
        processed_user_message: str,
        conversation_context: list[dict[str, str]],
        allow_tools: list[str] | None = None,
        deny_tools: list[str] | None = None,
        forced_operation_tool_names: Sequence[str] = (),
    ) -> tuple[str, ToolSelectionContext]:
        """Resolve effective mode and build selection context.

        Returns:
            (effective_mode, selection_context)
        """
        from src.infrastructure.agent.permission.manager import AgentPermissionMode

        plan_mode = plan_mode or routing_decision.path == ExecutionPath.PLAN_MODE
        effective_mode = (
            "plan"
            if plan_mode
            else (self.agent_mode if self.agent_mode in ["build", "plan"] else "build")
        )
        selection_context = self._build_tool_selection_context(
            tenant_id=tenant_id,
            project_id=project_id,
            user_message=processed_user_message,
            conversation_context=conversation_context,
            effective_mode=effective_mode,
            routing_metadata=routing_metadata,
            allow_tools=allow_tools,
            deny_tools=deny_tools,
        )
        selection_context = _pin_selection_context_tools_v2(
            selection_context,
            forced_operation_tool_names,
        )
        if effective_mode == "plan":
            self.permission_manager.set_mode(AgentPermissionMode.PLAN)
        else:
            self.permission_manager.set_mode(AgentPermissionMode.BUILD)
        return effective_mode, selection_context

    def _stream_determine_mode_and_permissions(
        self: _StreamAgent,
        plan_mode: bool,
        routing_decision: RoutingDecision,
    ) -> str:
        """Determine effective execution mode and set permission mode.

        Returns:
            effective_mode: "plan" or "build"
        """
        from src.infrastructure.agent.permission.manager import AgentPermissionMode

        resolved_plan_mode = plan_mode or routing_decision.path == ExecutionPath.PLAN_MODE
        effective_mode = (
            "plan"
            if resolved_plan_mode
            else (self.agent_mode if self.agent_mode in ["build", "plan"] else "build")
        )

        if effective_mode == "plan":
            self.permission_manager.set_mode(AgentPermissionMode.PLAN)
        else:
            self.permission_manager.set_mode(AgentPermissionMode.BUILD)

        return effective_mode

    def _stream_record_skill_usage(self: _StreamAgent, matched_skill: Any, success: bool) -> None:
        """Skill usage tracking was removed; method kept as a no-op hook."""
        _ = (matched_skill, success)
        return None

    def _stream_inject_subagent_tools(  # noqa: PLR0915
        self: _StreamAgent,
        tools_to_use: list[ToolDefinition],
        available_subagents: Sequence[Any],
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        abort_signal: asyncio.Event | None,
        tool_set_binding: SubAgentToolSetBindingV2,
        workspace_root_task: Any | None = None,
        leader_agent_id: str | None = None,
        actor_user_id: str | None = None,
        selected_agent: Any | None = None,
    ) -> list[ToolDefinition]:
        """Inject SubAgent-as-Tool delegation tools when enabled.

        Returns updated tools list with SubAgent tools appended.
        """
        if not available_subagents or not self._enable_subagent_as_tool:
            return tools_to_use
        if not _selected_agent_can_spawn(selected_agent):
            logger.info(
                "[ReActAgent] Skipping SubAgent delegation tools because selected agent %s "
                "cannot spawn",
                getattr(selected_agent, "id", None),
            )
            return tools_to_use

        enabled_subagents = _filter_subagents_for_selected_agent_policy(
            [sa for sa in available_subagents if sa.enabled],
            selected_agent,
        )
        if not enabled_subagents:
            return tools_to_use
        spawn_limits = _selected_agent_spawn_limits(
            selected_agent,
            default_depth=self._max_subagent_delegation_depth,
            default_active_runs=self._max_subagent_active_runs,
            default_children_per_requester=self._max_subagent_children_per_requester,
            default_active_runs_per_lineage=self._max_subagent_active_runs_per_lineage,
        )
        if spawn_limits["max_delegation_depth"] <= 0:
            logger.info(
                "[ReActAgent] Skipping SubAgent delegation tools because selected agent %s "
                "has max spawn depth %s",
                getattr(selected_agent, "id", None),
                spawn_limits["max_delegation_depth"],
            )
            return tools_to_use

        subagent_map = {sa.name: sa for sa in enabled_subagents}
        subagent_descriptions = {
            sa.name: (sa.trigger.description if sa.trigger else sa.display_name)
            for sa in enabled_subagents
        }

        async def _prepare_workspace_delegation(
            *,
            subagent_name: str,
            subagent_id: str,
            task: str,
            workspace_task_id: str | None = None,
        ) -> dict[str, str] | None:
            if workspace_root_task is None or not actor_user_id:
                return None
            from src.infrastructure.agent.workspace.orchestrator import (
                WorkspaceAutonomyOrchestrator,
            )

            return await WorkspaceAutonomyOrchestrator().prepare_subagent_delegation(
                workspace_id=getattr(workspace_root_task, "workspace_id", project_id),
                root_goal_task_id=getattr(workspace_root_task, "id", ""),
                actor_user_id=actor_user_id,
                delegated_task_text=task,
                subagent_name=subagent_name,
                subagent_id=subagent_id,
                leader_agent_id=leader_agent_id,
                workspace_task_id=workspace_task_id,
            )

        def _decorate_workspace_delegate_task(
            task: str,
            task_binding: dict[str, str] | None,
        ) -> str:
            if not task_binding:
                return task
            return (
                "[workspace-task-binding]\n"
                f"workspace_task_id={task_binding['workspace_task_id']}\n"
                f"attempt_id={task_binding.get('attempt_id', '')}\n"
                f"workspace_agent_binding_id={task_binding.get('workspace_agent_binding_id', '')}\n"
                f"root_goal_task_id={task_binding['root_goal_task_id']}\n"
                f"workspace_id={task_binding['workspace_id']}\n"
                "[/workspace-task-binding]\n\n"
                f"{task}"
            )

        async def _finalize_workspace_delegation(
            *,
            task_binding: dict[str, str] | None,
            report_type: str,
            summary: str,
            artifacts: list[str] | None = None,
        ) -> Any:
            if not task_binding or not actor_user_id:
                return None
            from src.infrastructure.agent.workspace.orchestrator import (
                WorkspaceAutonomyOrchestrator,
            )

            return await WorkspaceAutonomyOrchestrator().apply_worker_report(
                workspace_id=task_binding["workspace_id"],
                root_goal_task_id=task_binding["root_goal_task_id"],
                task_id=task_binding["workspace_task_id"],
                attempt_id=task_binding.get("attempt_id"),
                actor_user_id=actor_user_id,
                worker_agent_id=None,
                report_type=report_type,
                summary=summary,
                artifacts=artifacts,
                leader_agent_id=leader_agent_id,
            )

        def _format_workspace_delegate_result(
            *,
            subagent_name: str,
            task_binding: dict[str, str] | None,
            report_type: str,
            summary: str,
            tokens: int | None = None,
        ) -> str:
            if not task_binding:
                return summary

            lines = [
                f"[SubAgent '{subagent_name}' completed]",
                f"Candidate worker report stored for workspace_task_id={task_binding['workspace_task_id']}",
                f"Suggested report_type={report_type}",
                "Leader adjudication required: review the worker evidence, then use todoread/todowrite to decide whether this task should become completed, failed, remain in_progress, or be replanned.",
                f"Result: {summary}",
            ]
            if isinstance(tokens, int):
                lines.append(f"Tokens used: {tokens}")
            return "\n".join(lines)

        # Create delegation callback that captures stream-scoped context
        async def _delegate_callback(
            subagent_name: str,
            task: str,
            workspace_task_id: str | None = None,
            on_event: Callable[[dict[str, Any]], None] | None = None,
        ) -> str:
            target = subagent_map.get(subagent_name)
            if not target:
                return f"SubAgent '{subagent_name}' not found"

            task_binding = await _prepare_workspace_delegation(
                subagent_name=subagent_name,
                subagent_id=target.id,
                task=task,
                workspace_task_id=workspace_task_id,
            )
            delegated_task = _decorate_workspace_delegate_task(task, task_binding)
            events = []
            async for evt in self._execute_subagent(
                subagent=target,
                available_subagents=available_subagents,
                user_message=delegated_task,
                conversation_context=conversation_context,
                project_id=project_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                abort_signal=abort_signal,
                inherited_tool_set=tool_set_binding.require(),
            ):
                if on_event:
                    event_type = evt.get("type")
                    if event_type not in {"complete", "error"}:
                        on_event(evt)
                events.append(evt)

            complete_evt = next(
                (e for e in events if e.get("type") == "complete"),
                None,
            )
            if complete_evt:
                data = complete_evt.get("data", {})
                content = data.get("content", "")
                sa_result = data.get("subagent_result")
                if sa_result:
                    report_type = "completed" if sa_result.get("success", True) else "blocked"
                    summary = sa_result.get("summary", content)
                    result_summary = summary or content or f"SubAgent {subagent_name} finished"
                    tokens = sa_result.get("tokens_used", 0)
                    await _finalize_workspace_delegation(
                        task_binding=task_binding,
                        report_type=report_type,
                        summary=result_summary,
                    )
                    return _format_workspace_delegate_result(
                        subagent_name=subagent_name,
                        task_binding=task_binding,
                        report_type=report_type,
                        summary=result_summary,
                        tokens=tokens,
                    )
                await _finalize_workspace_delegation(
                    task_binding=task_binding,
                    report_type="completed",
                    summary=content or f"SubAgent {subagent_name} completed",
                )
                return _format_workspace_delegate_result(
                    subagent_name=subagent_name,
                    task_binding=task_binding,
                    report_type="completed",
                    summary=content or "SubAgent completed with no output",
                )

            await _finalize_workspace_delegation(
                task_binding=task_binding,
                report_type="blocked",
                summary=f"SubAgent {subagent_name} execution completed but no result returned",
            )
            return _format_workspace_delegate_result(
                subagent_name=subagent_name,
                task_binding=task_binding,
                report_type="blocked",
                summary="SubAgent execution completed but no result returned",
            )

        async def _spawn_callback(
            subagent_name: str,
            task: str,
            run_id: str,
            **spawn_options: Any,
        ) -> str:
            target = subagent_map.get(subagent_name)
            if not target:
                raise ValueError(f"SubAgent '{subagent_name}' not found")
            task_binding = await _prepare_workspace_delegation(
                subagent_name=subagent_name,
                subagent_id=target.id,
                task=task,
                workspace_task_id=(
                    str(spawn_options.get("workspace_task_id") or "").strip() or None
                ),
            )
            delegated_task = _decorate_workspace_delegate_task(task, task_binding)
            await self._launch_subagent_session(
                run_id=run_id,
                subagent=target,
                available_subagents=available_subagents,
                user_message=delegated_task,
                conversation_id=conversation_id,
                conversation_context=conversation_context,
                project_id=project_id,
                tenant_id=tenant_id,
                abort_signal=abort_signal,
                model_override=(str(spawn_options.get("model") or "").strip() or None),
                thinking_override=(str(spawn_options.get("thinking") or "").strip() or None),
                spawn_mode=str(spawn_options.get("spawn_mode") or "run"),
                thread_requested=bool(spawn_options.get("thread_requested")),
                cleanup=str(spawn_options.get("cleanup") or "keep"),
                run_metadata=task_binding,
                inherited_tool_set=tool_set_binding.require(),
            )
            return run_id

        async def _cancel_spawn_callback(run_id: str) -> bool:
            return await self._cancel_subagent_session(run_id)

        tools_to_use = self._build_subagent_tool_definitions(
            subagent_map=subagent_map,
            subagent_descriptions=subagent_descriptions,
            enabled_subagents=enabled_subagents,
            delegate_callback=_delegate_callback,
            spawn_callback=_spawn_callback,
            cancel_callback=_cancel_spawn_callback,
            conversation_id=conversation_id,
            tools_to_use=tools_to_use,
            max_delegation_depth=spawn_limits["max_delegation_depth"],
            max_active_runs=spawn_limits["max_active_runs"],
            max_active_runs_per_lineage=spawn_limits["max_active_runs_per_lineage"],
            max_children_per_requester=spawn_limits["max_children_per_requester"],
        )

        logger.info(
            f"[ReActAgent] Injected SubAgent delegation tools "
            f"({len(enabled_subagents)} SubAgents, "
            f"parallel={'yes' if len(enabled_subagents) >= 2 else 'no'}, "
            "sessions=yes)"
        )

        return tools_to_use

    def _build_subagent_tool_definitions(
        self: _StreamAgent,
        *,
        subagent_map: dict[str, Any],
        subagent_descriptions: dict[str, str],
        enabled_subagents: list[Any],
        delegate_callback: Any,
        spawn_callback: Any,
        cancel_callback: Any,
        conversation_id: str,
        tools_to_use: list[ToolDefinition],
        max_delegation_depth: int | None = None,
        max_active_runs: int | None = None,
        max_active_runs_per_lineage: int | None = None,
        max_children_per_requester: int | None = None,
    ) -> list[ToolDefinition]:
        """Build and append all SubAgent tool definitions to tools list."""
        definitions = self._tool_builder.build_subagent_tool_definitions(
            subagent_map=subagent_map,
            subagent_descriptions=subagent_descriptions,
            enabled_subagents=enabled_subagents,
            delegate_callback=delegate_callback,
            spawn_callback=spawn_callback,
            cancel_callback=cancel_callback,
            conversation_id=conversation_id,
            tools_to_use=tools_to_use,
            max_delegation_depth=max_delegation_depth,
            max_active_runs=max_active_runs,
            max_active_runs_per_lineage=max_active_runs_per_lineage,
            max_children_per_requester=max_children_per_requester,
        )
        return cast(list[ToolDefinition], definitions)

    async def stream(  # noqa: PLR0913, PLR0912, PLR0915
        self: _StreamAgent,
        conversation_id: str,
        user_message: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
        conversation_context: list[dict[str, str]] | None = None,
        message_id: str | None = None,
        attachment_content: list[dict[str, Any]] | None = None,
        attachment_metadata: list[dict[str, Any]] | None = None,
        abort_signal: asyncio.Event | None = None,
        forced_skill_name: str | None = None,
        context_summary_data: dict[str, Any] | None = None,
        plan_mode: bool = False,
        llm_overrides: dict[str, Any] | None = None,
        model_override: str | None = None,
        selected_agent_model_route: ModelRouteRef | None = None,
        model_route_override: ModelRouteRef | None = None,
        agent_id: str | None = None,
        tenant_agent_config_data: dict[str, Any] | None = None,
        preferred_language: str | None = None,
        api_auth_token: str | None = None,
        canonical_run_id: str | None = None,
        plugin_generation: dict[str, str | int] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Stream agent response with ReAct loop.

        This is the main entry point for agent execution. It:
        1. Checks for Plan Mode triggering
        2. Checks for SubAgent routing (L3)
        3. Checks for Skill matching (L2)
        4. Builds messages from context
        5. Creates SessionProcessor
        6. Streams events back to caller

        Args:
            conversation_id: Conversation ID
            user_message: User's message
            project_id: Project ID
            user_id: User ID
            tenant_id: Tenant ID
            conversation_context: Optional conversation history
            message_id: Optional message ID for HITL request persistence
            forced_skill_name: Optional skill name to force direct execution

        Yields:
            Event dictionaries compatible with existing SSE format:
            - {"type": "plan_mode_triggered", "data": {...}}
            - {"type": "thought", "data": {...}}
            - {"type": "act", "data": {...}}
            - {"type": "observe", "data": {...}}
            - {"type": "complete", "data": {...}}
            - {"type": "error", "data": {...}}
        """
        resolved_agent_id = (agent_id or "").strip()
        if not resolved_agent_id:
            raise RuntimeV2Error(
                "agent_id_not_resolved",
                "agent stream requires an explicit agent ID resolved by the pinned generation",
            )

        conversation_context = conversation_context or []
        resolved_model_route_override = _resolve_model_route_override(
            model_override=model_override,
            model_route_override=model_route_override,
        )
        self._reset_stream_state()
        start_time = time.time()

        logger.info(
            f"[ReActAgent] Starting stream for conversation {conversation_id}, "
            f"user: {user_id}, message: {user_message[:50]}..."
        )

        # Phase 1: Plan mode detection
        async for event in self._stream_detect_plan_mode(user_message, conversation_id):
            yield event

        # Phase 2: Parse forced subagent from system instruction
        forced_subagent_name, processed_user_message = self._stream_parse_forced_subagent(
            user_message
        )

        # Phase 3: Routing decision
        routing_decision, _route_id, _trace_id, routing_metadata, forced_skill_name, route_event = (
            self._stream_decide_route(
                processed_user_message=processed_user_message,
                conversation_context=conversation_context,
                forced_subagent_name=forced_subagent_name,
                forced_skill_name=forced_skill_name,
                plan_mode=plan_mode,
            )
        )
        yield route_event

        # Phase 4b: Filesystem skill loading (lazy, once per agent instance)
        await self._load_filesystem_skills(tenant_id, project_id)
        runtime_capabilities = await _resolve_agent_capabilities_from_runtime_v2(
            self,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        available_skills = list(runtime_capabilities.skills)
        available_subagents = list(runtime_capabilities.subagents)

        selected_agent = await self._load_selected_agent(
            agent_id=resolved_agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if selected_agent is None:
            raise RuntimeV2Error(
                "agent_definition_not_found",
                f"agent definition {resolved_agent_id} is unavailable in the pinned generation",
            )
        await _register_selected_agent_session(
            conversation_id=conversation_id,
            project_id=project_id,
            selected_agent_id=selected_agent.id,
        )
        has_workspace_binding = False
        workspace_runtime_payload = self._workspace_runtime_context(conversation_context)
        runtime_preferred_language = _normalize_preferred_language(
            preferred_language
        ) or _preferred_language_from_payload(workspace_runtime_payload)
        workspace_replan_turn = self._is_workspace_leader_replan_context(workspace_runtime_payload)
        workspace_binding = self._normalize_workspace_binding(
            workspace_runtime_payload.get("workspace_binding")
            if isinstance(workspace_runtime_payload, Mapping)
            else None
        ) or self._workspace_binding_from_text(processed_user_message)
        workspace_root_task: Any
        if project_id and tenant_id and user_id:
            from src.infrastructure.agent.workspace.orchestrator import (
                WorkspaceAutonomyOrchestrator,
            )

            orchestrator = WorkspaceAutonomyOrchestrator()
            has_workspace_binding = workspace_binding is not None
            if orchestrator.should_activate(
                processed_user_message,
                has_workspace_binding=has_workspace_binding,
            ):
                if workspace_binding is not None:
                    workspace_root_task = SimpleNamespace(
                        id=workspace_binding.get("root_goal_task_id")
                        or workspace_binding.get("workspace_task_id")
                        or "",
                        workspace_id=workspace_binding["workspace_id"],
                    )
                else:
                    workspace_root_task = await orchestrator.materialize_goal_candidate(
                        project_id,
                        tenant_id,
                        user_id,
                        leader_agent_id=selected_agent.id,
                        user_query=processed_user_message,
                        preferred_language=runtime_preferred_language,
                    )
            else:
                workspace_root_task = None
        else:
            workspace_root_task = None
        runtime_profile = self._build_runtime_profile(
            tenant_id=tenant_id,
            tenant_agent_config_data=tenant_agent_config_data,
            selected_agent=selected_agent,
            selected_agent_model_route=selected_agent_model_route,
            is_workspace_worker_runtime=has_workspace_binding,
            available_skills=available_skills,
        )
        effective_model_route = (
            resolved_model_route_override or runtime_profile.effective_model_route
        )
        runtime_limits = _workspace_runtime_limit_overrides(workspace_runtime_payload)
        if runtime_limits:
            runtime_profile = replace(
                runtime_profile,
                effective_max_tokens=runtime_limits.get(
                    "max_tokens", runtime_profile.effective_max_tokens
                ),
            )
        if workspace_replan_turn:
            runtime_profile = self._with_workspace_leader_replan_tool_allowlist(runtime_profile)
        elif has_workspace_binding:
            runtime_profile = self._with_workspace_worker_tool_allowlist(runtime_profile)
        runtime_workspace_manager = self._build_runtime_workspace_manager(selected_agent)

        # Phase 5: Skill matching
        if workspace_root_task is not None and not forced_skill_name:
            self._stream_skill_state = {
                "matched_skill": None,
                "is_forced": False,
                "should_inject_prompt": False,
            }
            logger.info(
                "[ReActAgent] Skipping non-forced skill matching because workspace authority is active "
                "for conversation %s",
                conversation_id,
            )
        else:
            for event in self._stream_match_skill(
                processed_user_message,
                forced_skill_name,
                available_skills=cast(
                    "list[SkillProtocol]",
                    runtime_profile.available_skills,
                ),
            ):
                yield event
        skill_state = self._stream_skill_state
        matched_skill: Skill | None = cast("Skill | None", skill_state["matched_skill"])
        is_forced: bool = cast(bool, skill_state["is_forced"])
        should_inject_prompt: bool = cast(bool, skill_state["should_inject_prompt"])

        # Phase 5b: Bind all turn-local tool effects to the pinned operation.
        from src.infrastructure.plugins.v2.boundary import current_operation_context_v2

        operation = current_operation_context_v2()
        from src.application.services.approved_run_tool_permission_v2 import (
            current_approved_run_guard_v2,
            prepare_approved_run_guard_v2,
            restore_approved_child_guard_v2,
        )
        from src.application.services.chat_run_tool_permission_v2 import (
            current_chat_run_guard_v2,
            prepare_chat_run_guard_v2,
            restore_chat_child_guard_v2,
        )

        if current_approved_run_guard_v2() is None:
            await restore_approved_child_guard_v2(operation)
        if current_chat_run_guard_v2() is None:
            await restore_chat_child_guard_v2(operation)
        if (
            canonical_run_id is None
            and current_approved_run_guard_v2() is None
            and current_chat_run_guard_v2() is None
        ):
            raise RuntimeV2Error("run_tool_authority_missing", "Agent turn requires canonical authority")
        await prepare_approved_run_guard_v2(operation, canonical_run_id)
        await prepare_chat_run_guard_v2(operation, canonical_run_id)
        operation_catalog = bind_operation_tool_set_catalog_v2(operation)
        from src.infrastructure.plugins.v2.agent_skill_mcp_service import (
            SKILL_MCP_MANAGER_SERVICE_V2,
        )

        skill_mcp_manager = operation.require(SKILL_MCP_MANAGER_SERVICE_V2)
        if not isinstance(skill_mcp_manager, SkillMCPManagerProtocolV2):
            raise RuntimeV2Error(
                "invalid_skill_mcp_manager",
                "service:agent.skill-mcp-manager has an invalid implementation",
            )
        mcp_tool_names: tuple[str, ...] = ()
        if matched_skill and matched_skill.metadata:
            mcp_servers_raw = matched_skill.metadata.get("mcp_servers")
            mcp_configs = parse_skill_mcp_configs_v2(mcp_servers_raw)
            mcp_tool_names = await activate_skill_mcp_operation_tools_v2(
                operation=operation,
                catalog=operation_catalog,
                manager=skill_mcp_manager,
                skill_id=matched_skill.name,
                configs=mcp_configs,
            )

        # Phase 6: Mode/selection context setup
        effective_mode, selection_context = self._stream_resolve_mode(
            plan_mode=plan_mode,
            routing_decision=routing_decision,
            routing_metadata=routing_metadata,
            tenant_id=tenant_id,
            project_id=project_id,
            processed_user_message=processed_user_message,
            conversation_context=conversation_context,
            allow_tools=runtime_profile.allow_tools,
            deny_tools=runtime_profile.deny_tools,
            forced_operation_tool_names=mcp_tool_names,
        )

        # Phase 6b: Inject matched skill's declared tools into selection context
        # so the tool selection pipeline can pin them (survive semantic budget + deny lists)
        if matched_skill and matched_skill.tools:
            selection_context = _pin_selection_context_tools_v2(
                selection_context,
                matched_skill.tools,
            )
            skill_pinned = selection_context.metadata["skill_pinned_tools"]
            logger.info(
                f"[ReActAgent] Skill '{matched_skill.name}' declares tools={skill_pinned}, "
                f"injecting into selection context for pipeline pinning"
            )

        # Phase 6c: Contribute turn-bound SubAgent closures before the one
        # selection pass so prompt, processor, traces, and telemetry share them.
        subagent_tool_set_binding = SubAgentToolSetBindingV2(operation=operation)
        subagent_definitions = self._stream_inject_subagent_tools(
            tools_to_use=[],
            available_subagents=available_subagents,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            workspace_root_task=workspace_root_task,
            leader_agent_id=selected_agent.id,
            actor_user_id=user_id,
            selected_agent=selected_agent,
            tool_set_binding=subagent_tool_set_binding,
        )
        if subagent_definitions:
            await contribute_operation_tool_definitions_v2(
                operation=operation,
                catalog=operation_catalog,
                source_id=OPERATION_SUBAGENT_TOOL_SOURCE_V2,
                definitions=subagent_definitions,
            )

        # Phase 6d: Resolve and finalize one immutable model-visible ToolSet.
        # Every consumer below receives this exact value; no consumer may
        # independently refresh native/static tools during the turn.
        from src.infrastructure.agent.workspace.runtime_role_contract import (
            is_workspace_conversation as _is_workspace_conversation,
        )

        workspace_conversation_flag = _is_workspace_conversation(workspace_runtime_payload)
        turn_tool_set = _resolve_current_tools_from_runtime_v2(
            self,
            selection_context,
            operation_catalog=operation_catalog,
        )
        turn_tool_set = _finalize_turn_tool_set_v2(
            turn_tool_set,
            is_forced=is_forced,
            matched_skill=matched_skill,
            workspace_root_task=workspace_root_task,
            is_workspace_conversation=workspace_conversation_flag,
            allow_tools=runtime_profile.allow_tools,
            deny_tools=runtime_profile.deny_tools,
            forced_operation_tool_names=mcp_tool_names,
        )
        subagent_tool_set_binding.bind(
            turn_tool_set,
            rebindable_tool_names=(
                definition.name
                for definition in subagent_definitions
                if definition.name in turn_tool_set.tools
            ),
        )

        # Phase 6e: Operational resource sync derives its sandbox identity
        # from the same pinned ToolSet used by model-visible consumers.
        if should_inject_prompt and matched_skill:
            await self._stream_sync_skill_resources(
                matched_skill,
                tool_set=turn_tool_set,
            )
            yield cast(
                dict[str, Any],
                AgentSkillExecutionStartEvent(
                    skill_id=matched_skill.id,
                    skill_name=matched_skill.name,
                    tools=list(matched_skill.tools),
                    query=processed_user_message,
                ).to_event_dict(),
            )

        # Phase 7: Memory runtime prompt augmentation
        memory_context, hook_events = await self._apply_before_prompt_build_hook(
            processed_user_message=processed_user_message,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            effective_mode=effective_mode,
            matched_skill=matched_skill if should_inject_prompt else None,
            selected_agent=selected_agent,
        )
        for event in hook_events:
            yield event

        # Phase 7b: Heartbeat check
        heartbeat_prompt: str | None = None
        if self._heartbeat_runner and self._heartbeat_runner.check_due():
            hb_result = await self._heartbeat_runner.run_once()
            if hb_result.should_run:
                heartbeat_prompt = hb_result.prompt
                logger.info("[ReActAgent] Heartbeat due, injecting heartbeat prompt into context")

        # Phase 7c: Selected agent prompt resolution
        primary_agent_prompt = self._build_primary_agent_prompt(
            runtime_profile=runtime_profile,
            selection_context=selection_context,
            tool_set=turn_tool_set,
            available_subagents=available_subagents,
        )

        # Phase 8: System prompt building
        system_prompt = await self._build_system_prompt(
            processed_user_message,
            conversation_context,
            matched_skill=matched_skill if should_inject_prompt else None,
            subagent=None,
            mode=effective_mode,
            current_step=1,
            project_id=project_id,
            tenant_id=tenant_id,
            force_execution=is_forced,
            memory_context=memory_context,
            selection_context=selection_context,
            heartbeat_prompt=heartbeat_prompt,
            agent_definition_prompt=runtime_profile.agent_definition_prompt,
            primary_agent_prompt=primary_agent_prompt,
            available_skills=runtime_profile.available_skills,
            available_subagents=available_subagents,
            model_name=effective_model_route.model_id,
            max_steps_override=runtime_profile.effective_max_steps,
            workspace_manager=runtime_workspace_manager,
            selected_agent_name=selected_agent.name,
            is_workspace_conversation=workspace_conversation_flag,
            tool_set=turn_tool_set,
        )

        # Phase 9: Context building
        async for event in self._stream_build_context(
            system_prompt=system_prompt,
            conversation_context=conversation_context,
            processed_user_message=processed_user_message,
            attachment_metadata=attachment_metadata,
            attachment_content=attachment_content,
            context_summary_data=context_summary_data,
            tenant_id=tenant_id,
            project_id=project_id,
            conversation_id=conversation_id,
        ):
            yield event
        messages = self._stream_messages

        # Phase 10: Tool preparation
        for event in self._stream_prepare_tools(
            selection_context,
            is_forced,
            matched_skill,
            tool_set=turn_tool_set,
        ):
            yield event
        tools_to_use = list(turn_tool_set.definitions)

        # Phase 12: Processor creation
        config = self._stream_create_processor_config(
            self.config,
            selection_context,
            tool_set=turn_tool_set,
        )
        config.run_id = canonical_run_id or message_id
        config.approved_run_required = current_approved_run_guard_v2() is not None
        config.chat_run_required = current_chat_run_guard_v2() is not None
        config.api_auth_token = api_auth_token
        previous_model_route = ModelRouteRef(
            provider_id=config.provider_id,
            model_id=config.model,
        )
        await _bind_processor_model_route(
            config=config,
            route=effective_model_route,
            tenant_id=tenant_id,
            revalidate=resolved_model_route_override is not None,
        )
        config.temperature = runtime_profile.effective_temperature
        config.max_tokens = runtime_profile.effective_max_tokens
        config.max_steps = runtime_profile.effective_max_steps
        config.skill_names = [skill.name for skill in runtime_profile.available_skills]
        config.runtime_context = {
            **dict(config.runtime_context),
            "selected_agent_id": selected_agent.id,
            "selected_agent_name": selected_agent.name,
            "allowed_skills": list(selected_agent.allowed_skills)
            if selected_agent.allowed_skills
            else [],
            "allowed_tools": list(runtime_profile.allow_tools),
            "denied_tools": list(runtime_profile.deny_tools),
            "route_id": selection_context.metadata.get("route_id"),
            "trace_id": selection_context.metadata.get("trace_id"),
        }
        if runtime_preferred_language:
            config.runtime_context[PREFERRED_LANGUAGE] = runtime_preferred_language
        if (
            workspace_root_task is not None
            or workspace_binding is not None
            or isinstance(workspace_runtime_payload, Mapping)
        ):
            from src.infrastructure.agent.workspace.runtime_role_contract import (
                derive_workspace_session_role,
            )

            workspace_session_role = derive_workspace_session_role(
                has_workspace_binding=has_workspace_binding
            )
            if workspace_replan_turn:
                workspace_session_role = WORKSPACE_ROLE_LEADER
            elif isinstance(workspace_runtime_payload, Mapping):
                runtime_role = workspace_runtime_payload.get(WORKSPACE_SESSION_ROLE_KEY)
                if isinstance(runtime_role, str) and runtime_role.strip():
                    workspace_session_role = runtime_role.strip()

            workspace_runtime_context: dict[str, Any] = {
                "task_authority": "workspace",
                WORKSPACE_SESSION_ROLE_KEY: workspace_session_role,
            }
            if runtime_preferred_language:
                workspace_runtime_context[PREFERRED_LANGUAGE] = runtime_preferred_language
            workspace_id_value = getattr(workspace_root_task, "workspace_id", None)
            if not workspace_id_value and workspace_binding is not None:
                workspace_id_value = workspace_binding.get("workspace_id")
            workspace_runtime_context["workspace_id"] = workspace_id_value or project_id

            root_goal_task_id = getattr(workspace_root_task, "id", None)
            if not root_goal_task_id and workspace_binding is not None:
                root_goal_task_id = workspace_binding.get("root_goal_task_id")
            workspace_runtime_context["root_goal_task_id"] = root_goal_task_id or ""
            if isinstance(workspace_runtime_payload, Mapping):
                for key in (WORKSPACE_TURN_TYPE_KEY, WORKSPACE_TOOL_MODE_KEY):
                    value = workspace_runtime_payload.get(key)
                    if isinstance(value, str) and value.strip():
                        workspace_runtime_context[key] = value.strip()
                code_context = workspace_runtime_payload.get("code_context")
                if isinstance(code_context, Mapping):
                    workspace_runtime_context["code_context"] = dict(code_context)
                    sandbox_code_root = code_context.get("sandbox_code_root")
                    if isinstance(sandbox_code_root, str) and sandbox_code_root.strip():
                        workspace_runtime_context["sandbox_code_root"] = sandbox_code_root.strip()
                workspace_runtime_context.update(
                    _workspace_runtime_forwarded_fields(workspace_runtime_payload)
                )
            if workspace_binding is not None:
                for key in ("workspace_task_id", "attempt_id", "leader_agent_id"):
                    value = workspace_binding.get(key)
                    if value:
                        workspace_runtime_context[key] = value
            config.runtime_context = {
                **dict(config.runtime_context),
                **workspace_runtime_context,
            }
        # Set session_id for announce message polling (P0.5)
        config.session_id = conversation_id
        # Pass forced skill context to processor for loop reinforcement (Fix 4)
        if is_forced and matched_skill:
            config.forced_skill_name = matched_skill.name
            forced_skill_tools = tuple(dict.fromkeys((*matched_skill.tools, *mcp_tool_names)))
            config.forced_skill_tools = list(forced_skill_tools) if forced_skill_tools else None

        # Rebuild model-specific reasoning options after an explicit route change.
        route_changed = previous_model_route != effective_model_route
        if route_changed:
            from src.infrastructure.llm.reasoning_config import build_reasoning_config

            provider_options = dict(config.provider_options)
            for key in (
                "reasoning_effort",
                "thinking",
                "reasoning_split",
                "__omit_temperature",
                "__use_max_completion_tokens",
                "__override_max_tokens",
            ):
                provider_options.pop(key, None)

            reasoning_cfg = build_reasoning_config(effective_model_route.model_id)
            if reasoning_cfg:
                provider_options.update(reasoning_cfg.provider_options)
                provider_options["__omit_temperature"] = reasoning_cfg.omit_temperature
                provider_options["__use_max_completion_tokens"] = (
                    reasoning_cfg.use_max_completion_tokens
                )
                provider_options["__override_max_tokens"] = reasoning_cfg.override_max_tokens
            config.provider_options = provider_options

        # Apply per-request LLM overrides (F1.4)
        if llm_overrides:

            def _to_float(value: Any) -> float | None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None

            def _to_int(value: Any) -> int | None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None

            if "temperature" in llm_overrides:
                parsed = _to_float(llm_overrides["temperature"])
                if parsed is not None:
                    config.temperature = parsed
            if "max_tokens" in llm_overrides:
                parsed = _to_int(llm_overrides["max_tokens"])
                if parsed is not None:
                    config.max_tokens = parsed
            if "top_p" in llm_overrides:
                parsed = _to_float(llm_overrides["top_p"])
                if parsed is not None:
                    config.provider_options["top_p"] = parsed
            if "frequency_penalty" in llm_overrides:
                parsed = _to_float(llm_overrides["frequency_penalty"])
                if parsed is not None:
                    config.provider_options["frequency_penalty"] = parsed
            if "presence_penalty" in llm_overrides:
                parsed = _to_float(llm_overrides["presence_penalty"])
                if parsed is not None:
                    config.provider_options["presence_penalty"] = parsed

            # Thinking-level override: map the requested effort onto
            # provider-specific reasoning options for the effective model.
            # Non-reasoning models simply ignore the request.
            raw_reasoning_effort = llm_overrides.get("reasoning_effort")
            if isinstance(raw_reasoning_effort, str) and raw_reasoning_effort.strip():
                effort = raw_reasoning_effort.strip().lower()
                if effort in ("low", "medium", "high"):
                    from src.infrastructure.llm.reasoning_config import build_reasoning_config

                    budget_by_effort = {"low": 4096, "medium": 10000, "high": 32000}
                    reasoning_cfg = build_reasoning_config(
                        effective_model_route.model_id,
                        thinking_override=True,
                        reasoning_effort=effort,
                        thinking_budget_tokens=budget_by_effort[effort],
                    )
                    if reasoning_cfg:
                        config.provider_options.update(reasoning_cfg.provider_options)

        if workspace_replan_turn:
            config.provider_options["tool_choice"] = "required"
        processor = self._processor_factory.create_for_main(
            config=config,
            tools=tools_to_use,
        )

        # Inject language guidance so the agent's user-facing replies match
        # the user's preferred UI language. ``runtime_preferred_language``
        # is the per-turn override from the workspace runtime payload; the
        # resolver also falls back to the request-scoped locale set by
        # ``LocaleMiddleware`` (``X-Language`` / ``Accept-Language`` /
        # persisted user preference).
        _language = resolve_response_language(
            runtime_override=runtime_preferred_language,
        )
        await processor.add_runtime_guidance(directive_for(_language))

        # Inject lane JIT guidance (friction signals + matched playbooks +
        # entry-gate checks) for workspace-scoped sessions. No-op for
        # non-workspace chats. Failures are logged and swallowed so this
        # cannot break the agent loop.
        await self._inject_lane_jit_guidance(
            processor=processor,
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_task=workspace_root_task,
        )

        langfuse_context = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "message_id": message_id,
            "sandbox_id": self._extract_sandbox_id_from_tools(tool_set=turn_tool_set),
            "agent_name": selected_agent.name,
        }

        # Phase 13: Event processing
        async for event in self._stream_process_events(
            processor=processor,
            messages=messages,
            langfuse_context=langfuse_context,
            abort_signal=abort_signal,
            matched_skill=matched_skill,
            agent_id=agent_id,
            plugin_generation=plugin_generation,
        ):
            yield event

        # Phase 13b: Heartbeat reply processing
        if self._heartbeat_runner and heartbeat_prompt:
            hb_reply = self._heartbeat_runner.process_reply(self._stream_final_content)
            if hb_reply.should_suppress:
                logger.debug("[ReActAgent] Heartbeat reply acknowledged (HEARTBEAT_OK)")
            elif hb_reply.did_strip:
                self._stream_final_content = hb_reply.cleaned_text

        # Phase 14: Post-processing
        # Calculate execution time before post-process (post-process is
        # lightweight — just hook delivery — so this is accurate enough).
        execution_time_ms = int((time.time() - start_time) * 1000)
        # Settle the forced-skill execution lifecycle so clients render the
        # terminal state instead of freezing at the matched step.
        if matched_skill and should_inject_prompt:
            yield cast(
                dict[str, Any],
                AgentSkillExecutionCompleteEvent(
                    skill_id=matched_skill.id,
                    skill_name=matched_skill.name,
                    success=bool(self._stream_success),
                    tool_results=[],
                    execution_time_ms=execution_time_ms,
                    summary=None,
                    error=None,
                ).to_event_dict(),
            )
        # Count tool calls from conversation context for skill evolution capture.
        tool_call_count = sum(
            1 for msg in conversation_context if msg.get("role") in ("tool", "function")
        )
        async for event in self._stream_post_process(
            processed_user_message=processed_user_message,
            final_content=self._stream_final_content,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            conversation_context=conversation_context,
            matched_skill=matched_skill,
            success=self._stream_success,
            execution_time_ms=execution_time_ms,
            tool_call_count=tool_call_count,
            llm_client_override=(
                config.llm_client if resolved_model_route_override is not None else None
            ),
        ):
            yield event

        # Finally: Record execution statistics
        end_time = time.time()
        execution_time_ms = int((end_time - start_time) * 1000)
        logger.debug(f"[ReActAgent] Stream finished in {execution_time_ms}ms")
        self._stream_record_skill_usage(matched_skill, self._stream_success)

    async def astream_multi_level(
        self: _StreamAgent,
        conversation_id: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
        user_query: str,
        conversation_context: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream with multi-level thinking (compatibility wrapper for ``stream``)."""
        async for event in self.stream(
            conversation_id=conversation_id,
            user_message=user_query,
            project_id=project_id,
            user_id=user_id,
            tenant_id=tenant_id,
            conversation_context=conversation_context,
        ):
            yield event
