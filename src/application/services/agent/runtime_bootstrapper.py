"""Agent runtime bootstrapping extracted from AgentService."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from subprocess import DEVNULL
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy.exc import SQLAlchemyError

from src.configuration.config import Settings
from src.domain.model.agent import Conversation
from src.domain.model.agent.tenant_agent_config import TenantAgentConfig
from src.infrastructure.agent.sisyphus.builtin_agent import BUILTIN_SISYPHUS_ID

if TYPE_CHECKING:
    from src.infrastructure.agent.actor.types import ProjectAgentActorConfig, ProjectChatRequest
    from src.infrastructure.agent.orchestration.orchestrator import SpawnExecutionRequest

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[Any]] = set()
_LOCAL_SUBPROCESS_REQUEST_DIR = "MEMSTACK_LOCAL_AGENT_REQUEST_DIR"


def _safe_request_file_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)


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

            conversation = Conversation(
                id=child_session_id,
                project_id=resolved_project_id,
                tenant_id=resolved_tenant_id,
                user_id=resolved_user_id,
                title=f"{child_agent_name or child_agent_id} session",
                agent_config={"selected_agent_id": child_agent_id},
                metadata={
                    "spawned_by_agent_id": parent_agent_id,
                    "spawned_agent_id": child_agent_id,
                    "spawn_mode": mode,
                },
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
        )
        await self.start_chat_actor(
            conversation=conversation,
            message_id=str(uuid.uuid4()),
            user_message=request.message,
            conversation_context=[],
            agent_id=request.child_agent_id,
            parent_session_id=request.parent_session_id,
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
        runtime_mode = self._resolve_runtime_mode(
            configured_mode=settings.agent_runtime_mode,
            app_model_context=app_model_context,
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
            app_model_context=app_model_context,
            image_attachments=image_attachments,
            agent_id=agent_id or BUILTIN_SISYPHUS_ID,
            tenant_agent_config=tenant_agent_config.to_dict(),
            parent_session_id=parent_session_id,
        )

        if runtime_mode == "local":
            await self._register_project_local(conversation.tenant_id, conversation.project_id)
            if self._is_workspace_worker_runtime(app_model_context):
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
        """Start local execution task and register cancellation signal."""
        abort_signal = asyncio.Event()
        task = asyncio.create_task(self._run_chat_local(config, request, abort_signal=abort_signal))
        await self._track_local_chat_task(conversation_id, task, abort_signal)

    async def _start_local_subprocess_chat(
        self,
        conversation_id: str,
        config: ProjectAgentActorConfig,
        request: ProjectChatRequest,
    ) -> None:
        """Start workspace local execution in a child process.

        Workspace worker turns can outlive a dev-server reload. Running them
        in the uvicorn process turns reload SIGTERM into false task blockers,
        so local mode uses a short-lived child process for those turns.
        """
        request_path = self._write_local_subprocess_request(config, request)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "src.infrastructure.agent.actor.local_chat_worker",
            str(request_path),
            cwd=str(Path.cwd()),
            stdout=DEVNULL,
            stderr=None,
            env=os.environ.copy(),
        )
        monitor = asyncio.create_task(
            self._monitor_local_subprocess_chat(
                conversation_id=conversation_id,
                message_id=request.message_id,
                correlation_id=request.correlation_id,
                process=process,
                request_path=request_path,
            ),
            name=f"workspace-local-agent-subprocess:{conversation_id}",
        )
        _background_tasks.add(monitor)
        monitor.add_done_callback(_background_tasks.discard)

    @staticmethod
    def _write_local_subprocess_request(
        config: ProjectAgentActorConfig,
        request: ProjectChatRequest,
    ) -> Path:
        request_dir = Path(
            os.getenv(_LOCAL_SUBPROCESS_REQUEST_DIR, "/tmp/memstack-agent-requests")
        )
        request_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        file_name = _safe_request_file_name(
            f"{request.conversation_id}-{request.message_id}.json"
        )
        request_path = request_dir / file_name
        payload = {
            "config": asdict(config),
            "request": asdict(request),
        }
        fd = os.open(request_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False)
        return request_path

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
        if return_code == 0:
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
                from src.configuration.di_container import (
                    get_container,  # type: ignore[attr-defined]
                )

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
