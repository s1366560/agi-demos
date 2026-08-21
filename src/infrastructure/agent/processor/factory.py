"""ProcessorFactory - Centralized processor creation with shared heavy deps.

The factory holds long-lived, shared dependencies (LLM client, permission
manager, artifact service) and produces configured SessionProcessor instances
for both the main agent and SubAgents.  It replaces the ad-hoc construction
scattered across SubAgentProcess, ParallelScheduler, BackgroundExecutor, and
SubAgentChain.

Design:
    - frozen=True: factory is immutable after creation.
    - create_for_subagent(): builds ProcessorConfig from SubAgent settings,
      resolving model inheritance.
    - create_for_main(): wraps an already-built ProcessorConfig and attaches
      shared deps.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService
    from src.domain.llm_providers.llm_types import LLMClient
    from src.domain.ports.agent.control_channel_port import ControlChannelPort
    from src.infrastructure.agent.commands.interceptor import CommandInterceptor
    from src.infrastructure.agent.permission.manager import PermissionManager
    from src.infrastructure.agent.tools.pipeline import ToolPipeline

from src.domain.model.agent.subagent import AgentModel, SubAgent
from src.infrastructure.agent.model_route import ModelRouteRef
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error

from .processor import ProcessorConfig, SessionProcessor, ToolDefinition


class AgentLoopResolverLike(Protocol):
    def resolve(self, provider_id: str, model_id: str) -> object: ...


@dataclass(frozen=True)
class ProcessorFactory:
    """Immutable factory for creating SessionProcessor instances.

    Holds shared heavy dependencies that are expensive to create or should
    be shared across processor instances (LLM client with circuit breaker,
    permission manager, artifact service).

    Attributes:
        llm_client: Shared LLM client instance (circuit breaker + rate limiter).
        permission_manager: Permission manager for tool access control.
        artifact_service: Artifact service for rich outputs.
        command_interceptor: Command interceptor for slash commands (main agent only).
        base_model: Default model name (used when SubAgent inherits).
        base_provider_id: Provider identity inherited by SubAgent turns.
        base_api_key: API key for LLM calls.
        base_url: Base URL for LLM API.
        tool_pipeline: ToolPipeline | None = None
    """

    llm_client: LLMClient | None = None
    permission_manager: PermissionManager | None = None
    artifact_service: ArtifactService | None = None
    command_interceptor: CommandInterceptor | None = None
    base_model: str = ""
    base_provider_id: str = ""
    base_api_key: str | None = None
    base_url: str | None = None
    tool_pipeline: ToolPipeline | None = None
    plugin_registry: object | None = None
    plugin_event_dispatcher: object | None = None
    message_bus: object | None = None
    control_channel: ControlChannelPort | None = None

    def create_for_subagent(
        self,
        subagent: SubAgent,
        tools: list[ToolDefinition],
        *,
        model_override: str | None = None,
        configured_model_route: ModelRouteRef | None = None,
        model_route_override: ModelRouteRef | None = None,
        abort_signal: asyncio.Event | None = None,
        doom_loop_threshold: int | None = None,
        thinking_override: bool | None = None,
        run_id: str | None = None,
    ) -> SessionProcessor:
        """Create a SessionProcessor configured for a SubAgent.

        Resolves an explicit provider/model pair. Inherited models use the
        factory's pinned base pair; configured and retry models require their
        own ``ModelRouteRef``.

        Args:
            subagent: The SubAgent definition.
            tools: Filtered tool definitions for this SubAgent.
            model_override: Optional legacy model value, valid only with a matching route.
            configured_model_route: Explicit route for a SubAgent-declared model.
            model_route_override: Explicit route for a spawn or retry override.
            abort_signal: Not used by processor directly; caller manages abort.
            doom_loop_threshold: Optional doom-loop detection threshold.
                Defaults to 3 (ProcessorConfig default). Subagents typically
                use a tighter threshold than the main agent.
            thinking_override: If True, enable extended thinking for Anthropic models.

        Returns:
            Configured SessionProcessor instance.
        """
        normalized_model_override = (model_override or "").strip() or None
        if model_route_override is not None:
            if (
                normalized_model_override is not None
                and model_route_override.model_id != normalized_model_override
            ):
                raise RuntimeV2Error(
                    "subagent_model_override_route_mismatch",
                    f"subagent model override {normalized_model_override} does not match route "
                    f"model {model_route_override.model_id}",
                )
            model_route = model_route_override
        elif normalized_model_override is not None:
            raise RuntimeV2Error(
                "subagent_model_override_route_missing",
                f"subagent model override {normalized_model_override} has no provider route",
            )
        elif subagent.model != AgentModel.INHERIT:
            declared_model = subagent.model.value
            if configured_model_route is None:
                raise RuntimeV2Error(
                    "subagent_model_route_missing",
                    f"subagent {subagent.id} declares model {declared_model} "
                    "without an explicit provider route",
                )
            if configured_model_route.model_id != declared_model:
                raise RuntimeV2Error(
                    "subagent_model_route_mismatch",
                    f"subagent {subagent.id} declares model {declared_model}, but its route "
                    f"declares {configured_model_route.model_id}",
                )
            model_route = configured_model_route
        elif configured_model_route is not None:
            if configured_model_route.model_id != self.base_model:
                raise RuntimeV2Error(
                    "subagent_model_route_mismatch",
                    f"inherited model {self.base_model} does not match route model "
                    f"{configured_model_route.model_id}",
                )
            model_route = configured_model_route
        else:
            model_route = ModelRouteRef(
                provider_id=self.base_provider_id,
                model_id=self.base_model,
            )
        model = model_route.model_id

        from src.infrastructure.llm.reasoning_config import build_reasoning_config

        _reasoning_cfg = build_reasoning_config(model, thinking_override=thinking_override)
        _provider_opts: dict[str, Any] = {}
        if _reasoning_cfg:
            _provider_opts = {
                **_reasoning_cfg.provider_options,
                "__omit_temperature": _reasoning_cfg.omit_temperature,
                "__use_max_completion_tokens": _reasoning_cfg.use_max_completion_tokens,
                "__override_max_tokens": _reasoning_cfg.override_max_tokens,
            }

        config = ProcessorConfig(
            model=model,
            api_key=self.base_api_key,
            base_url=self.base_url,
            temperature=subagent.temperature,
            max_tokens=subagent.max_tokens,
            max_steps=subagent.max_iterations,
            llm_client=self.llm_client,
            plugin_registry=self.plugin_registry,
            plugin_event_dispatcher=self.plugin_event_dispatcher,
            doom_loop_threshold=doom_loop_threshold if doom_loop_threshold is not None else 3,
            provider_options=_provider_opts,
            message_bus=self.message_bus,
            control_channel=self.control_channel,
            run_id=run_id,
            provider_id=model_route.provider_id,
            loop_resolver=_default_loop_resolver(),
        )

        return SessionProcessor(
            config=config,
            tools=tools,
            permission_manager=self.permission_manager,
            artifact_service=self.artifact_service,
            tool_pipeline=self.tool_pipeline,
        )

    def create_for_main(
        self,
        config: ProcessorConfig,
        tools: list[ToolDefinition],
    ) -> SessionProcessor:
        """Create a SessionProcessor for the main agent.

        Uses the caller-supplied ProcessorConfig (which may include
        tool_provider, forced_skill_name, etc.) and attaches shared deps.

        Args:
            config: Pre-built ProcessorConfig from the main agent.
            tools: Tool definitions for this invocation.

        Returns:
            Configured SessionProcessor instance.
        """
        config.loop_resolver = _default_loop_resolver()
        return SessionProcessor(
            config=config,
            tools=tools,
            permission_manager=self.permission_manager,
            artifact_service=self.artifact_service,
            command_interceptor=self.command_interceptor,
            tool_pipeline=self.tool_pipeline,
        )


def _default_loop_resolver() -> AgentLoopResolverLike:
    """Resolve the required agent-loop service from the pinned v2 operation."""
    from src.infrastructure.plugins.v2.agent_loop import AGENT_LOOP_RESOLVER_SERVICE_V2
    from src.infrastructure.plugins.v2.boundary import current_operation_context_v2

    operation = current_operation_context_v2()
    resolver = operation.require(AGENT_LOOP_RESOLVER_SERVICE_V2)
    if not callable(getattr(resolver, "resolve", None)):
        raise RuntimeError("v2 agent loop resolver has no callable resolve method")
    return cast(AgentLoopResolverLike, resolver)
