"""Project-level Ray Actor for Agent execution."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import ray

from src.configuration.config import get_settings
from src.configuration.factories import create_native_graph_adapter
from src.configuration.temporal_config import get_temporal_settings
from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
    set_agent_graph_service,
    set_mcp_sandbox_adapter,
    set_mcp_temporal_adapter,
    sync_mcp_sandbox_adapter_from_docker,
)
from src.infrastructure.adapters.secondary.temporal.client import get_temporal_client
from src.infrastructure.adapters.secondary.temporal.mcp.adapter import MCPTemporalAdapter
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
    MCPSandboxAdapter,
)
from src.infrastructure.agent.actor.execution import (
    continue_project_chat,
    execute_project_chat,
)
from src.infrastructure.agent.actor.types import (
    ProjectAgentActorConfig,
    ProjectAgentStatus,
    ProjectChatRequest,
)
from src.infrastructure.agent.core.project_react_agent import (
    ProjectAgentConfig,
    ProjectReActAgent,
)
from src.infrastructure.llm.initializer import initialize_default_llm_providers

logger = logging.getLogger(__name__)


@ray.remote(max_restarts=5, max_task_retries=3, max_concurrency=10)
class ProjectAgentActor:
    """Ray Actor that runs a project-level agent instance."""

    def __init__(self) -> None:
        self._config: Optional[ProjectAgentActorConfig] = None
        self._agent: Optional[ProjectReActAgent] = None
        self._created_at = datetime.utcnow()
        self._bootstrapped = False
        self._bootstrap_lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._tasks: Dict[str, asyncio.Task] = {}
        self._current_conversation_id: Optional[str] = None
        self._current_message_id: Optional[str] = None

    @staticmethod
    def actor_id(tenant_id: str, project_id: str, agent_mode: str) -> str:
        return f"agent:{tenant_id}:{project_id}:{agent_mode}"

    async def initialize(self, config: ProjectAgentActorConfig, force_refresh: bool = False) -> Dict[str, Any]:
        """Initialize the ProjectReActAgent instance."""
        async with self._init_lock:
            await self._bootstrap_runtime()
            self._config = config

            if self._agent and not force_refresh:
                return {"status": "initialized", "cached": True}

            if self._agent and force_refresh:
                await self._agent.stop()
                self._agent = None

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
                persistent=config.persistent,
                idle_timeout_seconds=config.idle_timeout_seconds,
                max_concurrent_chats=config.max_concurrent_chats,
                mcp_tools_ttl_seconds=config.mcp_tools_ttl_seconds,
                enable_skills=config.enable_skills,
                enable_subagents=config.enable_subagents,
            )

            self._agent = ProjectReActAgent(agent_config)
            success = await self._agent.initialize(force_refresh=force_refresh)
            status = "initialized" if success else "error"

            return {"status": status, "cached": False}

    async def chat(self, request: ProjectChatRequest) -> Dict[str, Any]:
        """Start a chat execution in the background."""
        if not self._agent:
            if not self._config:
                raise RuntimeError("Actor config not set")
            await self.initialize(self._config)

        task = asyncio.create_task(self._run_chat(request))
        self._tasks[request.message_id] = task
        return {"status": "started", "message_id": request.message_id}

    async def continue_chat(self, request_id: str, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """Continue a paused chat after HITL response."""
        if not self._agent:
            if not self._config:
                raise RuntimeError("Actor config not set")
            await self.initialize(self._config)

        task = asyncio.create_task(self._run_continue(request_id, response_data))
        self._tasks[request_id] = task
        return {"status": "continued", "request_id": request_id}

    async def cancel(self, conversation_id: str) -> bool:
        """Cancel running tasks for a conversation."""
        cancelled = False
        for key, task in list(self._tasks.items()):
            if task.done():
                continue
            if self._current_conversation_id == conversation_id or conversation_id in key:
                task.cancel()
                cancelled = True
        return cancelled

    async def status(self) -> ProjectAgentStatus:
        """Return current actor status."""
        agent_status = self._agent.get_status() if self._agent else None
        now = datetime.utcnow()
        uptime_seconds = (now - self._created_at).total_seconds()

        return ProjectAgentStatus(
            tenant_id=self._config.tenant_id if self._config else "",
            project_id=self._config.project_id if self._config else "",
            agent_mode=self._config.agent_mode if self._config else "default",
            actor_id=self.actor_id(
                self._config.tenant_id if self._config else "",
                self._config.project_id if self._config else "",
                self._config.agent_mode if self._config else "default",
            ),
            is_initialized=agent_status.is_initialized if agent_status else False,
            is_active=agent_status.is_active if agent_status else False,
            is_executing=agent_status.is_executing if agent_status else False,
            total_chats=agent_status.total_chats if agent_status else 0,
            active_chats=agent_status.active_chats if agent_status else 0,
            failed_chats=agent_status.failed_chats if agent_status else 0,
            tool_count=agent_status.tool_count if agent_status else 0,
            skill_count=agent_status.skill_count if agent_status else 0,
            subagent_count=agent_status.subagent_count if agent_status else 0,
            created_at=agent_status.created_at if agent_status else None,
            last_activity_at=agent_status.last_activity_at if agent_status else None,
            uptime_seconds=uptime_seconds,
            current_conversation_id=self._current_conversation_id,
            current_message_id=self._current_message_id,
        )

    async def shutdown(self) -> bool:
        """Stop the actor and cleanup resources."""
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        self._tasks.clear()

        if self._agent:
            await self._agent.stop()
            self._agent = None
        return True

    async def _run_chat(self, request: ProjectChatRequest) -> None:
        self._current_conversation_id = request.conversation_id
        self._current_message_id = request.message_id

        if not self._agent:
            return

        result = await execute_project_chat(self._agent, request)
        if result.hitl_pending:
            logger.info(
                "[ProjectAgentActor] HITL pending: request_id=%s",
                result.hitl_request_id,
            )
        if result.is_error:
            logger.warning(
                "[ProjectAgentActor] Chat failed: message_id=%s error=%s",
                request.message_id,
                result.error_message,
            )

    async def _run_continue(self, request_id: str, response_data: Dict[str, Any]) -> None:
        if not self._agent:
            return
        result = await continue_project_chat(self._agent, request_id, response_data)
        if result.hitl_pending:
            logger.info(
                "[ProjectAgentActor] HITL pending (continue): request_id=%s",
                result.hitl_request_id,
            )
        if result.is_error:
            logger.warning(
                "[ProjectAgentActor] Continue failed: request_id=%s error=%s",
                request_id,
                result.error_message,
            )

    async def _bootstrap_runtime(self) -> None:
        if self._bootstrapped:
            return

        async with self._bootstrap_lock:
            if self._bootstrapped:
                return

            settings = get_settings()

            try:
                await initialize_default_llm_providers()
            except Exception as e:
                logger.warning(f"[ProjectAgentActor] LLM provider init failed: {e}")

            try:
                graph_service = await create_native_graph_adapter()
                set_agent_graph_service(graph_service)
            except Exception as e:
                logger.error(f"[ProjectAgentActor] Graph service init failed: {e}")
                raise

            try:
                temporal_settings = get_temporal_settings()
                temporal_client = await get_temporal_client(temporal_settings)
                mcp_temporal_adapter = MCPTemporalAdapter(temporal_client)
                set_mcp_temporal_adapter(mcp_temporal_adapter)
            except Exception as e:
                logger.warning(f"[ProjectAgentActor] MCP Temporal adapter disabled: {e}")

            try:
                mcp_sandbox_adapter = MCPSandboxAdapter(
                    mcp_image=settings.sandbox_default_image,
                    default_timeout=settings.sandbox_timeout_seconds,
                    default_memory_limit=settings.sandbox_memory_limit,
                    default_cpu_limit=settings.sandbox_cpu_limit,
                )
                set_mcp_sandbox_adapter(mcp_sandbox_adapter)
                await sync_mcp_sandbox_adapter_from_docker()
            except Exception as e:
                logger.warning(f"[ProjectAgentActor] MCP Sandbox adapter disabled: {e}")

            self._bootstrapped = True
