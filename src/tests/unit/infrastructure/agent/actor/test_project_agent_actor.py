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
async def test_actor_orchestrator_binds_generation_owned_runtime() -> None:
    actor = _actor_instance()
    bind_orchestrator = AsyncMock(return_value="agent-orchestrator")
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
            "src.infrastructure.plugins.v2.agent_worker_runtime.bind_current_agent_orchestrator_v2",
            new=bind_orchestrator,
        ),
        patch(
            "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
            return_value=operation,
        ),
    ):
        await actor._ensure_agent_orchestrator_v2()

    bind_orchestrator.assert_awaited_once()
    assert bind_orchestrator.await_args.kwargs["owner"] is actor
    assert bind_orchestrator.await_args.kwargs["spawn_executor"] is not None
    assert bind_orchestrator.await_args.kwargs["session_turn_executor"] is not None

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
        await bind_orchestrator.await_args.kwargs["spawn_executor"](
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
        await bind_orchestrator.await_args.kwargs["session_turn_executor"](
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
    bind_orchestrator = AsyncMock(side_effect=error)

    with (
        patch(
            "src.infrastructure.plugins.v2.agent_worker_runtime.bind_current_agent_orchestrator_v2",
            new=bind_orchestrator,
        ),
        pytest.raises(RuntimeV2Error) as raised,
    ):
        await actor._ensure_agent_orchestrator_v2()

    assert raised.value is error
    bind_orchestrator.assert_awaited_once()
    await actor._plugin_admission_v2.close()


@pytest.mark.unit
async def test_actor_shutdown_awaits_main_tasks_before_stopping_project_agent() -> None:
    actor = _actor_instance()
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def _active_chat() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    task = asyncio.create_task(_active_chat())
    actor._tasks["message-1"] = task
    actor._task_conversations["message-1"] = "conversation-1"
    actor._abort_signals["message-1"] = asyncio.Event()
    await started.wait()

    agent = MagicMock()

    async def _stop_agent() -> bool:
        assert cleaned.is_set() is True
        return True

    agent.stop = AsyncMock(side_effect=_stop_agent)
    actor._agent = agent

    assert await actor.shutdown() is True

    assert task.cancelled() is True
    assert actor._tasks == {}
    assert actor._task_conversations == {}
    assert actor._abort_signals == {}
    agent.stop.assert_awaited_once_with()


@pytest.mark.unit
async def test_actor_shutdown_snapshot_waits_for_inflight_chat_registration() -> None:
    actor = _actor_instance()
    config = ProjectAgentActorConfig(tenant_id="tenant-a", project_id="project-a")
    actor._config = config
    bootstrap_started = asyncio.Event()
    release_bootstrap = asyncio.Event()

    async def _blocked_bootstrap() -> None:
        bootstrap_started.set()
        await release_bootstrap.wait()

    agent = MagicMock()
    agent.stop = AsyncMock(return_value=True)
    request = ProjectChatRequest(
        conversation_id="conversation-race",
        message_id="message-race",
        user_message="hello",
        user_id="user-a",
    )

    with (
        patch.object(actor, "_bootstrap_runtime", side_effect=_blocked_bootstrap),
        patch(
            "src.infrastructure.agent.actor.project_agent_actor.ProjectReActAgent",
            return_value=agent,
        ),
        patch.object(actor, "_run_chat", side_effect=asyncio.Event().wait),
    ):
        chat = asyncio.create_task(actor.chat(request))
        await asyncio.wait_for(bootstrap_started.wait(), timeout=1)

        shutdown = asyncio.create_task(actor.shutdown())
        await asyncio.sleep(0)
        assert shutdown.done() is False

        release_bootstrap.set()
        assert await asyncio.wait_for(chat, timeout=1) == {
            "status": "started",
            "message_id": "message-race",
        }
        assert await asyncio.wait_for(shutdown, timeout=1) is True

    assert actor._tasks == {}
    assert actor._task_conversations == {}
    assert actor._abort_signals == {}
    agent.stop.assert_awaited_once_with()


@pytest.mark.unit
async def test_actor_rejects_registration_after_shutdown_gate_closes() -> None:
    actor = _actor_instance()
    config = ProjectAgentActorConfig(tenant_id="tenant-a", project_id="project-a")
    actor._config = config
    cancelled = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def _active_chat() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
            await release_cleanup.wait()

    task = asyncio.create_task(_active_chat())
    actor._tasks["message-active"] = task
    actor._task_conversations["message-active"] = "conversation-active"
    actor._abort_signals["message-active"] = asyncio.Event()
    actor._agent = MagicMock()
    actor._agent.stop = AsyncMock(return_value=True)

    shutdown = asyncio.create_task(actor.shutdown())
    await asyncio.wait_for(cancelled.wait(), timeout=1)

    request = ProjectChatRequest(
        conversation_id="conversation-late",
        message_id="message-late",
        user_message="too late",
        user_id="user-a",
    )
    with pytest.raises(RuntimeV2Error) as chat_error:
        await actor.chat(request)
    with pytest.raises(RuntimeV2Error) as continue_error:
        await actor.continue_chat("request-late", {})
    with pytest.raises(RuntimeV2Error) as initialize_error:
        await actor.initialize(config)

    assert chat_error.value.code == "project_agent_actor_shutting_down"
    assert continue_error.value.code == "project_agent_actor_shutting_down"
    assert initialize_error.value.code == "project_agent_actor_shutting_down"

    release_cleanup.set()
    assert await asyncio.wait_for(shutdown, timeout=1) is True
    assert actor._tasks == {}
