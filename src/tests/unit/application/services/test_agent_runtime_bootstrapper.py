"""Unit tests for AgentRuntimeBootstrapper runtime mode behavior."""

import asyncio
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper
from src.domain.model.agent.tenant_agent_config import TenantAgentConfig
from src.infrastructure.agent.actor.types import ProjectAgentActorConfig, ProjectChatRequest


@pytest.fixture(autouse=True)
def _reset_local_task_tracking() -> None:
    AgentRuntimeBootstrapper._local_chat_tasks.clear()
    AgentRuntimeBootstrapper._local_chat_abort_signals.clear()
    AgentRuntimeBootstrapper._local_subprocesses.clear()
    AgentRuntimeBootstrapper._local_subprocess_request_paths.clear()
    AgentRuntimeBootstrapper._local_subprocess_superseded.clear()
    yield
    AgentRuntimeBootstrapper._local_chat_tasks.clear()
    AgentRuntimeBootstrapper._local_chat_abort_signals.clear()
    AgentRuntimeBootstrapper._local_subprocesses.clear()
    AgentRuntimeBootstrapper._local_subprocess_request_paths.clear()
    AgentRuntimeBootstrapper._local_subprocess_superseded.clear()


class _FakeTask:
    def __init__(self, done: bool = False) -> None:
        self._done = done
        self.cancel_called = False
        self.callbacks = []

    def done(self) -> bool:
        return self._done

    def cancel(self) -> None:
        self.cancel_called = True
        self._done = True

    def add_done_callback(self, callback) -> None:
        self.callbacks.append(callback)


