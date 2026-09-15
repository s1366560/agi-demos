"""Project-level Ray Actor for Agent execution."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import ray

from src.application.services.publication_archive_loader_v2 import load_agent_generation_archives_v2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.domain.ports.services.graph_store_port import GraphStorePort
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
from src.infrastructure.plugins.v2.agent_worker_lifecycle_transport_v2 import (
    AgentWorkerLifecycleTransportV2,
)
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    agent_worker_graph_runtime_factory_v2,
    agent_worker_redis_runtime_factory_v2,
    agent_worker_sandbox_runtime_factory_v2,
    agent_worker_workspace_core_runtime_factory_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import DataPlaneGenerationAdmissionV2

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _AgentRuntimeEntryV2:
    """One immutable ProjectReActAgent runtime owned by an exact generation."""

    descriptor: PluginGenerationDescriptorV2
    agent: ProjectReActAgent
    active_leases: int = 0


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
        self._lifecycle_lock = asyncio.Lock()
        self._shutting_down = False
        self._shutdown_task: asyncio.Task[None] | None = None
        self._plugin_admission_v2 = DataPlaneGenerationAdmissionV2(
            builtin_runtime_definitions_v2(
                agent_lifecycle_connection_manager=AgentWorkerLifecycleTransportV2(),
                graph_runtime_factory=self._create_graph_runtime_v2,
                redis_runtime_factory=agent_worker_redis_runtime_factory_v2,
                sandbox_runtime_factory=agent_worker_sandbox_runtime_factory_v2,
                workspace_core_runtime_factory=agent_worker_workspace_core_runtime_factory_v2,
            ),
            archive_loader=load_agent_generation_archives_v2,
        )
        self._agent_generation_descriptor_v2: PluginGenerationDescriptorV2 | None = None
        self._agent_runtime_entries_v2: dict[
            PluginGenerationDescriptorV2, _AgentRuntimeEntryV2
        ] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._task_conversations: dict[str, str] = {}
        self._abort_signals: dict[str, asyncio.Event] = {}
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        self._current_conversation_id: str | None = None
        self._current_message_id: str | None = None

    @staticmethod
    def actor_id(tenant_id: str, project_id: str, agent_mode: str) -> str:
        return f"agent:{tenant_id}:{project_id}:{agent_mode}"

    async def initialize(
        self, config: ProjectAgentActorConfig, force_refresh: bool = False
    ) -> dict[str, Any]:
        """Initialize the ProjectReActAgent instance."""
        async with self._lifecycle_lock:
            self._require_task_registration_open()
            return await self._initialize_locked(config, force_refresh=force_refresh)

    async def _initialize_locked(
        self,
        config: ProjectAgentActorConfig,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Initialize while the actor lifecycle registration gate is held."""
        async with self._init_lock:
            await self._bootstrap_runtime()
            self._config = config

            if self._agent and not force_refresh:
                return {"status": "initialized", "cached": True}

            if self._agent and force_refresh:
                if any(
                    entry.active_leases > 0 for entry in self._agent_runtime_entries_v2.values()
                ):
                    raise RuntimeV2Error(
                        "agent_runtime_refresh_in_use",
                        "project agent runtime cannot be refreshed while generation leases are active",
                    )
                runtime_agents = {
                    id(entry.agent): entry.agent
                    for entry in self._agent_runtime_entries_v2.values()
                }
                runtime_agents[id(self._agent)] = self._agent
                for runtime_agent in runtime_agents.values():
                    await runtime_agent.stop()
                self._agent_runtime_entries_v2.clear()
                self._agent = None
                self._agent_generation_descriptor_v2 = None

            self._agent = self._build_agent_runtime_v2(config)
            self._agent_generation_descriptor_v2 = None

            return {"status": "initialized", "cached": False}

    @staticmethod
    def _build_agent_runtime_v2(config: ProjectAgentActorConfig) -> ProjectReActAgent:
        """Construct one unbound runtime that will be pinned on its first lease."""
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
        agent = ProjectReActAgent(agent_config)

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
                    agent._plan_repo = plan_repository_factory()
        except Exception:
            pass  # Plan Mode awareness is optional

        return agent

    def _require_task_registration_open(self) -> None:
        if self._shutting_down:
            raise RuntimeV2Error(
                "project_agent_actor_shutting_down",
                "project agent actor is shutting down and no longer accepts work",
            )

    async def _ensure_agent_initialized_v2(
        self,
        operation: OperationContextV2,
        *,
        agent: ProjectReActAgent | None = None,
    ) -> ProjectReActAgent:
        """Resolve one immutable runtime for the exact admitted generation."""
        async with self._init_lock:
            entry = await self._ensure_agent_runtime_entry_v2_locked(
                operation,
                preferred_agent=agent,
            )
            retired = self._take_retired_agent_runtimes_v2_locked()
            await self._dispose_agent_runtimes_v2(retired)
        return entry.agent

    async def _ensure_agent_runtime_entry_v2_locked(
        self,
        operation: OperationContextV2,
        *,
        preferred_agent: ProjectReActAgent | None = None,
    ) -> _AgentRuntimeEntryV2:
        """Resolve or create a generation runtime while ``_init_lock`` is held."""
        descriptor = operation.descriptor
        cached = self._agent_runtime_entries_v2.get(descriptor)
        if cached is not None:
            return cached

        target = preferred_agent
        if target is None and not self._agent_runtime_entries_v2:
            target = self._agent
        if target is None:
            if self._config is None:
                raise RuntimeV2Error(
                    "agent_runtime_unavailable",
                    "agent runtime is not configured for the admitted operation",
                )
            target = self._build_agent_runtime_v2(self._config)

        if any(entry.agent is target for entry in self._agent_runtime_entries_v2.values()):
            raise RuntimeV2Error(
                "agent_runtime_generation_conflict",
                "one agent runtime cannot be rebound to another plugin generation",
            )

        success = await target.initialize(force_refresh=False)
        if not success:
            await target.stop(
                generation_descriptor=descriptor,
                notify_lifecycle=False,
            )
            raise RuntimeV2Error(
                "agent_initialization_failed",
                "agent initialization failed for the admitted plugin generation",
            )

        entry = _AgentRuntimeEntryV2(descriptor=descriptor, agent=target)
        self._agent_runtime_entries_v2[descriptor] = entry
        if self._should_promote_agent_runtime_v2(descriptor):
            self._agent = target
            self._agent_generation_descriptor_v2 = descriptor
        return entry

    def _should_promote_agent_runtime_v2(
        self,
        descriptor: PluginGenerationDescriptorV2,
    ) -> bool:
        """Prefer the data-plane current descriptor, with a bootstrap fallback."""
        host = getattr(self._plugin_admission_v2, "host", None)
        manager = getattr(host, "manager", None)
        current_generation = getattr(manager, "current", None)
        published_descriptor = getattr(current_generation, "descriptor", None)
        if published_descriptor is not None:
            return bool(descriptor == published_descriptor)

        current = self._agent_generation_descriptor_v2
        return (
            current is None or descriptor == current or descriptor.generation > current.generation
        )

    def _take_retired_agent_runtimes_v2_locked(self) -> tuple[_AgentRuntimeEntryV2, ...]:
        """Detach inactive runtimes that no longer represent the current generation."""
        current = self._agent_generation_descriptor_v2
        retired = tuple(
            entry
            for descriptor, entry in self._agent_runtime_entries_v2.items()
            if descriptor != current and entry.active_leases == 0
        )
        for entry in retired:
            self._agent_runtime_entries_v2.pop(entry.descriptor, None)
        return retired

    @staticmethod
    async def _dispose_agent_runtimes_v2(
        entries: tuple[_AgentRuntimeEntryV2, ...],
    ) -> None:
        """Stop retired runtimes without invalidating another generation's cache."""
        for entry in entries:
            await entry.agent.stop(
                generation_descriptor=entry.descriptor,
                notify_lifecycle=False,
            )

    @asynccontextmanager
    async def _lease_agent_runtime_v2(
        self,
        operation: OperationContextV2,
        *,
        preferred_agent: ProjectReActAgent | None = None,
    ) -> AsyncIterator[ProjectReActAgent]:
        """Keep one generation-owned runtime immutable for an operation."""
        async with self._init_lock:
            entry = await self._ensure_agent_runtime_entry_v2_locked(
                operation,
                preferred_agent=preferred_agent,
            )
            entry.active_leases += 1
            retired = self._take_retired_agent_runtimes_v2_locked()
            await self._dispose_agent_runtimes_v2(retired)

        try:
            yield entry.agent
        finally:
            async with self._init_lock:
                entry.active_leases -= 1
                retired = self._take_retired_agent_runtimes_v2_locked()
                await self._dispose_agent_runtimes_v2(retired)

    async def chat(self, request: ProjectChatRequest) -> dict[str, Any]:
        """Start a chat execution in the background."""
        async with self._lifecycle_lock:
            self._require_task_registration_open()
            if not self._agent:
                if not self._config:
                    raise RuntimeError("Actor config not set")
                await self._initialize_locked(self._config)

            abort_signal = asyncio.Event()
            task = asyncio.create_task(self._run_chat(request, abort_signal))
            self._tasks[request.message_id] = task
            self._task_conversations[request.message_id] = request.conversation_id
            self._abort_signals[request.message_id] = abort_signal

            # Add cleanup callback
            task.add_done_callback(lambda _task: self._cleanup_task(request.message_id))

            return {"status": "started", "message_id": request.message_id}

    async def continue_chat(
        self,
        request_id: str,
        response_data: dict[str, Any],
        conversation_id: str | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        """Continue a paused chat after HITL response."""
        async with self._lifecycle_lock:
            self._require_task_registration_open()
            if not self._agent:
                if not self._config:
                    raise RuntimeError("Actor config not set")
                await self._initialize_locked(self._config)

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
        async with self._lifecycle_lock:
            if self._shutdown_task is None:
                self._shutting_down = True
                tasks = tuple(self._tasks.values())
                abort_signals = tuple(self._abort_signals.values())
                self._shutdown_task = asyncio.create_task(
                    self._shutdown_registered_tasks(tasks, abort_signals),
                    name="project-agent-actor-shutdown",
                )
            shutdown_task = self._shutdown_task
        await asyncio.shield(shutdown_task)
        return True

    async def _shutdown_registered_tasks(
        self,
        tasks: tuple[asyncio.Task[Any], ...],
        abort_signals: tuple[asyncio.Event, ...],
    ) -> None:
        """Cancel the closed registration snapshot and then dispose actor resources."""
        for abort_signal in abort_signals:
            abort_signal.set()
        for task in tasks:
            if not task.done():
                _ = task.cancel()
        if tasks:
            _ = await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._task_conversations.clear()
        self._abort_signals.clear()

        runtime_agents = {
            id(entry.agent): entry.agent for entry in self._agent_runtime_entries_v2.values()
        }
        if self._agent is not None:
            runtime_agents[id(self._agent)] = self._agent
        for runtime_agent in runtime_agents.values():
            await runtime_agent.stop()
        self._agent_runtime_entries_v2.clear()
        self._agent = None
        self._agent_generation_descriptor_v2 = None
        await self._plugin_admission_v2.close()

    def _admit_plugin_turn(
        self,
        request: ProjectChatRequest,
    ) -> AbstractAsyncContextManager[OperationContextV2]:
        """Build the exact generation admission context for one actor turn."""
        from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

        if self._config is None:
            raise RuntimeV2Error(
                "operation_scope_unavailable",
                "actor configuration is required to scope a plugin turn",
            )
        scope = ScopeV2(
            kind=ScopeKindV2.SESSION,
            tenant_id=self._config.tenant_id,
            project_id=self._config.project_id,
            session_id=request.conversation_id,
        )
        services = {
            OPERATION_IDENTITY_SERVICE_V2: {
                "tenant_id": self._config.tenant_id,
                "project_id": self._config.project_id,
                "user_id": request.user_id,
            },
            OPERATION_METADATA_SERVICE_V2: {
                "kind": "ray-agent-turn",
                "conversation_id": request.conversation_id,
                "message_id": request.message_id,
            },
        }
        return self._plugin_admission_v2.admit(
            descriptor_payload=request.plugin_generation,
            distribution_payload=request.plugin_distribution,
            operation_id=f"ray-turn:{request.message_id}",
            scope=scope,
            services=services,
        )

    async def _run_chat(
        self,
        request: ProjectChatRequest,
        abort_signal: asyncio.Event | None = None,
    ) -> None:
        lock = self._conversation_locks.setdefault(request.conversation_id, asyncio.Lock())
        async with lock:
            self._current_conversation_id = request.conversation_id
            self._current_message_id = request.message_id

            try:
                if not self._agent:
                    return

                async with self._admit_plugin_turn(request) as operation:
                    from src.application.services.wasm_operation_authority_v2 import (
                        prepare_agent_wasm_tools_v2,
                    )

                    await prepare_agent_wasm_tools_v2(operation)
                    await self._ensure_agent_orchestrator_v2()
                    async with self._lease_agent_runtime_v2(operation) as agent:
                        distribution = self._plugin_admission_v2.host.distribution_for_generation(
                            operation.generation
                        )
                        result = await execute_project_chat(
                            agent,
                            replace(
                                request,
                                plugin_distribution=distribution.to_payload(),
                            ),
                            abort_signal=abort_signal,
                        )
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
            finally:
                if self._current_message_id == request.message_id:
                    self._current_conversation_id = None
                    self._current_message_id = None

    async def _run_continue(
        self,
        request_id: str,
        response_data: dict[str, Any],
        conversation_id: str | None,
        message_id: str | None,
    ) -> dict[str, Any]:
        if not self._agent:
            return {"status": "unavailable", "request_id": request_id, "ack": False}
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
                from src.infrastructure.agent.actor.execution import (
                    load_hitl_state_for_resume,
                )

                state = await load_hitl_state_for_resume(
                    request_id,
                    generation_host=self._plugin_admission_v2.host,
                )
                if state is None:
                    raise RuntimeV2Error(
                        "generation_descriptor_missing",
                        "persisted HITL state does not identify the plugin generation to resume",
                    )

                from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

                async with self._plugin_admission_v2.admit(
                    descriptor_payload=state.plugin_generation,
                    distribution_payload=state.plugin_distribution,
                    operation_id=f"hitl-resume:{request_id}",
                    scope=ScopeV2(
                        kind=ScopeKindV2.SESSION,
                        tenant_id=state.tenant_id,
                        project_id=state.project_id,
                        session_id=state.conversation_id,
                    ),
                    services={
                        OPERATION_IDENTITY_SERVICE_V2: {
                            "tenant_id": state.tenant_id,
                            "project_id": state.project_id,
                            "user_id": state.user_id,
                        },
                        OPERATION_METADATA_SERVICE_V2: {
                            "kind": "hitl-resume",
                            "request_id": request_id,
                            "message_id": state.message_id,
                        },
                    },
                ) as operation:
                    from src.application.services.wasm_operation_authority_v2 import (
                        prepare_agent_wasm_tools_v2,
                    )

                    await prepare_agent_wasm_tools_v2(operation)
                    await self._ensure_agent_orchestrator_v2()
                    async with self._lease_agent_runtime_v2(
                        operation,
                        preferred_agent=agent,
                    ) as resume_agent:
                        result = await continue_project_chat(
                            resume_agent,
                            request_id,
                            response_data,
                            lease_owner=self._lease_owner(),
                            tenant_id=state.tenant_id,
                            project_id=state.project_id,
                            conversation_id=state.conversation_id,
                            message_id=state.message_id,
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

    async def _ensure_agent_orchestrator_v2(self) -> None:
        """Build the actor orchestrator from the exact admitted V2 registry."""
        from src.infrastructure.plugins.v2.agent_worker_runtime import (
            bind_current_agent_orchestrator_v2,
        )

        try:
            async with self._bootstrap_lock:
                from src.application.services.agent.runtime_bootstrapper import (
                    AgentRuntimeBootstrapper,
                )
                from src.infrastructure.agent.orchestration.orchestrator import (
                    SessionTurnExecutionRequest,
                    SpawnExecutionRequest,
                )
                from src.infrastructure.plugins.v2.boundary import (
                    OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2,
                    current_operation_context_v2,
                )

                def _pinned_distribution() -> tuple[
                    dict[str, str | int],
                    dict[str, Any],
                ]:
                    operation = current_operation_context_v2()
                    descriptor = operation.descriptor.to_payload()
                    value = operation.require(OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2)
                    if not isinstance(value, dict):
                        raise RuntimeV2Error(
                            "invalid_plugin_distribution",
                            "plugin operation distribution must be an object",
                        )
                    distribution = dict(value)
                    if distribution.get("descriptor") != descriptor:
                        raise RuntimeV2Error(
                            "plugin_distribution_mismatch",
                            "plugin operation distribution does not match the pinned generation",
                        )
                    return descriptor, distribution

                async def _spawn_executor(request: SpawnExecutionRequest) -> None:
                    from src.application.services.peer_chat_permission_v2 import (
                        resolve_peer_execution_v2,
                    )

                    generation, distribution = _pinned_distribution()
                    admission = await resolve_peer_execution_v2(request, spawn=True)
                    if not admission.created:
                        return
                    conversation = admission.conversation
                    tenant_agent_config = await AgentRuntimeBootstrapper._load_tenant_agent_config(
                        conversation.tenant_id
                    )
                    await self.chat(
                        ProjectChatRequest(
                            conversation_id=conversation.id,
                            message_id=admission.run_id,
                            canonical_run_id=admission.run_id,
                            user_message=request.message,
                            user_id=conversation.user_id,
                            conversation_context=[],
                            plan_mode=conversation.is_in_plan_mode,
                            agent_id=request.child_agent_id,
                            tenant_agent_config=tenant_agent_config.to_dict(),
                            parent_session_id=request.parent_session_id,
                            plugin_generation=generation,
                            plugin_distribution=distribution,
                        )
                    )

                async def _session_turn_executor(
                    request: SessionTurnExecutionRequest,
                ) -> None:
                    from src.application.services.peer_chat_permission_v2 import (
                        resolve_peer_execution_v2,
                    )

                    generation, distribution = _pinned_distribution()
                    admission = await resolve_peer_execution_v2(request, spawn=False)
                    if not admission.created:
                        return
                    conversation = admission.conversation
                    tenant_agent_config = await AgentRuntimeBootstrapper._load_tenant_agent_config(
                        conversation.tenant_id
                    )
                    await self.chat(
                        ProjectChatRequest(
                            conversation_id=conversation.id,
                            message_id=admission.run_id,
                            canonical_run_id=admission.run_id,
                            user_message=request.message,
                            user_id=conversation.user_id,
                            conversation_context=[],
                            plan_mode=conversation.is_in_plan_mode,
                            agent_id=request.child_agent_id,
                            tenant_agent_config=tenant_agent_config.to_dict(),
                            parent_session_id=conversation.parent_conversation_id,
                            plugin_generation=generation,
                            plugin_distribution=distribution,
                        )
                    )

                orchestrator = await bind_current_agent_orchestrator_v2(
                    owner=self,
                    spawn_executor=_spawn_executor,
                    session_turn_executor=_session_turn_executor,
                )
                self._agent_orchestrator_v2 = orchestrator
                logger.info(
                    "[ProjectAgentActor] AgentOrchestrator bootstrapped for multi-agent tools"
                )
        except RuntimeV2Error:
            raise
        except Exception as e:
            logger.warning(
                "[ProjectAgentActor] AgentOrchestrator init failed "
                "(multi-agent tools disabled): %s",
                e,
            )

    async def _create_graph_runtime_v2(self) -> GraphStorePort:
        """Create this actor tenant's graph resource for one candidate generation."""
        if self._config is None:
            raise RuntimeV2Error(
                "agent_actor_config_unavailable",
                "actor configuration is required before graph runtime activation",
            )
        factory = agent_worker_graph_runtime_factory_v2(self._config.tenant_id)
        return await factory()

    async def _bootstrap_runtime(self) -> None:
        if self._bootstrapped:
            return

        async with self._bootstrap_lock:
            if self._bootstrapped:
                return  # type: ignore[unreachable]

            try:
                await initialize_default_llm_providers()
            except Exception as e:
                logger.warning(f"[ProjectAgentActor] LLM provider init failed: {e}")

            self._bootstrapped = True
