"""Unit tests for AgentRuntimeBootstrapper runtime mode behavior."""

from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper


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
async def test_start_chat_actor_local_mode_uses_local_only(bootstrapper, conversation):
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
async def test_start_chat_actor_ray_mode_raises_when_router_unavailable(bootstrapper, conversation):
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
    ):
        with pytest.raises(RuntimeError, match="AGENT_RUNTIME_MODE=ray"):
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
async def test_start_chat_actor_auto_mode_falls_back_to_local(bootstrapper, conversation):
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
