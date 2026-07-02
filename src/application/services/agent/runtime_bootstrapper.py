"""Agent runtime bootstrapping extracted from AgentService."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from subprocess import DEVNULL
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy.exc import SQLAlchemyError

from src.configuration.config import Settings
from src.domain.model.agent import Conversation
from src.domain.model.agent.conversation.agent_config import selected_agent_id_from_config
from src.domain.model.agent.tenant_agent_config import TenantAgentConfig
from src.infrastructure.agent.sisyphus.builtin_agent import DEFAULT_GENERAL_AGENT_ID

if TYPE_CHECKING:
    from src.infrastructure.agent.actor.types import ProjectAgentActorConfig, ProjectChatRequest
    from src.infrastructure.agent.orchestration.orchestrator import (
        SessionTurnExecutionRequest,
        SpawnExecutionRequest,
    )

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[Any]] = set()
_LOCAL_SUBPROCESS_REQUEST_DIR = "MEMSTACK_LOCAL_AGENT_REQUEST_DIR"
_LOCAL_CHAT_WORKER_MODULE = "src.infrastructure.agent.actor.local_chat_worker"
_WORKSPACE_RUNTIME_CONTEXT_TYPE = "workspace_worker_runtime"
_WORKSPACE_CONTRACT_STAGES = frozenset(
    {
        "planner",
        "verification_judge",
        "iteration_review",
    }
)
_WORKSPACE_WORKER_STAGES = frozenset({"worker_launch"})


@dataclass(frozen=True)
class _LocalChatWorkItem:
    config: ProjectAgentActorConfig
    request: ProjectChatRequest
    run_in_subprocess: bool = False


def _safe_request_file_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)


def _non_empty_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _conversation_metadata(conversation: Conversation) -> dict[str, Any]:
    metadata = getattr(conversation, "metadata", None)
    return dict(metadata) if isinstance(metadata, dict) else {}


def _selected_agent_id_from_conversation(conversation: Conversation) -> str | None:
    agent_config = getattr(conversation, "agent_config", None)
    return selected_agent_id_from_config(agent_config if isinstance(agent_config, dict) else None)


def _workspace_session_role_from_metadata(metadata: dict[str, Any]) -> str:
    from src.infrastructure.agent.workspace.runtime_role_contract import (
        WORKSPACE_ROLE_CONTRACT,
        WORKSPACE_ROLE_LEADER,
        WORKSPACE_ROLE_WORKER,
    )

    explicit_role = _non_empty_string(metadata.get("workspace_session_role"))
    if explicit_role:
        return explicit_role
    stage = _non_empty_string(metadata.get("workspace_llm_stage"))
    if stage in _WORKSPACE_CONTRACT_STAGES:
        return WORKSPACE_ROLE_CONTRACT
    if stage in _WORKSPACE_WORKER_STAGES:
        return WORKSPACE_ROLE_WORKER
    return (
        WORKSPACE_ROLE_WORKER if metadata.get("linked_workspace_task_id") else WORKSPACE_ROLE_LEADER
    )


def _workspace_context_from_conversation(
    conversation: Conversation,
) -> dict[str, Any] | None:
    """Rebuild server-owned workspace runtime context from a persisted session."""
    from src.infrastructure.agent.workspace.runtime_role_contract import (
        WORKSPACE_SESSION_ROLE_KEY,
    )
    from src.infrastructure.agent.workspace.workspace_metadata_keys import PREFERRED_LANGUAGE

    metadata = _conversation_metadata(conversation)
    workspace_id = _non_empty_string(getattr(conversation, "workspace_id", None)) or (
        _non_empty_string(metadata.get("workspace_id"))
    )
    if workspace_id is None:
        return None

    linked_task_id = _non_empty_string(
        getattr(conversation, "linked_workspace_task_id", None)
    ) or _non_empty_string(metadata.get("linked_workspace_task_id"))
    root_goal_task_id = _non_empty_string(metadata.get("root_goal_task_id"))
    attempt_id = _non_empty_string(metadata.get("attempt_id")) or _non_empty_string(
        metadata.get("current_attempt_id")
    )

    binding: dict[str, Any] = {"workspace_id": workspace_id}
    if root_goal_task_id:
        binding["root_goal_task_id"] = root_goal_task_id
    if linked_task_id:
        binding["workspace_task_id"] = linked_task_id
        binding["linked_workspace_task_id"] = linked_task_id
    if attempt_id:
        binding["attempt_id"] = attempt_id
        binding["current_attempt_id"] = attempt_id
    current_plan_node_id = _non_empty_string(metadata.get("current_plan_node_id"))
    if current_plan_node_id:
        binding["current_plan_node_id"] = current_plan_node_id
    leader_agent_id = _non_empty_string(metadata.get("leader_agent_id"))
    if leader_agent_id:
        binding["leader_agent_id"] = leader_agent_id

    context: dict[str, Any] = {
        "context_type": _WORKSPACE_RUNTIME_CONTEXT_TYPE,
        WORKSPACE_SESSION_ROLE_KEY: _workspace_session_role_from_metadata(metadata),
        "workspace_binding": binding,
    }
    preferred_language = _non_empty_string(metadata.get(PREFERRED_LANGUAGE))
    if preferred_language:
        context[PREFERRED_LANGUAGE] = preferred_language
    return context


def _merge_workspace_context_from_conversation(
    conversation: Conversation,
    app_model_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Preserve explicit request context, else restore workspace context from the session."""
    if isinstance(app_model_context, dict):
        if app_model_context.get("context_type") == _WORKSPACE_RUNTIME_CONTEXT_TYPE:
            return dict(app_model_context)
        base_context = dict(app_model_context)
    else:
        base_context = {}

    workspace_context = _workspace_context_from_conversation(conversation)
    if workspace_context is None:
        return base_context or None
    return {**base_context, **workspace_context}


