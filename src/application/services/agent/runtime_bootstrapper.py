"""Agent runtime bootstrapping extracted from AgentService."""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from src.domain.model.agent import Conversation

logger = logging.getLogger(__name__)


class AgentRuntimeBootstrapper:
    """Handles Ray/Local runtime initialization for agent execution."""

    _local_bootstrapped = False
    _local_bootstrap_lock = asyncio.Lock()

    async def start_chat_actor(
        self,
        conversation: Conversation,
        message_id: str,
        user_message: str,
        conversation_context: list[Dict[str, Any]],
        attachment_ids: Optional[List[str]] = None,
        correlation_id: Optional[str] = None,
    ) -> str:
        """Start agent execution via Ray Actor, with local fallback."""
        from src.configuration.config import get_settings
        from src.infrastructure.agent.actor.actor_manager import (
            get_or_create_actor,
            register_project,
        )
        from src.infrastructure.agent.actor.types import (
            ProjectAgentActorConfig,
            ProjectChatRequest,
        )

        settings = get_settings()
        agent_mode = "default"

        config = ProjectAgentActorConfig(
            tenant_id=conversation.tenant_id,
            project_id=conversation.project_id,
            agent_mode=agent_mode,
            model=self._get_model(settings),
            api_key=self._get_api_key(settings),
            base_url=self._get_base_url(settings),
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
            correlation_id=correlation_id,
        )

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

            asyncio.create_task(_fire_and_forget_ray())
            logger.info("[AgentService] Using Ray Actor for conversation %s", conversation.id)
        else:
            asyncio.create_task(self._run_chat_local(config, chat_request))
            logger.info(
                "[AgentService] Using local execution (Ray unavailable) for conversation %s",
                conversation.id,
            )

        return f"agent:{conversation.tenant_id}:{conversation.project_id}:{agent_mode}"

    async def _run_chat_local(
        self,
        config: Any,
        request: Any,
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

            result = await execute_project_chat(agent, request)

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
                return

            from src.configuration.factories import create_native_graph_adapter
            from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
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
            from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
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

    def _get_api_key(self, settings):
        provider = settings.llm_provider.strip().lower()
        if provider == "openai":
            return settings.openai_api_key
        if provider == "qwen":
            return settings.qwen_api_key
        if provider == "deepseek":
            return settings.deepseek_api_key
        if provider == "gemini":
            return settings.gemini_api_key
        return None

    def _get_base_url(self, settings):
        provider = settings.llm_provider.strip().lower()
        if provider == "openai":
            return settings.openai_base_url
        if provider == "qwen":
            return settings.qwen_base_url
        if provider == "deepseek":
            return settings.deepseek_base_url
        return None

    def _get_model(self, settings):
        """Get the LLM model name based on the configured provider."""
        provider = settings.llm_provider.strip().lower()
        if provider == "openai":
            return settings.openai_model
        if provider == "qwen":
            return settings.qwen_model
        if provider == "deepseek":
            return settings.deepseek_model
        if provider == "gemini":
            return settings.gemini_model
        if provider == "zai" or provider == "zhipu":
            return settings.zai_model
        return "qwen-plus"