class _FakeProcess:
    def __init__(self, *, pid: int, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.terminate_called = False
        self.kill_called = False

    def terminate(self) -> None:
        self.terminate_called = True
        self.returncode = -15

    def kill(self) -> None:
        self.kill_called = True
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode if self.returncode is not None else 0


@pytest.fixture
def bootstrapper() -> AgentRuntimeBootstrapper:
    """Create bootstrapper instance."""
    return AgentRuntimeBootstrapper()


@pytest.fixture
def conversation() -> SimpleNamespace:
    """Create minimal conversation object for runtime bootstrapper tests."""
    return SimpleNamespace(
        id="conv-1",
        tenant_id="tenant-1",
        project_id="proj-1",
        user_id="user-1",
        is_in_plan_mode=False,
    )


@pytest.fixture
def tenant_agent_config(conversation: SimpleNamespace) -> TenantAgentConfig:
    """Provide a stable tenant config without touching the database."""
    return TenantAgentConfig.create_default(tenant_id=conversation.tenant_id)


def _build_provider_mocks() -> tuple[SimpleNamespace, MagicMock, MagicMock]:
    provider_config = SimpleNamespace(
        llm_model="qwen-plus",
        api_key_encrypted="encrypted-key",
        base_url=None,
    )
    factory = MagicMock()
    factory.resolve_provider = AsyncMock(return_value=provider_config)

    encryption_service = MagicMock()
    encryption_service.decrypt.return_value = "decrypted-key"
    return provider_config, factory, encryption_service


def _build_fake_module(name: str, **attrs) -> ModuleType:
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_chat_actor_local_mode_uses_local_only(
    bootstrapper,
    conversation,
    tenant_agent_config,
):
    """Should execute locally without Ray when AGENT_RUNTIME_MODE=local."""
    _, factory, encryption_service = _build_provider_mocks()
    settings = SimpleNamespace(
        agent_runtime_mode="local",
        agent_max_tokens=4096,
        agent_max_steps=20,
    )
    created_tasks = []

    def _capture_task(coro):
        created_tasks.append(coro)
        coro.close()
        return MagicMock()

    fake_config_module = _build_fake_module(
        "src.configuration.config",
        get_settings=lambda: settings,
    )
    fake_provider_module = _build_fake_module(
        "src.infrastructure.llm.provider_factory",
        get_ai_service_factory=lambda: factory,
    )
    fake_encryption_module = _build_fake_module(
        "src.infrastructure.security.encryption_service",
        get_encryption_service=lambda: encryption_service,
    )

    with (
        patch.dict(
            "sys.modules",
            {
                "src.configuration.config": fake_config_module,
                "src.infrastructure.llm.provider_factory": fake_provider_module,
                "src.infrastructure.security.encryption_service": fake_encryption_module,
            },
        ),
        patch.object(
            bootstrapper,
            "_register_project_local",
            new_callable=AsyncMock,
        ) as register_local_mock,
        patch.object(
            bootstrapper,
            "_load_tenant_agent_config",
            new_callable=AsyncMock,
            return_value=tenant_agent_config,
        ),
        patch.object(bootstrapper, "_run_chat_local", new_callable=AsyncMock),
        patch("asyncio.create_task", side_effect=_capture_task) as create_task_mock,
    ):
        actor_id = await bootstrapper.start_chat_actor(
            conversation=conversation,
            message_id="msg-1",
            user_message="hello",
            conversation_context=[],
        )

    assert actor_id == "agent:tenant-1:proj-1:default"
    register_local_mock.assert_awaited_once_with("tenant-1", "proj-1")
    create_task_mock.assert_called_once()
    assert len(created_tasks) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_chat_actor_local_workspace_worker_uses_subprocess(
    bootstrapper,
    conversation,
    tenant_agent_config,
):
    """Workspace worker local mode should survive API reload by using a subprocess."""
    _, factory, encryption_service = _build_provider_mocks()
    settings = SimpleNamespace(
        agent_runtime_mode="local",
        agent_max_tokens=4096,
        agent_max_steps=20,
    )
    fake_config_module = _build_fake_module(
        "src.configuration.config",
        get_settings=lambda: settings,
    )
    fake_provider_module = _build_fake_module(
        "src.infrastructure.llm.provider_factory",
        get_ai_service_factory=lambda: factory,
    )
    fake_encryption_module = _build_fake_module(
        "src.infrastructure.security.encryption_service",
        get_encryption_service=lambda: encryption_service,
    )

    with (
        patch.dict(
            "sys.modules",
            {
                "src.configuration.config": fake_config_module,
                "src.infrastructure.llm.provider_factory": fake_provider_module,
                "src.infrastructure.security.encryption_service": fake_encryption_module,
            },
        ),
        patch.object(
            bootstrapper,
            "_register_project_local",
            new_callable=AsyncMock,
        ) as register_local_mock,
        patch.object(
            bootstrapper,
            "_load_tenant_agent_config",
            new_callable=AsyncMock,
            return_value=tenant_agent_config,
        ),
        patch.object(bootstrapper, "_run_chat_local", new_callable=AsyncMock) as local_run_mock,
        patch.object(
            bootstrapper,
            "_start_local_subprocess_chat",
            new_callable=AsyncMock,
        ) as subprocess_mock,
    ):
        actor_id = await bootstrapper.start_chat_actor(
            conversation=conversation,
            message_id="msg-1",
            user_message="hello",
            conversation_context=[],
            app_model_context={"context_type": "workspace_worker_runtime"},
        )

    assert actor_id == "agent:tenant-1:proj-1:default"
    register_local_mock.assert_awaited_once_with("tenant-1", "proj-1")
    subprocess_mock.assert_awaited_once()
    local_run_mock.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_local_workspace_subprocess_starts_new_session(bootstrapper, tmp_path):
    """Detached process sessions keep workspace workers alive across dev reloads."""
    request_path = tmp_path / "request.json"
    process = _FakeProcess(pid=123)
    created_tasks = []

    def _capture_task(coro, **kwargs):
        created_tasks.append((coro, kwargs))
        coro.close()
        return _FakeTask(done=True)

    config = ProjectAgentActorConfig(tenant_id="tenant-1", project_id="proj-1")
    request = ProjectChatRequest(
        conversation_id="conv-1",
        message_id="msg-1",
        user_message="hello",
        user_id="user-1",
    )

    with (
        patch.object(
            bootstrapper,
            "_write_local_subprocess_request",
            return_value=request_path,
        ),
        patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as subprocess_mock,
        patch("asyncio.create_task", side_effect=_capture_task),
    ):
        subprocess_mock.return_value = process
        await bootstrapper._start_local_subprocess_chat("conv-1", config, request)

    subprocess_mock.assert_awaited_once()
    assert subprocess_mock.await_args.kwargs["start_new_session"] is True
    assert created_tasks
    assert AgentRuntimeBootstrapper._local_subprocesses["conv-1"] is process


@pytest.mark.unit
@pytest.mark.asyncio
async def test_local_workspace_subprocess_replaces_previous_process(bootstrapper, tmp_path):
    """Relaunching the same conversation should terminate the old detached worker."""
    request_paths = [tmp_path / "request-1.json", tmp_path / "request-2.json"]
    for path in request_paths:
        path.write_text("{}", encoding="utf-8")
    previous = _FakeProcess(pid=111)
    current = _FakeProcess(pid=222)

    def _capture_task(coro, **kwargs):
        coro.close()
        return _FakeTask(done=True)

    config = ProjectAgentActorConfig(tenant_id="tenant-1", project_id="proj-1")
    request = ProjectChatRequest(
        conversation_id="conv-1",
        message_id="msg-1",
        user_message="hello",
        user_id="user-1",
    )

    with (
        patch.object(
            bootstrapper,
            "_write_local_subprocess_request",
            side_effect=request_paths,
        ),
        patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as subprocess_mock,
        patch("asyncio.create_task", side_effect=_capture_task),
    ):
        subprocess_mock.side_effect = [previous, current]
        await bootstrapper._start_local_subprocess_chat("conv-1", config, request)
        await bootstrapper._start_local_subprocess_chat("conv-1", config, request)

    assert previous.terminate_called is True
    assert AgentRuntimeBootstrapper._local_subprocesses["conv-1"] is current
    assert AgentRuntimeBootstrapper._local_subprocess_request_paths["conv-1"] == request_paths[1]
    assert not request_paths[0].exists()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_chat_actor_ray_mode_raises_when_router_unavailable(
    bootstrapper,
    conversation,
    tenant_agent_config,
):
    """Should fail fast instead of local fallback when AGENT_RUNTIME_MODE=ray."""
    _, factory, encryption_service = _build_provider_mocks()
    settings = SimpleNamespace(
        agent_runtime_mode="ray",
        agent_max_tokens=4096,
        agent_max_steps=20,
    )
    fake_actor_manager = ModuleType("src.infrastructure.agent.actor.actor_manager")
    fake_actor_manager.ensure_router_actor = AsyncMock(return_value=None)
    fake_actor_manager.get_or_create_actor = AsyncMock(return_value=None)
    fake_actor_manager.register_project = AsyncMock()

    fake_config_module = _build_fake_module(
        "src.configuration.config",
        get_settings=lambda: settings,
    )
    fake_provider_module = _build_fake_module(
        "src.infrastructure.llm.provider_factory",
        get_ai_service_factory=lambda: factory,
    )
    fake_encryption_module = _build_fake_module(
        "src.infrastructure.security.encryption_service",
        get_encryption_service=lambda: encryption_service,
    )

    with (
        patch.dict(
            "sys.modules",
            {
                "src.configuration.config": fake_config_module,
                "src.infrastructure.llm.provider_factory": fake_provider_module,
                "src.infrastructure.security.encryption_service": fake_encryption_module,
                "src.infrastructure.agent.actor.actor_manager": fake_actor_manager,
            },
        ),
        patch.object(bootstrapper, "_run_chat_local", new_callable=AsyncMock) as local_run_mock,
        patch.object(
            bootstrapper,
            "_register_project_local",
            new_callable=AsyncMock,
        ) as register_local_mock,
        patch.object(
            bootstrapper,
            "_load_tenant_agent_config",
            new_callable=AsyncMock,
            return_value=tenant_agent_config,
        ),
        pytest.raises(RuntimeError, match="AGENT_RUNTIME_MODE=ray"),
    ):
        await bootstrapper.start_chat_actor(
            conversation=conversation,
            message_id="msg-1",
            user_message="hello",
            conversation_context=[],
        )

    local_run_mock.assert_not_called()
    register_local_mock.assert_not_called()
    fake_actor_manager.ensure_router_actor.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_chat_actor_workspace_worker_forces_ray_when_runtime_is_auto(
    bootstrapper,
    conversation,
    tenant_agent_config,
):
    """Workspace worker turns should not fall back to local when runtime mode is auto."""
    _, factory, encryption_service = _build_provider_mocks()
    settings = SimpleNamespace(
        agent_runtime_mode="auto",
        agent_max_tokens=4096,
        agent_max_steps=20,
    )
    fake_actor_manager = ModuleType("src.infrastructure.agent.actor.actor_manager")
    fake_actor_manager.ensure_router_actor = AsyncMock(return_value=None)
    fake_actor_manager.get_or_create_actor = AsyncMock(return_value=None)
    fake_actor_manager.register_project = AsyncMock()

    fake_config_module = _build_fake_module(
        "src.configuration.config",
        get_settings=lambda: settings,
    )
    fake_provider_module = _build_fake_module(
        "src.infrastructure.llm.provider_factory",
        get_ai_service_factory=lambda: factory,
    )
    fake_encryption_module = _build_fake_module(
        "src.infrastructure.security.encryption_service",
        get_encryption_service=lambda: encryption_service,
    )

    with (
        patch.dict(
            "sys.modules",
            {
                "src.configuration.config": fake_config_module,
                "src.infrastructure.llm.provider_factory": fake_provider_module,
                "src.infrastructure.security.encryption_service": fake_encryption_module,
                "src.infrastructure.agent.actor.actor_manager": fake_actor_manager,
            },
        ),
        patch.object(bootstrapper, "_run_chat_local", new_callable=AsyncMock) as local_run_mock,
        patch.object(
            bootstrapper,
            "_register_project_local",
            new_callable=AsyncMock,
        ) as register_local_mock,
        patch.object(
            bootstrapper,
            "_load_tenant_agent_config",
            new_callable=AsyncMock,
            return_value=tenant_agent_config,
        ),
        pytest.raises(RuntimeError, match="AGENT_RUNTIME_MODE=ray"),
    ):
        await bootstrapper.start_chat_actor(
            conversation=conversation,
            message_id="msg-1",
            user_message="hello",
            conversation_context=[],
            app_model_context={"context_type": "workspace_worker_runtime"},
        )

    local_run_mock.assert_not_called()
    register_local_mock.assert_not_called()
    fake_actor_manager.ensure_router_actor.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bootstrap_agent_orchestrator_wires_shared_run_registry(bootstrapper):
    """Multi-agent bootstrap should attach the shared SubAgent run registry."""
    sentinel_registry = object()
    settings = SimpleNamespace(
        multi_agent_enabled=True,
        agent_subagent_terminal_retention_seconds=321,
        agent_subagent_run_registry_path="/tmp/runs.json",
        agent_subagent_run_postgres_dsn="postgresql://example/db",
        agent_subagent_run_sqlite_path="/tmp/runs.sqlite",
        agent_subagent_run_redis_cache_url="redis://localhost:6379/0",
        agent_subagent_run_redis_cache_ttl_seconds=45,
    )
    get_settings_mock = MagicMock(return_value=settings)
    get_shared_registry_mock = MagicMock(return_value=sentinel_registry)
    get_agent_orchestrator_mock = MagicMock(return_value=None)
    set_agent_orchestrator_mock = MagicMock()
    get_redis_client_mock = AsyncMock(return_value="redis-client")
    async_session_factory_mock = MagicMock(return_value="db-session")
    sql_agent_registry_ctor = MagicMock(return_value="agent-registry")
    message_bus_ctor = MagicMock(return_value="message-bus")
    session_registry_ctor = MagicMock(return_value="session-registry")
    spawn_manager_ctor = MagicMock(return_value="spawn-manager")
    agent_orchestrator_ctor = MagicMock(return_value="agent-orchestrator")

    fake_config_module = _build_fake_module(
        "src.configuration.config",
        get_settings=get_settings_mock,
    )
    fake_database_module = _build_fake_module(
        "src.infrastructure.adapters.secondary.persistence.database",
        async_session_factory=async_session_factory_mock,
    )
    fake_registry_module = _build_fake_module(
        "src.infrastructure.adapters.secondary.persistence.sql_agent_registry",
        SqlAgentRegistryRepository=sql_agent_registry_ctor,
    )
    fake_message_bus_module = _build_fake_module(
        "src.infrastructure.adapters.secondary.messaging.redis_agent_message_bus",
        RedisAgentMessageBusAdapter=message_bus_ctor,
    )
    fake_orchestrator_module = _build_fake_module(
        "src.infrastructure.agent.orchestration.orchestrator",
        AgentOrchestrator=agent_orchestrator_ctor,
    )
    fake_session_registry_module = _build_fake_module(
        "src.infrastructure.agent.orchestration.session_registry",
        AgentSessionRegistry=session_registry_ctor,
    )
    fake_spawn_manager_module = _build_fake_module(
        "src.infrastructure.agent.orchestration.spawn_manager",
        SpawnManager=spawn_manager_ctor,
    )
    fake_run_registry_module = _build_fake_module(
        "src.infrastructure.agent.subagent.run_registry",
        get_shared_subagent_run_registry=get_shared_registry_mock,
    )
    fake_worker_state_module = _build_fake_module(
        "src.infrastructure.agent.state.agent_worker_state",
        get_agent_orchestrator=get_agent_orchestrator_mock,
        set_agent_orchestrator=set_agent_orchestrator_mock,
        get_redis_client=get_redis_client_mock,
    )

    with patch.dict(
        "sys.modules",
        {
            "src.configuration.config": fake_config_module,
            "src.infrastructure.adapters.secondary.persistence.database": fake_database_module,
            "src.infrastructure.adapters.secondary.persistence.sql_agent_registry": (
                fake_registry_module
            ),
            "src.infrastructure.adapters.secondary.messaging.redis_agent_message_bus": (
                fake_message_bus_module
            ),
            "src.infrastructure.agent.orchestration.orchestrator": fake_orchestrator_module,
            "src.infrastructure.agent.orchestration.session_registry": (
                fake_session_registry_module
            ),
            "src.infrastructure.agent.orchestration.spawn_manager": fake_spawn_manager_module,
            "src.infrastructure.agent.subagent.run_registry": fake_run_registry_module,
            "src.infrastructure.agent.state.agent_worker_state": fake_worker_state_module,
        },
    ):
        await bootstrapper._bootstrap_agent_orchestrator()

    get_shared_registry_mock.assert_called_once_with(
        persistence_path="/tmp/runs.json",
        postgres_persistence_dsn="postgresql://example/db",
        sqlite_persistence_path="/tmp/runs.sqlite",
        redis_cache_url="redis://localhost:6379/0",
        redis_cache_ttl_seconds=45,
        terminal_retention_seconds=321,
    )
    spawn_manager_ctor.assert_called_once_with(
        session_registry="session-registry",
        run_registry=sentinel_registry,
    )
    agent_orchestrator_ctor.assert_called_once()
    spawn_executor = agent_orchestrator_ctor.call_args.kwargs["spawn_executor"]
    assert getattr(spawn_executor, "__self__", None) is bootstrapper
    assert (
        getattr(spawn_executor, "__func__", None)
        is AgentRuntimeBootstrapper.launch_spawned_agent_session
    )
    set_agent_orchestrator_mock.assert_called_once_with("agent-orchestrator")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_chat_actor_auto_mode_falls_back_to_local(
    bootstrapper,
    conversation,
    tenant_agent_config,
):
    """Should fallback to local execution when AGENT_RUNTIME_MODE=auto and Ray actor is unavailable."""
    _, factory, encryption_service = _build_provider_mocks()
    settings = SimpleNamespace(
        agent_runtime_mode="auto",
        agent_max_tokens=4096,
        agent_max_steps=20,
    )
    created_tasks = []

    def _capture_task(coro):
        created_tasks.append(coro)
        coro.close()
        return MagicMock()

    fake_actor_manager = ModuleType("src.infrastructure.agent.actor.actor_manager")
    fake_actor_manager.ensure_router_actor = AsyncMock(return_value=None)
    fake_actor_manager.get_or_create_actor = AsyncMock(return_value=None)
    fake_actor_manager.register_project = AsyncMock()

    fake_config_module = _build_fake_module(
        "src.configuration.config",
        get_settings=lambda: settings,
    )
    fake_provider_module = _build_fake_module(
        "src.infrastructure.llm.provider_factory",
        get_ai_service_factory=lambda: factory,
    )
    fake_encryption_module = _build_fake_module(
        "src.infrastructure.security.encryption_service",
        get_encryption_service=lambda: encryption_service,
    )

    with (
        patch.dict(
            "sys.modules",
            {
                "src.configuration.config": fake_config_module,
                "src.infrastructure.llm.provider_factory": fake_provider_module,
                "src.infrastructure.security.encryption_service": fake_encryption_module,
                "src.infrastructure.agent.actor.actor_manager": fake_actor_manager,
            },
        ),
        patch.object(
            bootstrapper,
            "_register_project_local",
            new_callable=AsyncMock,
        ) as register_local_mock,
        patch.object(
            bootstrapper,
            "_load_tenant_agent_config",
            new_callable=AsyncMock,
            return_value=tenant_agent_config,
        ),
        patch.object(bootstrapper, "_run_chat_local", new_callable=AsyncMock),
        patch("asyncio.create_task", side_effect=_capture_task) as create_task_mock,
    ):
        actor_id = await bootstrapper.start_chat_actor(
            conversation=conversation,
            message_id="msg-1",
            user_message="hello",
            conversation_context=[],
        )

    assert actor_id == "agent:tenant-1:proj-1:default"
    fake_actor_manager.register_project.assert_awaited_once_with("tenant-1", "proj-1")
    register_local_mock.assert_awaited_once_with("tenant-1", "proj-1")
    create_task_mock.assert_called_once()
    assert len(created_tasks) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_local_chat_tracking_replaces_previous_task() -> None:
    """Tracking a new local task should cancel previous in-flight task for same conversation."""
    previous_abort = asyncio.Event()
    previous_task = _FakeTask()

    current_abort = asyncio.Event()
    current_task = _FakeTask()

    await AgentRuntimeBootstrapper._track_local_chat_task("conv-1", previous_task, previous_abort)
    await AgentRuntimeBootstrapper._track_local_chat_task("conv-1", current_task, current_abort)

    assert previous_task.cancel_called is True
    assert previous_abort.is_set()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancel_local_chat_sets_abort_and_cancels_task() -> None:
    """cancel_local_chat should set abort signal and cancel active local task."""
    abort_signal = asyncio.Event()
    task = _FakeTask()

    await AgentRuntimeBootstrapper._track_local_chat_task("conv-1", task, abort_signal)

    cancelled = await AgentRuntimeBootstrapper.cancel_local_chat("conv-1")

    assert cancelled is True
    assert abort_signal.is_set()
    assert task.cancel_called is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancel_local_chat_terminates_subprocess(tmp_path) -> None:
    """cancel_local_chat should also stop detached workspace worker processes."""
    request_path = tmp_path / "request.json"
    request_path.write_text("{}", encoding="utf-8")
    process = _FakeProcess(pid=333)
    AgentRuntimeBootstrapper._local_subprocesses["conv-1"] = process
    AgentRuntimeBootstrapper._local_subprocess_request_paths["conv-1"] = request_path

    cancelled = await AgentRuntimeBootstrapper.cancel_local_chat("conv-1")

    assert cancelled is True
    assert process.terminate_called is True
    assert "conv-1" not in AgentRuntimeBootstrapper._local_subprocesses
    assert not request_path.exists()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_has_running_local_subprocess_reflects_process_returncode() -> None:
    """Snapshot recovery can use the tracked detached worker as a liveness signal."""
    AgentRuntimeBootstrapper._local_subprocesses["conv-running"] = _FakeProcess(pid=444)
    AgentRuntimeBootstrapper._local_subprocesses["conv-finished"] = _FakeProcess(
        pid=555,
        returncode=0,
    )

    assert await AgentRuntimeBootstrapper.has_running_local_subprocess("conv-running") is True
    assert await AgentRuntimeBootstrapper.has_running_local_subprocess("conv-finished") is False
    assert await AgentRuntimeBootstrapper.has_running_local_subprocess("conv-missing") is False
