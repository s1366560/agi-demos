"""Agent runtime bootstrapping extracted from AgentService."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, ClassVar

from src.configuration.config import Settings
from src.domain.model.agent import Conversation

if TYPE_CHECKING:
    from src.infrastructure.agent.actor.types import ProjectAgentActorConfig, ProjectChatRequest

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[Any]] = set()


class AgentRuntimeBootstrapper:
    """Handles Ray/Local runtime initialization for agent execution."""

    _local_bootstrapped: ClassVar[bool] = False
    _local_bootstrap_lock = asyncio.Lock()
    _local_chat_lock = asyncio.Lock()
    _local_chat_tasks: ClassVar[dict[str, asyncio.Task[Any]]] = {}
    _local_chat_abort_signals: ClassVar[dict[str, asyncio.Event]] = {}

    @staticmethod
    def _normalize_runtime_mode(mode: str | None) -> str:
        """Normalize runtime mode value."""
        normalized = (mode or "auto").strip().lower()
        if normalized in {"auto", "ray", "local"}:
            return normalized
        return "auto"

    async def start_chat_actor(
        self,
        conversation: Conversation,
        message_id: str,
        user_message: str,
        conversation_context: list[dict[str, Any]],
        attachment_ids: list[str] | None = None,
        file_metadata: list[Any] | None = None,
        correlation_id: str | None = None,
        forced_skill_name: str | None = None,
        context_summary_data: dict[str, Any] | None = None,
        app_model_context: dict[str, Any] | None = None,
    ) -> str:
        """Start agent execution using configured runtime mode."""
        from src.configuration.config import get_settings
        from src.infrastructure.agent.actor.types import (
            ProjectAgentActorConfig,
            ProjectChatRequest,
        )
        from src.infrastructure.llm.provider_factory import get_ai_service_factory
        from src.infrastructure.security.encryption_service import get_encryption_service

        settings = get_settings()
        agent_mode = "default"
        runtime_mode = self._normalize_runtime_mode(settings.agent_runtime_mode)

        # Resolve provider config from DB
        factory = get_ai_service_factory()
        provider_config = await factory.resolve_provider(conversation.tenant_id)

        # Decrypt API key for the actor
        encryption_service = get_encryption_service()
        api_key = encryption_service.decrypt(provider_config.api_key_encrypted)

        config = ProjectAgentActorConfig(
            tenant_id=conversation.tenant_id,
            project_id=conversation.project_id,
            agent_mode=agent_mode,
            model=provider_config.llm_model,
            api_key=api_key,
            base_url=provider_config.base_url,
            temperature=0.7,
            max_tokens=settings.agent_max_tokens,
            max_steps=settings.agent_max_steps,
            persistent=True,
            mcp_tools_ttl_seconds=300,
            max_concurrent_chats=10,
            enable_skills=True,
            enable_subagents=True,
        )

        chat_request = ProjectChatRequest(
            conversation_id=conversation.id,
            message_id=message_id,
            user_message=user_message,
            user_id=conversation.user_id,
            conversation_context=conversation_context,
            attachment_ids=attachment_ids,
            file_metadata=file_metadata,
            correlation_id=correlation_id,
            forced_skill_name=forced_skill_name,
            context_summary_data=context_summary_data,
            plan_mode=conversation.is_in_plan_mode,
            app_model_context=app_model_context,
        )

        if runtime_mode == "local":
            await self._register_project_local(conversation.tenant_id, conversation.project_id)
            await self._start_local_chat(conversation.id, config, chat_request)
            logger.info(
                "[AgentService] Using local execution (AGENT_RUNTIME_MODE=local) for conversation %s",
                conversation.id,
            )
            return f"agent:{conversation.tenant_id}:{conversation.project_id}:{agent_mode}"

        from src.infrastructure.agent.actor.actor_manager import (
            ensure_router_actor,
            get_or_create_actor,
            register_project,
        )

        if runtime_mode == "ray":
            from src.infrastructure.adapters.secondary.ray.client import await_ray

            router = await ensure_router_actor()
            if router is None:
                raise RuntimeError(
                    "AGENT_RUNTIME_MODE=ray but Ray router actor is unavailable. "
                    "Use AGENT_RUNTIME_MODE=auto or local."
                )
            await await_ray(
                router.add_project.remote(conversation.tenant_id, conversation.project_id)
            )
        else:
            await register_project(conversation.tenant_id, conversation.project_id)

        actor = await get_or_create_actor(
            tenant_id=conversation.tenant_id,
            project_id=conversation.project_id,
            agent_mode=agent_mode,
            config=config,
        )

        if actor is not None:
            from src.infrastructure.adapters.secondary.ray.client import await_ray

            async def _fire_and_forget_ray() -> None:
                try:
                    await await_ray(actor.chat.remote(chat_request))
                except Exception as e:
                    logger.error(
                        "[AgentService] Actor chat failed: conversation=%s error=%s",
                        conversation.id,
                        e,
                        exc_info=True,
                    )

            task = asyncio.create_task(_fire_and_forget_ray())
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
            logger.info(
                "[AgentService] Using Ray Actor (AGENT_RUNTIME_MODE=%s) for conversation %s",
                runtime_mode,
                conversation.id,
            )
        elif runtime_mode == "ray":
            raise RuntimeError(
                "AGENT_RUNTIME_MODE=ray but failed to create Ray actor. "
                "Use AGENT_RUNTIME_MODE=auto or local."
            )
        else:
            await self._register_project_local(conversation.tenant_id, conversation.project_id)
            await self._start_local_chat(conversation.id, config, chat_request)
            logger.info(
                "[AgentService] Using local execution (Ray unavailable, AGENT_RUNTIME_MODE=auto) "
                "for conversation %s",
                conversation.id,
            )

        return f"agent:{conversation.tenant_id}:{conversation.project_id}:{agent_mode}"

    @staticmethod
    async def _register_project_local(tenant_id: str, project_id: str) -> None:
        """Register project with local HITL resume consumer."""
        from src.infrastructure.agent.hitl.local_resume_consumer import register_project_local

        await register_project_local(tenant_id, project_id)

    async def _start_local_chat(
        self, conversation_id: str, config: ProjectAgentActorConfig, request: ProjectChatRequest
    ) -> None:
        """Start local execution task and register cancellation signal."""
        abort_signal = asyncio.Event()
        task = asyncio.create_task(self._run_chat_local(config, request, abort_signal=abort_signal))
        await self._track_local_chat_task(conversation_id, task, abort_signal)

    @classmethod
    async def _track_local_chat_task(
        cls,
        conversation_id: str,
        task: asyncio.Task[Any],
        abort_signal: asyncio.Event,
    ) -> None:
        """Track local task and ensure previous in-flight execution is cancelled."""
        async with cls._local_chat_lock:
            previous_abort = cls._local_chat_abort_signals.get(conversation_id)
            previous_task = cls._local_chat_tasks.get(conversation_id)

            if previous_abort:
                previous_abort.set()
            if previous_task and not previous_task.done():
                previous_task.cancel()

            cls._local_chat_tasks[conversation_id] = task
            cls._local_chat_abort_signals[conversation_id] = abort_signal

        task.add_done_callback(
            lambda done_task: cls._schedule_local_chat_cleanup(conversation_id, done_task)
        )

    @classmethod
    def _schedule_local_chat_cleanup(cls, conversation_id: str, task: asyncio.Task[Any]) -> None:
        """Schedule async cleanup for tracked local task."""
        try:
            task = asyncio.create_task(cls._cleanup_local_chat_task(conversation_id, task))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
        except RuntimeError:
            # Event loop closed; best-effort direct cleanup.
            if cls._local_chat_tasks.get(conversation_id) is task:
                cls._local_chat_tasks.pop(conversation_id, None)
                cls._local_chat_abort_signals.pop(conversation_id, None)

    @classmethod
    async def _cleanup_local_chat_task(cls, conversation_id: str, task: asyncio.Task[Any]) -> None:
        """Cleanup tracked local task if it is still current."""
        async with cls._local_chat_lock:
            if cls._local_chat_tasks.get(conversation_id) is task:
                cls._local_chat_tasks.pop(conversation_id, None)
                cls._local_chat_abort_signals.pop(conversation_id, None)

    @classmethod
    async def cancel_local_chat(cls, conversation_id: str) -> bool:
        """Cancel locally running chat task for a conversation."""
        async with cls._local_chat_lock:
            abort_signal = cls._local_chat_abort_signals.get(conversation_id)
            task = cls._local_chat_tasks.get(conversation_id)

            if abort_signal:
                abort_signal.set()

            if task and not task.done():
                task.cancel()
                return True

            cls._local_chat_tasks.pop(conversation_id, None)
            cls._local_chat_abort_signals.pop(conversation_id, None)
            return False

    async def _run_chat_local(
        self,
        config: ProjectAgentActorConfig,
        request: ProjectChatRequest,
        abort_signal: asyncio.Event | None = None,
    ) -> None:
        """Run agent chat locally in-process when Ray is unavailable."""
        from src.infrastructure.agent.actor.execution import execute_project_chat
        from src.infrastructure.agent.core.project_react_agent import (
            ProjectAgentConfig,
            ProjectReActAgent,
        )

        try:
            await self._ensure_local_runtime_bootstrapped()

            agent_config = ProjectAgentConfig(
                tenant_id=config.tenant_id,
                project_id=config.project_id,
                agent_mode=config.agent_mode,
                model=config.model,
                api_key=config.api_key,
                base_url=config.base_url,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                max_steps=config.max_steps,
                persistent=False,
                idle_timeout_seconds=config.idle_timeout_seconds,
                max_concurrent_chats=config.max_concurrent_chats,
                mcp_tools_ttl_seconds=config.mcp_tools_ttl_seconds,
                enable_skills=config.enable_skills,
                enable_subagents=config.enable_subagents,
            )

            agent = ProjectReActAgent(agent_config)
            await agent.initialize()

            # Inject plan repository for Plan Mode awareness
            try:
                from src.configuration.di_container import get_container  # type: ignore[attr-defined]

                container = get_container()
                agent._plan_repo = container._agent.plan_repository()
            except Exception:
                pass  # Plan Mode awareness is optional

            result = await execute_project_chat(agent, request, abort_signal=abort_signal)

            if result.is_error:
                logger.warning(
                    "[AgentService] Local chat failed: message_id=%s error=%s",
                    request.message_id,
                    result.error_message,
                )
            else:
                logger.info(
                    "[AgentService] Local chat completed: message_id=%s events=%d",
                    request.message_id,
                    result.event_count,
                )
        except Exception as e:
            logger.error(
                "[AgentService] Local chat error: conversation=%s error=%s",
                request.conversation_id,
                e,
                exc_info=True,
            )
            try:
                from src.infrastructure.agent.actor.execution import _publish_error_event

                await _publish_error_event(
                    conversation_id=request.conversation_id,
                    message_id=request.message_id,
                    error_message=f"Agent execution failed: {e}",
                    correlation_id=request.correlation_id,
                )
            except Exception as pub_err:
                logger.warning("[AgentService] Failed to publish error event: %s", pub_err)

    async def _ensure_local_runtime_bootstrapped(self) -> None:
        """Bootstrap shared services for local (non-Ray) agent execution."""
        if AgentRuntimeBootstrapper._local_bootstrapped:
            return

        async with AgentRuntimeBootstrapper._local_bootstrap_lock:
            if AgentRuntimeBootstrapper._local_bootstrapped:
                return  # type: ignore[unreachable]

            from src.configuration.factories import create_native_graph_adapter
            from src.infrastructure.agent.state.agent_worker_state import (
                get_agent_graph_service,
                set_agent_graph_service,
            )
            from src.infrastructure.llm.initializer import initialize_default_llm_providers

            try:
                await initialize_default_llm_providers()
            except Exception as e:
                logger.warning("[AgentService] LLM provider init failed: %s", e)

            if not get_agent_graph_service():
                try:
                    graph_service = await create_native_graph_adapter()
                    set_agent_graph_service(graph_service)
                    logger.info("[AgentService] Graph service bootstrapped for local execution")
                except Exception as e:
                    logger.error("[AgentService] Graph service init failed: %s", e)
                    raise

            # Initialize MCP Sandbox Adapter for Project Sandbox tool loading
            from src.infrastructure.agent.state.agent_worker_state import (
                get_mcp_sandbox_adapter,
                set_mcp_sandbox_adapter,
                sync_mcp_sandbox_adapter_from_docker,
            )

            if not get_mcp_sandbox_adapter():
                try:
                    from src.configuration.config import get_settings
                    from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
                        MCPSandboxAdapter,
                    )

                    settings = get_settings()
                    mcp_sandbox_adapter = MCPSandboxAdapter(
                        mcp_image=settings.sandbox_default_image,
                        default_timeout=settings.sandbox_timeout_seconds,
                        default_memory_limit=settings.sandbox_memory_limit,
                        default_cpu_limit=settings.sandbox_cpu_limit,
                    )
                    set_mcp_sandbox_adapter(mcp_sandbox_adapter)
                    count = await sync_mcp_sandbox_adapter_from_docker()
                    if count > 0:
                        logger.info(
                            "[AgentService] Synced %d existing sandboxes from Docker", count
                        )
                    logger.info(
                        "[AgentService] MCP Sandbox adapter bootstrapped for local execution"
                    )
                except Exception as e:
                    logger.warning(
                        "[AgentService] MCP Sandbox adapter init failed "
                        "(Sandbox tools disabled): %s",
                        e,
                    )

            AgentRuntimeBootstrapper._local_bootstrapped = True

    def _get_api_key(self, settings: Settings) -> None:
        # Deprecated: Using ProviderResolutionService now
        return None

    def _get_base_url(self, settings: Settings) -> None:
        # Deprecated: Using ProviderResolutionService now
        return None

    def _get_model(self, settings: Settings) -> str:
        # Deprecated: Using ProviderResolutionService now
        return "qwen-plus"
