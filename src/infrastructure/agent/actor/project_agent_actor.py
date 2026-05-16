"""Project-level Ray Actor for Agent execution."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import ray

from src.configuration.config import get_settings
from src.configuration.factories import create_native_graph_adapter
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
from src.infrastructure.agent.state.agent_worker_state import (
    set_agent_graph_service,
    set_mcp_sandbox_adapter,
    sync_mcp_sandbox_adapter_from_docker,
)
from src.infrastructure.llm.initializer import initialize_default_llm_providers

logger = logging.getLogger(__name__)


@ray.remote(max_restarts=5, max_task_retries=3, max_concurrency=10)  # type: ignore[call-overload]
class ProjectAgentActor:
    """Ray Actor that runs a project-level agent instance."""

    def __init__(self) -> None:
        self._config: ProjectAgentActorConfig | None = None
        self._agent: ProjectReActAgent | None = None
        self._created_at = datetime.now(UTC)
        self._lease_owner_suffix = str(uuid.uuid4())
        self._bootstrapped = False
        self._bootstrap_lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._task_conversations: dict[str, str] = {}
        self._abort_signals: dict[str, asyncio.Event] = {}
        self._current_conversation_id: str | None = None
        self._current_message_id: str | None = None

    @staticmethod
    def actor_id(tenant_id: str, project_id: str, agent_mode: str) -> str:
        return f"agent:{tenant_id}:{project_id}:{agent_mode}"

    async def initialize(
        self, config: ProjectAgentActorConfig, force_refresh: bool = False
    ) -> dict[str, Any]:
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

            # Inject plan repository for Plan Mode awareness
            try:
                from src.infrastructure.adapters.primary.web.startup.container import (
                    get_app_container,
                )

                container = get_app_container()
                if container is not None:
                    agent_container = getattr(container, "_agent", None)
                    plan_repository_factory = getattr(agent_container, "plan_repository", None)
                    if callable(plan_repository_factory):
                        self._agent._plan_repo = plan_repository_factory()
            except Exception:
                pass  # Plan Mode awareness is optional

            status = "initialized" if success else "error"

            return {"status": status, "cached": False}

    async def chat(self, request: ProjectChatRequest) -> dict[str, Any]:
        """Start a chat execution in the background."""
        if not self._agent:
            if not self._config:
                raise RuntimeError("Actor config not set")
            await self.initialize(self._config)

        abort_signal = asyncio.Event()
        task = asyncio.create_task(self._run_chat(request, abort_signal))
        self._tasks[request.message_id] = task
        self._task_conversations[request.message_id] = request.conversation_id
        self._abort_signals[request.message_id] = abort_signal

        # Add cleanup callback
        task.add_done_callback(lambda t: self._cleanup_task(request.message_id))

        return {"status": "started", "message_id": request.message_id}

    async def continue_chat(
        self,
        request_id: str,
        response_data: dict[str, Any],
        conversation_id: str | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        """Continue a paused chat after HITL response."""
        if not self._agent:
            if not self._config:
                raise RuntimeError("Actor config not set")
            await self.initialize(self._config)

        task = asyncio.create_task(
            self._run_continue(request_id, response_data, conversation_id, message_id)
        )
        self._tasks[request_id] = task
        if conversation_id:
            self._task_conversations[request_id] = conversation_id

        try:
            return await task
        finally:
            self._cleanup_task(request_id)

    def _cleanup_task(self, task_id: str) -> None:
        """Remove task from tracking maps when done."""
        self._tasks.pop(task_id, None)
        self._task_conversations.pop(task_id, None)
        self._abort_signals.pop(task_id, None)

    async def cancel(self, conversation_id: str) -> bool:
        """Cancel running tasks for a conversation."""
        cancelled = False
        # Create a list of items to iterate safely
        for task_id, task in list(self._tasks.items()):
            if task.done():
                continue

            # Check by explicit mapping or legacy current_conversation_id
            is_match = False

            # 1. Check explicit mapping
            if (
                self._task_conversations.get(task_id) == conversation_id
                or self._current_conversation_id == conversation_id
                or conversation_id in task_id
            ):
                is_match = True

            if is_match:
                abort_signal = self._abort_signals.get(task_id)
                if abort_signal:
                    abort_signal.set()
                task.cancel()
                cancelled = True
                logger.info(
                    "[ProjectAgentActor] Cancelled task %s for conversation %s",
                    task_id,
                    conversation_id,
                )

        return cancelled

    async def status(self) -> ProjectAgentStatus:
        """Return current actor status."""
        agent_status = self._agent.get_status() if self._agent else None
        now = datetime.now(UTC)
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
        for abort_signal in self._abort_signals.values():
            abort_signal.set()
        self._tasks.clear()
        self._task_conversations.clear()
        self._abort_signals.clear()

        if self._agent:
            await self._agent.stop()
            self._agent = None
        return True

    async def _run_chat(
        self,
        request: ProjectChatRequest,
        abort_signal: asyncio.Event | None = None,
    ) -> None:
        self._current_conversation_id = request.conversation_id
        self._current_message_id = request.message_id

        if not self._agent:
            return

        result = await execute_project_chat(self._agent, request, abort_signal=abort_signal)
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

    async def _run_continue(
        self,
        request_id: str,
        response_data: dict[str, Any],
        conversation_id: str | None,
        message_id: str | None,
    ) -> dict[str, Any]:
        if not self._agent:
            return {"status": "unavailable", "request_id": request_id, "ack": False}
        agent = self._agent

        from src.infrastructure.agent.hitl.coordinator import (
            ResolveResult,
            resolve_by_request_id,
            wait_for_request_completion,
        )

        resolve_result = resolve_by_request_id(
            request_id,
            response_data,
            tenant_id=self._config.tenant_id if self._config else None,
            project_id=self._config.project_id if self._config else None,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        if resolve_result is ResolveResult.RESOLVED:
            await wait_for_request_completion(request_id)
            logger.info(
                "[ProjectAgentActor] Resolved HITL future: request_id=%s",
                request_id,
            )
            return {
                "status": "resolved",
                "request_id": request_id,
                "ack": True,
                "durably_completed": True,
            }
        if resolve_result is ResolveResult.REJECTED:
            reopened = await self._reopen_answered_request(request_id)
            logger.warning(
                "[ProjectAgentActor] Rejected HITL response: request_id=%s reopened=%s",
                request_id,
                reopened,
            )
            return {
                "status": "rejected",
                "request_id": request_id,
                "ack": reopened,
                "durably_completed": False,
            }

        return await self._resume_continue_request(
            agent=agent,
            request_id=request_id,
            response_data=response_data,
            conversation_id=conversation_id,
            message_id=message_id,
        )

    async def _resume_continue_request(
        self,
        *,
        agent: ProjectReActAgent | None = None,
        request_id: str,
        response_data: dict[str, Any],
        conversation_id: str | None,
        message_id: str | None,
    ) -> dict[str, Any]:
        """Fallback resume path when no in-memory coordinator owns the request."""
        resume_agent = agent if agent is not None else self._agent
        if resume_agent is None:
            return {"status": "unavailable", "request_id": request_id, "ack": False}

        from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )
        from src.infrastructure.agent.hitl.coordinator import complete_hitl_request
        from src.infrastructure.agent.hitl.utils import (
            is_permanent_hitl_resume_error,
            processing_lease_heartbeat,
        )

        async with async_session_factory() as session:
            repo = SqlHITLRequestRepository(session)
            claimed_request = await repo.claim_for_processing(
                request_id,
                lease_owner=self._lease_owner(),
            )
            if claimed_request is None:
                logger.info(
                    "[ProjectAgentActor] Request already claimed for processing: %s",
                    request_id,
                )
                return {
                    "status": "processing",
                    "request_id": request_id,
                    "ack": False,
                    "durably_completed": False,
                }
            await session.commit()

        try:
            async with processing_lease_heartbeat(
                request_id,
                lease_owner=self._lease_owner(),
            ):
                result = await continue_project_chat(
                    resume_agent,
                    request_id,
                    response_data,
                    lease_owner=self._lease_owner(),
                    tenant_id=self._config.tenant_id if self._config else None,
                    project_id=self._config.project_id if self._config else None,
                    conversation_id=conversation_id,
                    message_id=message_id,
                )
        except Exception:
            await self._revert_continue_claim(request_id)
            raise

        if result.hitl_pending:
            logger.info(
                "[ProjectAgentActor] HITL pending (continue): request_id=%s",
                result.hitl_request_id,
            )
        if not result.is_error:
            return {
                "status": "continued",
                "request_id": request_id,
                "ack": True,
                "durably_completed": True,
            }

        logger.warning(
            "[ProjectAgentActor] Continue failed: request_id=%s error=%s",
            request_id,
            result.error_message,
        )
        if is_permanent_hitl_resume_error(result.error_message):
            await complete_hitl_request(request_id, lease_owner=self._lease_owner())
            return {
                "status": "rejected",
                "request_id": request_id,
                "ack": True,
                "durably_completed": False,
                "error": result.error_message,
            }

        await self._revert_continue_claim(request_id)
        return {
            "status": "error",
            "request_id": request_id,
            "ack": False,
            "durably_completed": False,
            "error": result.error_message,
        }

    async def _revert_continue_claim(self, request_id: str) -> None:
        """Return a failed fallback resume claim to ANSWERED for later retry."""
        from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        async with async_session_factory() as session:
            repo = SqlHITLRequestRepository(session)
            reverted_request = await repo.revert_to_answered(
                request_id,
                lease_owner=self._lease_owner(),
            )
            if reverted_request is not None:
                await session.commit()

    async def _reopen_answered_request(self, request_id: str) -> bool:
        """Clear an invalid answered payload so the request can be retried."""
        from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        async with async_session_factory() as session:
            repo = SqlHITLRequestRepository(session)
            reopened_request = await repo.reopen_pending(request_id)
            if reopened_request is None:
                return False
            await session.commit()
            return True

    def _lease_owner(self) -> str:
        """Return a stable lease owner identifier for this actor instance."""
        if self._config is None:
            return "project-actor"
        return (
            self.actor_id(
                self._config.tenant_id,
                self._config.project_id,
                self._config.agent_mode,
            )
            + f":{self._lease_owner_suffix}"
        )

    async def _bootstrap_runtime(self) -> None:
        if self._bootstrapped:
            return

        async with self._bootstrap_lock:
            if self._bootstrapped:
                return  # type: ignore[unreachable]

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

            from src.infrastructure.agent.state.agent_worker_state import (
                get_agent_orchestrator,
                set_agent_orchestrator,
            )

            if not get_agent_orchestrator() and settings.multi_agent_enabled:
                try:
                    from src.application.services.agent.runtime_bootstrapper import (
                        AgentRuntimeBootstrapper,
                    )
                    from src.infrastructure.adapters.secondary.messaging.redis_agent_message_bus import (
                        RedisAgentMessageBusAdapter,
                    )
                    from src.infrastructure.adapters.secondary.persistence.database import (
                        async_session_factory,
                    )
                    from src.infrastructure.adapters.secondary.persistence.sql_agent_registry import (
                        SqlAgentRegistryRepository,
                    )
                    from src.infrastructure.agent.orchestration.orchestrator import (
                        AgentOrchestrator,
                        SpawnExecutionRequest,
                    )
                    from src.infrastructure.agent.orchestration.session_registry import (
                        AgentSessionRegistry,
                    )
                    from src.infrastructure.agent.orchestration.spawn_manager import (
                        SpawnManager,
                    )
                    from src.infrastructure.agent.state.agent_worker_state import (
                        get_redis_client,
                    )
                    from src.infrastructure.agent.subagent.run_registry import (
                        get_shared_subagent_run_registry,
                    )

                    _db_session = async_session_factory()
                    _redis = await get_redis_client()
                    _session_registry = AgentSessionRegistry()
                    _run_registry = get_shared_subagent_run_registry(
                        persistence_path=getattr(
                            settings, "agent_subagent_run_registry_path", None
                        ),
                        postgres_persistence_dsn=getattr(
                            settings, "agent_subagent_run_postgres_dsn", None
                        ),
                        sqlite_persistence_path=getattr(
                            settings, "agent_subagent_run_sqlite_path", None
                        ),
                        redis_cache_url=getattr(
                            settings, "agent_subagent_run_redis_cache_url", None
                        ),
                        redis_cache_ttl_seconds=(
                            getattr(settings, "agent_subagent_run_redis_cache_ttl_seconds", 60)
                        ),
                        terminal_retention_seconds=(
                            settings.agent_subagent_terminal_retention_seconds
                        ),
                    )

                    async def _spawn_executor(request: SpawnExecutionRequest) -> None:
                        conversation = (
                            await AgentRuntimeBootstrapper.ensure_spawned_agent_conversation(
                                child_session_id=request.child_session_id,
                                parent_session_id=request.parent_session_id,
                                project_id=request.project_id,
                                tenant_id=request.tenant_id,
                                user_id=request.user_id,
                                parent_agent_id=request.parent_agent_id,
                                child_agent_id=request.child_agent_id,
                                child_agent_name=request.child_agent_name,
                                mode=request.mode.value,
                            )
                        )
                        tenant_agent_config = (
                            await AgentRuntimeBootstrapper._load_tenant_agent_config(
                                conversation.tenant_id
                            )
                        )
                        await self.chat(
                            ProjectChatRequest(
                                conversation_id=conversation.id,
                                message_id=str(uuid.uuid4()),
                                user_message=request.message,
                                user_id=conversation.user_id,
                                conversation_context=[],
                                plan_mode=conversation.is_in_plan_mode,
                                agent_id=request.child_agent_id,
                                tenant_agent_config=tenant_agent_config.to_dict(),
                                parent_session_id=request.parent_session_id,
                            )
                        )

                    _orchestrator = AgentOrchestrator(
                        agent_registry=SqlAgentRegistryRepository(_db_session),
                        session_registry=_session_registry,
                        spawn_manager=SpawnManager(
                            session_registry=_session_registry,
                            run_registry=_run_registry,
                        ),
                        message_bus=RedisAgentMessageBusAdapter(_redis),
                        db_session=_db_session,
                        spawn_executor=_spawn_executor,
                    )
                    set_agent_orchestrator(_orchestrator)
                    logger.info(
                        "[ProjectAgentActor] AgentOrchestrator bootstrapped for multi-agent tools"
                    )
                except Exception as e:
                    logger.warning(
                        f"[ProjectAgentActor] AgentOrchestrator init failed "
                        f"(multi-agent tools disabled): {e}"
                    )

            self._bootstrapped = True
