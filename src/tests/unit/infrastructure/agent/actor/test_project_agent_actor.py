"""Unit tests for ProjectAgentActor scheduling behavior."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.agent.actor.project_agent_actor import ProjectAgentActor
from src.infrastructure.agent.actor.types import (
    ProjectAgentActorConfig,
    ProjectChatRequest,
    ProjectChatResult,
)
from src.infrastructure.agent.orchestration.orchestrator import (
    SessionTurnExecutionRequest,
    SpawnExecutionRequest,
)
from src.infrastructure.plugins.v2.boundary import current_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[6]


def _actor_instance() -> Any:
    actor_class = ProjectAgentActor.__ray_metadata__.modified_class
    return actor_class()


@pytest.mark.unit
async def test_actor_admits_complete_distribution_and_pins_turn_generation() -> None:
    source = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await source.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="generation-1",
    )
    first = source.current_distribution
    assert first is not None
    await source.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=2,
        version=2,
        nonce="generation-2",
    )
    second = source.current_distribution
    assert second is not None

    actor = _actor_instance()
    actor._config = ProjectAgentActorConfig(tenant_id="tenant-a", project_id="project-a")
    request = ProjectChatRequest(
        conversation_id="conversation-a",
        message_id="message-a",
        user_message="hello",
        user_id="user-a",
        plugin_generation=first.descriptor.to_payload(),
        plugin_distribution=first.to_payload(),
    )

    async with actor._admit_plugin_turn(request):
        operation = current_operation_context_v2()
        assert operation.descriptor == first.descriptor
        publication = await actor._plugin_admission_v2.host.apply_distribution(second.to_payload())
        assert publication.accepted
        assert operation.descriptor == first.descriptor
        assert actor._plugin_admission_v2.host.manager.current is not None
        assert actor._plugin_admission_v2.host.manager.current.descriptor == second.descriptor

    with pytest.raises(RuntimeV2Error) as stale:
        async with actor._admit_plugin_turn(request):
            pass
    assert stale.value.code == "stale_version"
    assert actor._plugin_admission_v2.host.manager.current is not None
    assert actor._plugin_admission_v2.host.manager.current.descriptor == second.descriptor

    await actor._plugin_admission_v2.close()
    await source.close()


@pytest.mark.unit
async def test_actor_rejects_turn_without_generation_before_execution() -> None:
    actor = _actor_instance()
    actor._config = ProjectAgentActorConfig(tenant_id="tenant-a", project_id="project-a")
    actor._agent = MagicMock()
    actor._agent.initialize = AsyncMock(return_value=True)
    request = ProjectChatRequest(
        conversation_id="conversation-a",
        message_id="message-a",
        user_message="hello",
        user_id="user-a",
    )

    with (
        patch("src.infrastructure.agent.actor.project_agent_actor.execute_project_chat") as execute,
        pytest.raises(RuntimeV2Error) as error,
    ):
        await actor._run_chat(request)

    assert error.value.code == "generation_descriptor_missing"
    execute.assert_not_called()
    await actor._plugin_admission_v2.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_serializes_same_conversation_turns_fifo() -> None:
    """The Ray actor must not run multiple turns for one conversation concurrently."""
    source = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await source.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="fifo-generation",
    )
    distribution = source.current_distribution
    assert distribution is not None
    distribution_payload = distribution.to_payload()
    await source.close()

    actor = _actor_instance()
    actor._config = ProjectAgentActorConfig(tenant_id="tenant-a", project_id="project-a")
    actor._agent = MagicMock()
    actor._agent.initialize = AsyncMock(return_value=True)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    started: list[str] = []
    observed_distributions: list[dict[str, Any] | None] = []

    first = ProjectChatRequest(
        conversation_id="conv-1",
        message_id="msg-1",
        user_message="first",
        user_id="user-1",
        plugin_generation=distribution.descriptor.to_payload(),
        plugin_distribution=distribution_payload,
    )
    second = ProjectChatRequest(
        conversation_id="conv-1",
        message_id="msg-2",
        user_message="second",
        user_id="user-1",
        plugin_generation=distribution.descriptor.to_payload(),
    )

    async def _execute_chat(
        _agent: object,
        request: ProjectChatRequest,
        abort_signal: asyncio.Event | None = None,
    ) -> ProjectChatResult:
        assert abort_signal is not None
        started.append(request.message_id)
        observed_distributions.append(request.plugin_distribution)
        if request.message_id == "msg-1":
            first_started.set()
            await release_first.wait()
        return ProjectChatResult(
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            content="done",
        )

    with patch(
        "src.infrastructure.agent.actor.project_agent_actor.execute_project_chat",
        side_effect=_execute_chat,
    ):
        first_result = await actor.chat(first)
        await first_started.wait()
        second_result = await actor.chat(second)
        await asyncio.sleep(0)

        assert first_result == {"status": "started", "message_id": "msg-1"}
        assert second_result == {"status": "started", "message_id": "msg-2"}
        assert started == ["msg-1"]

        release_first.set()
        for _ in range(20):
            if started == ["msg-1", "msg-2"]:
                break
            await asyncio.sleep(0.01)

    assert started == ["msg-1", "msg-2"]
    assert observed_distributions == [distribution_payload, distribution_payload]
    await actor._plugin_admission_v2.close()


@pytest.mark.unit
async def test_actor_initializes_once_per_generation_and_refreshes_on_switch() -> None:
    actor = _actor_instance()
    agent = MagicMock()
    agent.initialize = AsyncMock(return_value=True)
    actor._agent = agent
    first = PluginGenerationDescriptorV2(
        profile_id="memstack-default-v2",
        generation=1,
        digest="a" * 64,
    )
    second = PluginGenerationDescriptorV2(
        profile_id="memstack-default-v2",
        generation=2,
        digest="b" * 64,
    )

    await actor._ensure_agent_initialized_v2(SimpleNamespace(descriptor=first))
    await actor._ensure_agent_initialized_v2(SimpleNamespace(descriptor=first))
    await actor._ensure_agent_initialized_v2(SimpleNamespace(descriptor=second))

    assert agent.initialize.await_args_list == [
        call(force_refresh=False),
        call(force_refresh=True),
    ]
    await actor._plugin_admission_v2.close()


@pytest.mark.unit
async def test_actor_orchestrator_uses_pinned_worker_registry() -> None:
    actor = _actor_instance()
    run_registry = object()
    current_services = MagicMock(return_value=SimpleNamespace(subagent_run_registry=run_registry))
    set_orchestrator = MagicMock()
    spawn_manager = MagicMock(return_value="spawn-manager")
    orchestrator = MagicMock(return_value="agent-orchestrator")
    descriptor = PluginGenerationDescriptorV2(
        profile_id="memstack-default-v2",
        generation=7,
        digest="a" * 64,
    )
    distribution = {
        "descriptor": descriptor.to_payload(),
        "snapshot": {"profile_id": descriptor.profile_id},
        "envelope": {"version": 7, "nonce": "publication-7"},
    }
    operation = SimpleNamespace(
        descriptor=descriptor,
        require=MagicMock(return_value=distribution),
    )

    with (
        patch(
            "src.infrastructure.agent.actor.project_agent_actor.get_settings",
            return_value=SimpleNamespace(multi_agent_enabled=True),
        ),
        patch(
            "src.infrastructure.plugins.v2.agent_worker_runtime."
            "current_agent_worker_runtime_services_v2",
            current_services,
        ),
        patch(
            "src.infrastructure.agent.state.agent_worker_state.get_agent_orchestrator",
            return_value=None,
        ),
        patch(
            "src.infrastructure.agent.state.agent_worker_state.set_agent_orchestrator",
            set_orchestrator,
        ),
        patch(
            "src.infrastructure.agent.state.agent_worker_state.get_redis_client",
            new=AsyncMock(return_value="redis-client"),
        ),
        patch(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            return_value="db-session",
        ),
        patch(
            "src.infrastructure.adapters.secondary.persistence.sql_agent_registry."
            "SqlAgentRegistryRepository",
            return_value="agent-registry",
        ),
        patch(
            "src.infrastructure.adapters.secondary.messaging.redis_agent_message_bus."
            "RedisAgentMessageBusAdapter",
            return_value="message-bus",
        ),
        patch(
            "src.infrastructure.agent.orchestration.session_registry.AgentSessionRegistry",
            return_value="session-registry",
        ),
        patch(
            "src.infrastructure.agent.orchestration.spawn_manager.SpawnManager",
            spawn_manager,
        ),
        patch(
            "src.infrastructure.agent.orchestration.orchestrator.AgentOrchestrator",
            orchestrator,
        ),
        patch(
            "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
            return_value=operation,
        ),
    ):
        await actor._ensure_agent_orchestrator_v2()

    current_services.assert_called_once_with()
    spawn_manager.assert_called_once_with(
        session_registry="session-registry",
        run_registry=run_registry,
    )
    assert orchestrator.call_args.kwargs["spawn_executor"] is not None
    assert orchestrator.call_args.kwargs["session_turn_executor"] is not None
    set_orchestrator.assert_called_once_with("agent-orchestrator")

    conversation = SimpleNamespace(
        id="child-session",
        tenant_id="tenant-a",
        user_id="user-a",
        is_in_plan_mode=False,
        parent_conversation_id="parent-session",
    )
    actor.chat = AsyncMock()

    with (
        patch(
            "src.application.services.agent.runtime_bootstrapper."
            "AgentRuntimeBootstrapper.ensure_spawned_agent_conversation",
            new=AsyncMock(return_value=conversation),
        ),
        patch(
            "src.application.services.agent.runtime_bootstrapper."
            "AgentRuntimeBootstrapper.load_spawned_agent_conversation",
            new=AsyncMock(return_value=conversation),
        ),
        patch(
            "src.application.services.agent.runtime_bootstrapper."
            "AgentRuntimeBootstrapper._load_tenant_agent_config",
            new=AsyncMock(return_value=SimpleNamespace(to_dict=lambda: {"mode": "test"})),
        ),
    ):
        await orchestrator.call_args.kwargs["spawn_executor"](
            SpawnExecutionRequest(
                parent_agent_id="parent-agent",
                child_agent_id="child-agent",
                child_agent_name="Child",
                child_session_id="child-session",
                parent_session_id="parent-session",
                project_id="project-a",
                tenant_id="tenant-a",
                user_id="user-a",
                message="spawn",
            )
        )
        await orchestrator.call_args.kwargs["session_turn_executor"](
            SessionTurnExecutionRequest(
                child_agent_id="child-agent",
                child_session_id="child-session",
                project_id="project-a",
                tenant_id="tenant-a",
                message="continue",
            )
        )

    child_requests = [call.args[0] for call in actor.chat.await_args_list]
    assert [request.plugin_generation for request in child_requests] == [
        descriptor.to_payload(),
        descriptor.to_payload(),
    ]
    assert [request.plugin_distribution for request in child_requests] == [
        distribution,
        distribution,
    ]
    await actor._plugin_admission_v2.close()


@pytest.mark.unit
async def test_actor_orchestrator_propagates_runtime_v2_errors() -> None:
    actor = _actor_instance()
    error = RuntimeV2Error("missing_service", "worker runtime is unavailable")

    with (
        patch(
            "src.infrastructure.agent.actor.project_agent_actor.get_settings",
            return_value=SimpleNamespace(multi_agent_enabled=True),
        ),
        patch(
            "src.infrastructure.plugins.v2.agent_worker_runtime."
            "current_agent_worker_runtime_services_v2",
            side_effect=error,
        ),
        pytest.raises(RuntimeV2Error) as raised,
    ):
        await actor._ensure_agent_orchestrator_v2()

    assert raised.value is error
    await actor._plugin_admission_v2.close()