class AgentRuntimeBootstrapper:
    """Handles Ray/Local runtime initialization for agent execution."""

    _local_bootstrapped: ClassVar[bool] = False
    _local_bootstrap_lock = asyncio.Lock()
    _local_chat_lock = asyncio.Lock()
    _local_chat_tasks: ClassVar[dict[str, asyncio.Task[Any]]] = {}
    _local_chat_abort_signals: ClassVar[dict[str, asyncio.Event]] = {}
    _local_chat_queues: ClassVar[dict[str, asyncio.Queue[_LocalChatWorkItem]]] = {}
    _local_chat_queue_tasks: ClassVar[dict[str, asyncio.Task[Any]]] = {}
    _local_subprocesses: ClassVar[dict[str, asyncio.subprocess.Process]] = {}
    _local_subprocess_request_paths: ClassVar[dict[str, Path]] = {}
    _local_subprocess_superseded: ClassVar[set[tuple[str, int | None]]] = set()

    @staticmethod
    def _normalize_runtime_mode(mode: str | None) -> str:
        """Normalize runtime mode value."""
        normalized = (mode or "auto").strip().lower()
        if normalized in {"auto", "ray", "local"}:
            return normalized
        return "auto"

    @staticmethod
    async def _load_tenant_agent_config(tenant_id: str) -> TenantAgentConfig:
        """Load tenant agent config for request-scoped runtime policy."""
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_tenant_agent_config_repository import (
            SqlTenantAgentConfigRepository,
        )

        session = async_session_factory()
        try:
            repo = SqlTenantAgentConfigRepository(session)
            try:
                config = await repo.get_by_tenant(tenant_id)
            except (RuntimeError, SQLAlchemyError) as exc:
                logger.warning(
                    "Failed to load tenant agent config for tenant %s; using defaults instead: %s",
                    tenant_id,
                    exc,
                )
                return TenantAgentConfig.create_default(tenant_id=tenant_id)
            return config or TenantAgentConfig.create_default(tenant_id=tenant_id)
        finally:
            try:
                await session.close()
            except (RuntimeError, SQLAlchemyError) as exc:
                logger.warning(
                    "Failed to close tenant agent config session for tenant %s: %s",
                    tenant_id,
                    exc,
                )

    @staticmethod
    async def ensure_spawned_agent_conversation(
        *,
        child_session_id: str,
        parent_session_id: str,
        project_id: str,
        tenant_id: str,
        user_id: str,
        parent_agent_id: str,
        child_agent_id: str,
        child_agent_name: str,
        mode: str,
        metadata: dict[str, Any] | None = None,
    ) -> Conversation:
        """Create or load the persisted conversation backing a spawned child session."""
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
            SqlConversationRepository,
        )

        session = async_session_factory()
        try:
            repo = SqlConversationRepository(session)
            existing = await repo.find_by_id(child_session_id)
            if existing is not None:
                return existing

            parent = await repo.find_by_id(parent_session_id)
            resolved_project_id = (project_id or (parent.project_id if parent else "")).strip()
            resolved_tenant_id = (tenant_id or (parent.tenant_id if parent else "")).strip()
            resolved_user_id = (user_id or (parent.user_id if parent else "")).strip()
            if not resolved_project_id:
                raise ValueError("Spawned agent session requires a project_id")
            if not resolved_tenant_id:
                raise ValueError("Spawned agent session requires a tenant_id")
            if not resolved_user_id:
                raise ValueError("Spawned agent session requires a user_id")

            conversation_metadata = dict(metadata) if isinstance(metadata, dict) else {}
            conversation_metadata.update(
                {
                    "spawned_by_agent_id": parent_agent_id,
                    "spawned_agent_id": child_agent_id,
                    "spawn_mode": mode,
                }
            )

            conversation = Conversation(
                id=child_session_id,
                project_id=resolved_project_id,
                tenant_id=resolved_tenant_id,
                user_id=resolved_user_id,
                title=f"{child_agent_name or child_agent_id} session",
                agent_config={"selected_agent_id": child_agent_id},
                metadata=conversation_metadata,
                parent_conversation_id=parent_session_id,
            )
            await repo.save_and_commit(conversation)
            return conversation
        finally:
            await session.close()

    async def launch_spawned_agent_session(
        self,
        request: SpawnExecutionRequest,
    ) -> None:
        """Persist and start a child session created via agent_spawn."""
        conversation = await self.ensure_spawned_agent_conversation(
            child_session_id=request.child_session_id,
            parent_session_id=request.parent_session_id,
            project_id=request.project_id,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            parent_agent_id=request.parent_agent_id,
            child_agent_id=request.child_agent_id,
            child_agent_name=request.child_agent_name,
            mode=request.mode.value,
            metadata=request.metadata,
        )
        await self.start_chat_actor(
            conversation=conversation,
            message_id=str(uuid.uuid4()),
            user_message=request.message,
            conversation_context=[],
            agent_id=request.child_agent_id,
            parent_session_id=request.parent_session_id,
        )

    @staticmethod
    async def load_spawned_agent_conversation(
        *,
        child_session_id: str,
        project_id: str,
        tenant_id: str,
    ) -> Conversation:
        """Load and validate the persisted conversation for a spawned child session."""
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
            SqlConversationRepository,
        )

        session = async_session_factory()
        try:
            repo = SqlConversationRepository(session)
            conversation = await repo.find_by_id(child_session_id)
            if conversation is None:
                raise ValueError(f"Spawned agent conversation not found: {child_session_id}")
            if project_id and conversation.project_id != project_id:
                raise ValueError(f"Spawned agent conversation not found: {child_session_id}")
            if tenant_id and conversation.tenant_id != tenant_id:
                raise ValueError(f"Spawned agent conversation not found: {child_session_id}")
            if not conversation.parent_conversation_id:
                raise ValueError(f"Spawned agent conversation has no parent: {child_session_id}")
            return conversation
        finally:
            await session.close()

    async def launch_agent_session_turn(
        self,
        request: SessionTurnExecutionRequest,
    ) -> None:
        """Start one follow-up turn for a persistent session spawned via agent_spawn."""
        conversation = await self.load_spawned_agent_conversation(
            child_session_id=request.child_session_id,
            project_id=request.project_id,
            tenant_id=request.tenant_id,
        )
        await self.start_chat_actor(
            conversation=conversation,
            message_id=str(uuid.uuid4()),
            user_message=request.message,
            conversation_context=[],
            agent_id=request.child_agent_id,
            parent_session_id=conversation.parent_conversation_id,
        )

    async def start_chat_actor(  # noqa: PLR0913, PLR0915
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
        image_attachments: list[str] | None = None,
        agent_id: str | None = None,
        model_override: str | None = None,
        parent_session_id: str | None = None,
        preferred_language: str | None = None,
        api_auth_token: str | None = None,
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
        resolved_app_model_context = _merge_workspace_context_from_conversation(
            conversation,
            app_model_context,
        )
        resolved_agent_id = (
            agent_id
            or _selected_agent_id_from_conversation(conversation)
            or DEFAULT_GENERAL_AGENT_ID
        )
        runtime_mode = self._resolve_runtime_mode(
            configured_mode=settings.agent_runtime_mode,
            app_model_context=resolved_app_model_context,
            conversation_id=conversation.id,
        )
        tenant_agent_config = await self._load_tenant_agent_config(conversation.tenant_id)

        # Resolve provider config from DB
        factory = get_ai_service_factory()
        provider_config = await factory.resolve_provider(conversation.tenant_id)

        # Decrypt API key for the actor
        encryption_service = get_encryption_service()
        api_key = encryption_service.decrypt(provider_config.api_key_encrypted)

        configured_model = tenant_agent_config.llm_model.strip()
        base_model = (
            configured_model
            if configured_model and configured_model.lower() != "default"
            else provider_config.llm_model
        )

        config = ProjectAgentActorConfig(
            tenant_id=conversation.tenant_id,
            project_id=conversation.project_id,
            agent_mode=agent_mode,
            model=model_override or base_model,
            api_key=api_key,
            base_url=provider_config.base_url,
            temperature=tenant_agent_config.llm_temperature,
            max_tokens=settings.agent_max_tokens,
            max_steps=tenant_agent_config.max_work_plan_steps,
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
            app_model_context=resolved_app_model_context,
            image_attachments=image_attachments,
            agent_id=resolved_agent_id,
            tenant_agent_config=tenant_agent_config.to_dict(),
            parent_session_id=parent_session_id,
            preferred_language=preferred_language
            if preferred_language in {"en-US", "zh-CN"}
            else None,
            api_auth_token=api_auth_token,
        )

        if runtime_mode == "local":
            await self._register_project_local(conversation.tenant_id, conversation.project_id)
            if self._is_workspace_worker_runtime(resolved_app_model_context):
                await self._start_local_subprocess_chat(conversation.id, config, chat_request)
                logger.info(
                    "[AgentService] Using local subprocess execution "
                    "(AGENT_RUNTIME_MODE=local workspace worker) for conversation %s",
                    conversation.id,
                )
            else:
                await self._start_local_chat(conversation.id, config, chat_request)
                logger.info(
                    "[AgentService] Using local execution (AGENT_RUNTIME_MODE=local) "
                    "for conversation %s",
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

    @classmethod
    def _resolve_runtime_mode(
        cls,
        *,
        configured_mode: str | None,
        app_model_context: dict[str, Any] | None,
        conversation_id: str,
    ) -> str:
        """Resolve the runtime mode for this request."""
        runtime_mode = cls._normalize_runtime_mode(configured_mode)
        if cls._is_workspace_worker_runtime(app_model_context) and runtime_mode == "auto":
            logger.warning(
                "[AgentService] Forcing Ray runtime for workspace worker conversation %s "
                "(configured AGENT_RUNTIME_MODE=%s)",
                conversation_id,
                runtime_mode,
            )
            return "ray"
        if cls._is_workspace_worker_runtime(app_model_context) and runtime_mode == "local":
            logger.warning(
                "[AgentService] Workspace worker conversation %s is using local runtime because "
                "AGENT_RUNTIME_MODE=local is explicit; dev reload can interrupt long-running turns.",
                conversation_id,
            )
        return runtime_mode

    @staticmethod
    def _is_workspace_worker_runtime(app_model_context: dict[str, Any] | None) -> bool:
        """Return True for long-running workspace worker turns.

        Workspace workers should run out-of-process. Running them in the API
        reload process lets dev reload/SIGTERM interrupt LLM execution and
        turns infrastructure shutdown into false task blockers.
        """
        return (
            isinstance(app_model_context, dict)
            and app_model_context.get("context_type") == "workspace_worker_runtime"
        )

    @staticmethod
    async def _register_project_local(tenant_id: str, project_id: str) -> None:
        """Register project with local HITL resume consumer."""
        from src.infrastructure.agent.hitl.local_resume_consumer import register_project_local

        await register_project_local(tenant_id, project_id)

    async def _start_local_chat(
        self, conversation_id: str, config: ProjectAgentActorConfig, request: ProjectChatRequest
    ) -> None:
        """Queue local execution for this conversation."""
        await self._enqueue_local_chat_work(
            conversation_id,
            _LocalChatWorkItem(config=config, request=request),
        )

    async def _start_local_subprocess_chat(
        self,
        conversation_id: str,
        config: ProjectAgentActorConfig,
        request: ProjectChatRequest,
    ) -> None:
        """Queue workspace local execution in a child process.

        Workspace worker turns can outlive a dev-server reload. Running them
        in the uvicorn process turns reload SIGTERM into false task blockers,
        so local mode uses a short-lived child process for those turns.
        """
        await self._enqueue_local_chat_work(
            conversation_id,
            _LocalChatWorkItem(
                config=config,
                request=request,
                run_in_subprocess=True,
            ),
        )

    async def _enqueue_local_chat_work(
        self,
        conversation_id: str,
        item: _LocalChatWorkItem,
    ) -> None:
        """Append a local turn to the per-conversation FIFO worker."""
        async with self._local_chat_lock:
            queue = self._local_chat_queues.get(conversation_id)
            if queue is None:
                queue = asyncio.Queue[_LocalChatWorkItem]()
                self._local_chat_queues[conversation_id] = queue
            queue.put_nowait(item)

            worker = self._local_chat_queue_tasks.get(conversation_id)
            if worker is None or worker.done():
                worker = asyncio.create_task(
                    self._run_local_chat_queue(conversation_id),
                    name=f"local-agent-chat-queue:{conversation_id}",
                )
                self._local_chat_queue_tasks[conversation_id] = worker
                self._local_chat_tasks[conversation_id] = worker
                worker.add_done_callback(
                    lambda done_task: self._schedule_local_chat_cleanup(
                        conversation_id,
                        done_task,
                    )
                )

    async def _run_local_chat_queue(self, conversation_id: str) -> None:
        """Run queued local turns sequentially for one conversation."""
        while True:
            async with self._local_chat_lock:
                queue = self._local_chat_queues.get(conversation_id)
                if queue is None or queue.empty():
                    _ = self._local_chat_queues.pop(conversation_id, None)
                    _ = self._local_chat_queue_tasks.pop(conversation_id, None)
                    current_task = asyncio.current_task()
                    if (
                        current_task is not None
                        and self._local_chat_tasks.get(conversation_id) is current_task
                    ):
                        _ = self._local_chat_tasks.pop(conversation_id, None)
                    _ = self._local_chat_abort_signals.pop(conversation_id, None)
                    return

                item = queue.get_nowait()
                abort_signal = asyncio.Event()
                self._local_chat_abort_signals[conversation_id] = abort_signal

            try:
                if item.run_in_subprocess:
                    await self._run_local_subprocess_chat_once(
                        conversation_id,
                        item.config,
                        item.request,
                    )
                else:
                    await self._run_chat_local(
                        item.config,
                        item.request,
                        abort_signal=abort_signal,
                    )
            finally:
                queue.task_done()
                async with self._local_chat_lock:
                    if self._local_chat_abort_signals.get(conversation_id) is abort_signal:
                        _ = self._local_chat_abort_signals.pop(conversation_id, None)

    async def _run_local_subprocess_chat_once(
        self,
        conversation_id: str,
        config: ProjectAgentActorConfig,
        request: ProjectChatRequest,
    ) -> None:
        """Start and monitor one local subprocess turn."""
        async with self._local_chat_lock:
            request_path = self._write_local_subprocess_request(config, request)
            try:
                env = os.environ.copy()
                _ = env.setdefault("MEMSTACK_POSTGRES_POOL_MODE", "null")
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    _LOCAL_CHAT_WORKER_MODULE,
                    str(request_path),
                    cwd=str(Path.cwd()),
                    stdout=DEVNULL,
                    stderr=None,
                    env=env,
                    start_new_session=True,
                )
            except Exception:
                request_path.unlink(missing_ok=True)
                raise
            self._local_subprocesses[conversation_id] = process
            self._local_subprocess_request_paths[conversation_id] = request_path

        await self._monitor_local_subprocess_chat(
            conversation_id=conversation_id,
            message_id=request.message_id,
            correlation_id=request.correlation_id,
            process=process,
            request_path=request_path,
        )

    @classmethod
    async def has_running_local_subprocess(cls, conversation_id: str) -> bool:
        """Return True when this API process still owns a live local worker."""
        async with cls._local_chat_lock:
            process = cls._local_subprocesses.get(conversation_id)
            if process is not None and getattr(process, "returncode", None) is None:
                pid = getattr(process, "pid", None)
                if isinstance(pid, int) and pid > 0:
                    if await asyncio.to_thread(cls._local_subprocess_pid_is_running, pid):
                        return True
                    cls._local_subprocesses.pop(conversation_id, None)
                    request_path = cls._local_subprocess_request_paths.pop(conversation_id, None)
                    if request_path is not None:
                        with contextlib.suppress(OSError):
                            request_path.unlink()
                else:
                    return True
        return False

    @staticmethod
    def _local_subprocess_pid_is_running(pid: int) -> bool:
        """Check the OS process table for a tracked detached worker PID."""
        try:
            result = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(pid)],
                check=False,
                capture_output=True,
                text=True,
                timeout=2.0,
            )
        except Exception:
            return True
        if result.returncode != 0:
            return False
        status = result.stdout.strip()
        return bool(status) and not status.startswith("Z")

    @staticmethod
    def _find_orphan_local_subprocess_pids(conversation_id: str) -> list[int]:
        """Find detached local worker processes lost from in-memory tracking."""
        safe_conversation_id = _safe_request_file_name(conversation_id)
        if not safe_conversation_id:
            return []
        request_name_marker = f"{safe_conversation_id}-"
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid=,command="],
                check=False,
                capture_output=True,
                text=True,
                timeout=2.0,
            )
        except Exception:
            logger.debug(
                "[AgentService] Failed to scan local subprocess table",
                exc_info=True,
            )
            return []
        if result.returncode != 0:
            return []
        current_pid = os.getpid()
        pids: list[int] = []
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            pid_text, _separator, command = stripped.partition(" ")
            try:
                pid = int(pid_text)
            except ValueError:
                continue
            if pid == current_pid:
                continue
            if _LOCAL_CHAT_WORKER_MODULE not in command:
                continue
            if request_name_marker not in command:
                continue
            pids.append(pid)
        return pids

    @staticmethod
    def _signal_process_group(pid: int, sig: int) -> None:
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            logger.warning(
                "[AgentService] Permission denied signalling local subprocess: pid=%s signal=%s",
                pid,
                sig,
            )
        except OSError:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, sig)

    @staticmethod
    def _remove_local_subprocess_request_files(conversation_id: str) -> None:
        safe_conversation_id = _safe_request_file_name(conversation_id)
        if not safe_conversation_id:
            return
        request_dir = Path(os.getenv(_LOCAL_SUBPROCESS_REQUEST_DIR, "/tmp/memstack-agent-requests"))
        if not request_dir.exists():
            return
        for request_path in request_dir.glob(f"{safe_conversation_id}-*.json"):
            with contextlib.suppress(OSError):
                request_path.unlink()

    @classmethod
    async def _terminate_orphaned_local_subprocesses_locked(
        cls,
        conversation_id: str,
        *,
        reason: str,
    ) -> bool:
        pids = await asyncio.to_thread(cls._find_orphan_local_subprocess_pids, conversation_id)
        if not pids:
            await asyncio.to_thread(cls._remove_local_subprocess_request_files, conversation_id)
            return False
        logger.warning(
            "[AgentService] Terminating orphaned local subprocesses: conversation=%s pids=%s reason=%s",
            conversation_id,
            pids,
            reason,
        )
        for pid in pids:
            await asyncio.to_thread(cls._signal_process_group, pid, signal.SIGTERM)
        await asyncio.sleep(0.5)
        remaining = await asyncio.to_thread(cls._find_orphan_local_subprocess_pids, conversation_id)
        if remaining:
            logger.warning(
                "[AgentService] Killing unresponsive orphaned local subprocesses: "
                "conversation=%s pids=%s",
                conversation_id,
                remaining,
            )
            for pid in remaining:
                await asyncio.to_thread(cls._signal_process_group, pid, signal.SIGKILL)
        await asyncio.to_thread(cls._remove_local_subprocess_request_files, conversation_id)
        return True

    @staticmethod
    def _write_local_subprocess_request(
        config: ProjectAgentActorConfig,
        request: ProjectChatRequest,
    ) -> Path:
        request_dir = Path(os.getenv(_LOCAL_SUBPROCESS_REQUEST_DIR, "/tmp/memstack-agent-requests"))
        request_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        file_name = _safe_request_file_name(f"{request.conversation_id}-{request.message_id}.json")
        request_path = request_dir / file_name
        payload = {
            "config": asdict(config),
            "request": asdict(request),
        }
        fd = os.open(request_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False)
        return request_path

    @classmethod
    async def _terminate_local_subprocess_locked(
        cls,
        conversation_id: str,
        *,
        reason: str,
    ) -> bool:
        """Terminate the tracked detached worker for a conversation.

        The caller must hold ``_local_chat_lock``. Detached workspace workers are
        keyed by conversation, so stale recovery can safely relaunch a worker only
        after the previous process has been asked to stop.
        """
        process = cls._local_subprocesses.pop(conversation_id, None)
        request_path = cls._local_subprocess_request_paths.pop(conversation_id, None)
        if process is None:
            if request_path is not None:
                request_path.unlink(missing_ok=True)
            return await cls._terminate_orphaned_local_subprocesses_locked(
                conversation_id,
                reason=reason,
            )

        pid = getattr(process, "pid", None)
        returncode = getattr(process, "returncode", None)
        if returncode is None:
            cls._local_subprocess_superseded.add((conversation_id, pid))
            logger.warning(
                "[AgentService] Terminating previous local subprocess: conversation=%s pid=%s reason=%s",
                conversation_id,
                pid,
                reason,
            )
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except TimeoutError:
                logger.warning(
                    "[AgentService] Killing unresponsive local subprocess: conversation=%s pid=%s",
                    conversation_id,
                    pid,
                )
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(process.wait(), timeout=2.0)

        if request_path is not None:
            request_path.unlink(missing_ok=True)
        _ = await cls._terminate_orphaned_local_subprocesses_locked(
            conversation_id,
            reason=reason,
        )
        return True

    async def _monitor_local_subprocess_chat(
        self,
        *,
        conversation_id: str,
        message_id: str,
        correlation_id: str | None,
        process: asyncio.subprocess.Process,
        request_path: Path,
    ) -> None:
        return_code = await process.wait()
        pid = getattr(process, "pid", None)
        async with self._local_chat_lock:
            superseded = (conversation_id, pid) in self._local_subprocess_superseded
            self._local_subprocess_superseded.discard((conversation_id, pid))
            if self._local_subprocesses.get(conversation_id) is process:
                self._local_subprocesses.pop(conversation_id, None)
                self._local_subprocess_request_paths.pop(conversation_id, None)
        try:
            if return_code == 0 or superseded:
                return
            logger.error(
                "[AgentService] Local subprocess chat failed: conversation=%s return_code=%s",
                conversation_id,
                return_code,
            )
            try:
                from src.infrastructure.agent.actor.execution import _publish_error_event

                await _publish_error_event(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    error_message=f"Agent subprocess failed with exit code {return_code}",
                    correlation_id=correlation_id,
                )
            except Exception as pub_err:
                logger.warning(
                    "[AgentService] Failed to publish local subprocess error: %s",
                    pub_err,
                )
        finally:
            try:
                request_path.unlink(missing_ok=True)
            except Exception:
                logger.debug(
                    "[AgentService] Failed to remove local subprocess request file %s",
                    request_path,
                    exc_info=True,
                )

    @classmethod
    async def _track_local_chat_task(
        cls,
        conversation_id: str,
        task: asyncio.Task[Any],
        abort_signal: asyncio.Event,
    ) -> None:
        """Track a local worker task for cancellation and cleanup."""
        async with cls._local_chat_lock:
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
                _ = cls._local_chat_tasks.pop(conversation_id, None)
                _ = cls._local_chat_abort_signals.pop(conversation_id, None)

    @classmethod
    async def _cleanup_local_chat_task(cls, conversation_id: str, task: asyncio.Task[Any]) -> None:
        """Cleanup tracked local task if it is still current."""
        async with cls._local_chat_lock:
            if cls._local_chat_tasks.get(conversation_id) is task:
                _ = cls._local_chat_tasks.pop(conversation_id, None)
                _ = cls._local_chat_abort_signals.pop(conversation_id, None)
            if cls._local_chat_queue_tasks.get(conversation_id) is task:
                _ = cls._local_chat_queue_tasks.pop(conversation_id, None)
                queue = cls._local_chat_queues.get(conversation_id)
                if queue is None or queue.empty():
                    _ = cls._local_chat_queues.pop(conversation_id, None)

    @classmethod
    async def cancel_local_chat(cls, conversation_id: str) -> bool:
        """Cancel the active local turn and discard queued turns for a conversation."""
        async with cls._local_chat_lock:
            abort_signal = cls._local_chat_abort_signals.get(conversation_id)
            task = cls._local_chat_queue_tasks.pop(
                conversation_id,
                None,
            ) or cls._local_chat_tasks.get(conversation_id)
            queue = cls._local_chat_queues.pop(conversation_id, None)
            dropped_pending = 0
            if queue is not None:
                while True:
                    try:
                        _ = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    dropped_pending += 1
                    queue.task_done()

            subprocess_cancelled = await cls._terminate_local_subprocess_locked(
                conversation_id,
                reason="cancel",
            )

            if abort_signal:
                abort_signal.set()

            task_cancelled = False
            if task and not task.done():
                _ = task.cancel()
                task_cancelled = True

            _ = cls._local_chat_tasks.pop(conversation_id, None)
            _ = cls._local_chat_abort_signals.pop(conversation_id, None)
            return task_cancelled or subprocess_cancelled or dropped_pending > 0

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
            from src.domain.llm_providers.models import NoActiveProviderError
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
                except NoActiveProviderError:
                    logger.warning(
                        "[AgentService] No active LLM provider configured "
                        "-- graph service disabled for local execution. "
                        "Agent will work without knowledge graph features."
                    )
                except Exception as e:
                    logger.error("[AgentService] Graph service init failed: %s", e)
                    raise

            await self._bootstrap_mcp_sandbox()
            await self._bootstrap_agent_orchestrator()

            AgentRuntimeBootstrapper._local_bootstrapped = True

    async def _bootstrap_mcp_sandbox(self) -> None:
        """Initialize MCP Sandbox Adapter for Project Sandbox tool loading."""
        from src.infrastructure.agent.state.agent_worker_state import (
            get_mcp_sandbox_adapter,
            set_mcp_sandbox_adapter,
            sync_mcp_sandbox_adapter_from_docker,
        )

        if get_mcp_sandbox_adapter():
            return

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
                logger.info("[AgentService] Synced %d existing sandboxes from Docker", count)
            logger.info("[AgentService] MCP Sandbox adapter bootstrapped for local execution")
        except Exception as e:
            logger.warning(
                "[AgentService] MCP Sandbox adapter init failed (Sandbox tools disabled): %s",
                e,
            )

    async def _bootstrap_agent_orchestrator(self) -> None:
        """Initialize AgentOrchestrator for multi-agent tools."""
        from src.infrastructure.agent.state.agent_worker_state import (
            get_agent_orchestrator,
            set_agent_orchestrator,
        )

        if get_agent_orchestrator():
            return

        try:
            from src.configuration.config import get_settings as _get_ma_settings

            _ma_settings = _get_ma_settings()
            if _ma_settings.multi_agent_enabled:
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
                        _ma_settings, "agent_subagent_run_registry_path", None
                    ),
                    postgres_persistence_dsn=getattr(
                        _ma_settings, "agent_subagent_run_postgres_dsn", None
                    ),
                    sqlite_persistence_path=getattr(
                        _ma_settings, "agent_subagent_run_sqlite_path", None
                    ),
                    redis_cache_url=getattr(
                        _ma_settings, "agent_subagent_run_redis_cache_url", None
                    ),
                    redis_cache_ttl_seconds=(
                        getattr(_ma_settings, "agent_subagent_run_redis_cache_ttl_seconds", 60)
                    ),
                    terminal_retention_seconds=(
                        _ma_settings.agent_subagent_terminal_retention_seconds
                    ),
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
                    spawn_executor=self.launch_spawned_agent_session,
                    session_turn_executor=self.launch_agent_session_turn,
                )
                set_agent_orchestrator(_orchestrator)
                logger.info("[AgentService] AgentOrchestrator bootstrapped for multi-agent tools")
        except Exception as e:
            logger.warning(
                "[AgentService] AgentOrchestrator init failed (multi-agent tools disabled): %s",
                e,
            )

    def _get_api_key(self, settings: Settings) -> None:
        # Deprecated: Using ProviderResolutionService now
        return None

    def _get_base_url(self, settings: Settings) -> None:
        # Deprecated: Using ProviderResolutionService now
        return None

    def _get_model(self, settings: Settings) -> str:
        # Deprecated: Using ProviderResolutionService now
        return "qwen-plus"
