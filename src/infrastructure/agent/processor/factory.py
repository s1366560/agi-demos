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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService
    from src.domain.llm_providers.llm_types import LLMClient
    from src.infrastructure.agent.commands.interceptor import CommandInterceptor
    from src.infrastructure.agent.permission.manager import PermissionManager

from src.domain.model.agent.subagent import AgentModel, SubAgent

from .processor import ProcessorConfig, SessionProcessor, ToolDefinition


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
        base_api_key: API key for LLM calls.
        base_url: Base URL for LLM API.
    """

    llm_client: LLMClient | None = None
    permission_manager: PermissionManager | None = None
    artifact_service: ArtifactService | None = None
    command_interceptor: CommandInterceptor | None = None
    base_model: str = ""
    base_api_key: str | None = None
    base_url: str | None = None

    def create_for_subagent(
        self,
        subagent: SubAgent,
        tools: list[ToolDefinition],
        *,
        model_override: str | None = None,
        abort_signal: asyncio.Event | None = None,
    ) -> SessionProcessor:
        """Create a SessionProcessor configured for a SubAgent.

        Resolves model inheritance: if SubAgent uses INHERIT, falls back to
        base_model or model_override.

        Args:
            subagent: The SubAgent definition.
            tools: Filtered tool definitions for this SubAgent.
            model_override: Optional model override (takes precedence over base_model).
            abort_signal: Not used by processor directly; caller manages abort.

        Returns:
            Configured SessionProcessor instance.
        """
        # Resolve model
        if subagent.model == AgentModel.INHERIT:
            model = model_override or self.base_model
        else:
            model = subagent.model.value

        config = ProcessorConfig(
            model=model,
            api_key=self.base_api_key,
            base_url=self.base_url,
            temperature=subagent.temperature,
            max_tokens=subagent.max_tokens,
            max_steps=subagent.max_iterations,
            llm_client=self.llm_client,
        )

        return SessionProcessor(
            config=config,
            tools=tools,
            permission_manager=self.permission_manager,
            artifact_service=self.artifact_service,
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
        return SessionProcessor(
            config=config,
            tools=tools,
            permission_manager=self.permission_manager,
            artifact_service=self.artifact_service,
            command_interceptor=self.command_interceptor,
        )
