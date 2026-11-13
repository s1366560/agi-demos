"""Admission failure reaches the parent without pinning an operation.

The actor and the local queue call the real publisher. Spawn registration,
the message bus, the session registry, and the run registry are the production
objects. Redis, a Ray cluster, and a paid model are not used.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.application.services.agent.runtime_bootstrapper import (
    AgentRuntimeBootstrapper,
    _LocalChatWorkItem,
)
from src.domain.model.agent.agent_role import AgentRole
from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.model.agent.subagent_run import SubAgentRunStatus
from src.domain.ports.services.agent_message_bus_port import (
    AgentMessage,
    AgentMessageBusPort,
    AgentMessageType,
)
from src.infrastructure.agent.actor.project_agent_actor import ProjectAgentActor
from src.infrastructure.agent.actor.types import (
    ProjectAgentActorConfig,
    ProjectChatRequest,
    ProjectChatResult,
)
from src.infrastructure.agent.orchestration.bootstrap_failure_settlement import (
    settle_unpinned_child_bootstrap_failure,
)
from src.infrastructure.agent.orchestration.orchestrator import AgentOrchestrator
from src.infrastructure.agent.orchestration.session_registry import AgentSessionRegistry
from src.infrastructure.agent.orchestration.spawn_manager import SpawnManager
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import (
    DataPlaneGenerationAdmissionV2,
    PlatformPluginRuntimeHostV2,
)

_ROOT = Path(__file__).resolve().parents[6]
pytestmark = pytest.mark.unit


class MemoryBus(AgentMessageBusPort):
    """In-process bus. The parent reads the same history the spawn wrote."""

    def __init__(self) -> None:
        self.messages: list[AgentMessage] = []

    async def send_message(
        self,
        from_agent_id: str,
        to_agent_id: str,
        session_id: str,
        content: str,
        message_type: AgentMessageType,
        metadata: dict[str, Any] | None = None,
        parent_message_id: str | None = None,
    ) -> str:
        message_id = f"m-{len(self.messages)}"
        self.messages.append(
            AgentMessage(
                message_id=message_id,
                from_agent_id=from_agent_id,
                to_agent_id=to_agent_id,
                session_id=session_id,
                content=content,
                message_type=message_type,
                metadata=metadata,
                parent_message_id=parent_message_id,
            )
        )
        return message_id

    async def receive_messages(
        self,
        agent_id: str,
        session_id: str,
        since_id: str | None = None,
        limit: int = 50,
    ) -> list[AgentMessage]:
        del agent_id, since_id
        return await self.get_message_history(session_id, limit)

    def subscribe_messages(
        self,
        agent_id: str,
        session_id: str,
        timeout_ms: int = 30000,
    ) -> Any:
        del agent_id, session_id, timeout_ms
        raise AssertionError("bootstrap failure settlement must not subscribe")

    async def get_message_history(self, session_id: str, limit: int = 50) -> list[AgentMessage]:
        matched = [item for item in self.messages if item.session_id == session_id]
        return matched[-limit:]

    async def cleanup_session(self, session_id: str) -> None:
        self.messages = [item for item in self.messages if item.session_id != session_id]

    async def session_has_messages(self, session_id: str) -> bool:
        return any(item.session_id == session_id for item in self.messages)


def _agent(agent_id: str, *, tenant_id: str, project_id: str) -> Mock:
    agent = Mock()
    agent.id = agent_id
    agent.name = agent_id
    agent.display_name = agent_id
    agent.tenant_id = tenant_id
    agent.project_id = project_id
    agent.enabled = True
    agent.discoverable = True
    agent.agent_to_agent_enabled = True
    agent.can_spawn = True
    agent.max_spawn_depth = 3
    agent.role = AgentRole.ORCHESTRATOR
    return agent


def _actor() -> Any:
    actor_class = ProjectAgentActor.__ray_metadata__.modified_class
    actor = actor_class()
    actor._plugin_admission_v2 = DataPlaneGenerationAdmissionV2(builtin_runtime_definitions_v2())
    actor._config = ProjectAgentActorConfig(tenant_id="tenant", project_id="project")
    actor._agent = MagicMock()
    actor._agent.initialize = AsyncMock(return_value=True)
    return actor


def _orchestrator(
    executor: Any,
    *,
    runs: SubAgentRunRegistry | None = None,
) -> tuple[AgentOrchestrator, MemoryBus, AgentSessionRegistry, SubAgentRunRegistry]:
    bus = MemoryBus()
    sessions = AgentSessionRegistry()
    registry = runs if runs is not None else SubAgentRunRegistry(sync_across_processes=False)
    manager = SpawnManager(session_registry=sessions, run_registry=registry)
    agents = Mock()
    agents.get_by_id = AsyncMock(
        side_effect=lambda agent_id, **kwargs: _agent(
            agent_id,
            tenant_id=kwargs.get("tenant_id") or "tenant",
            project_id=kwargs.get("project_id") or "project",
        )
    )
    agents.get_by_name = AsyncMock(return_value=None)
    orchestrator = AgentOrchestrator(
        agents,
        sessions,
        manager,
        bus,
        spawn_executor=executor,
    )
    return orchestrator, bus, sessions, registry


async def _spawn(
    orchestrator: AgentOrchestrator,
    sessions: AgentSessionRegistry,
    *,
    metadata: dict[str, Any] | None = None,
    parent_session_id: str = "parent-session",
) -> Any:
    await sessions.register(
        agent_id="parent",
        conversation_id=parent_session_id,
        project_id="project",
    )
    return await orchestrator.spawn_agent(
        parent_agent_id="parent",
        target_agent_id="child",
        message="ping",
        mode=SpawnMode.RUN,
        parent_session_id=parent_session_id,
        project_id="project",
        tenant_id="tenant",
        user_id="user",
        conversation_id=parent_session_id,
        metadata=metadata,
    )


def _history_types(bus: MemoryBus, child_session_id: str) -> list[AgentMessageType]:
    return [
        item.message_type for item in bus.messages if item.session_id == child_session_id
    ]


@pytest.mark.asyncio
async def test_missing_generation_fails_spawn_without_initialize_or_execute() -> None:
    actor = _actor()
    child_box: dict[str, str] = {}

    async def executor(request: Any) -> None:
        child_box["id"] = request.child_session_id
        await actor._run_chat(
            ProjectChatRequest(
                conversation_id=request.child_session_id,
                message_id="message-1",
                user_message=request.message,
                user_id="user",
                agent_id=request.child_agent_id,
                parent_session_id=request.parent_session_id,
            )
        )

    orchestrator, bus, sessions, runs = _orchestrator(executor)
    execute = AsyncMock()
    with patch(
        "src.infrastructure.agent.actor.project_agent_actor.execute_project_chat",
        new=execute,
    ):
        spawned = await _spawn(orchestrator, sessions)

    child_session_id = child_box["id"]
    record = await orchestrator.get_spawn_record(child_session_id)
    assert record is not None
    assert record.status == "failed"
    assert actor._agent.initialize.await_count == 0
    execute.assert_not_called()
    assert _history_types(bus, child_session_id) == [
        AgentMessageType.REQUEST,
        AgentMessageType.RESPONSE,
    ]
    failure = bus.messages[-1]
    assert failure.content.startswith("failure_class=backend code=generation_descriptor_missing")
    assert failure.metadata is not None
    assert failure.metadata["success"] is False
    run = runs.get_run("parent-session", spawned.spawn_record.id)
    assert run is not None
    assert run.status is SubAgentRunStatus.FAILED
    assert await sessions.get_session_for_conversation(child_session_id, "project") is None
    assert await sessions.get_session_for_conversation("parent-session", "project") is not None

    await settle_unpinned_child_bootstrap_failure(
        child_session_id=child_session_id,
        child_agent_id="child",
        parent_session_id="parent-session",
        project_id="project",
        request_message_id="message-1",
        error_message=failure.content,
    )
    assert _history_types(bus, child_session_id) == [
        AgentMessageType.REQUEST,
        AgentMessageType.RESPONSE,
    ]
    await actor._plugin_admission_v2.close()


@pytest.mark.asyncio
async def test_local_queue_admission_failure_uses_the_same_spawn_record() -> None:
    worker: asyncio.Task[Any] | None = None

    async def executor(request: Any) -> None:
        nonlocal worker
        bootstrapper = AgentRuntimeBootstrapper()
        await bootstrapper._enqueue_local_chat_work(
            request.child_session_id,
            _LocalChatWorkItem(
                config=ProjectAgentActorConfig(tenant_id="tenant", project_id="project"),
                request=ProjectChatRequest(
                    conversation_id=request.child_session_id,
                    message_id="message-local",
                    user_message=request.message,
                    user_id="user",
                    agent_id=request.child_agent_id,
                    parent_session_id=request.parent_session_id,
                ),
            ),
        )
        worker = AgentRuntimeBootstrapper._local_chat_queue_tasks[request.child_session_id]

    orchestrator, bus, sessions, _runs = _orchestrator(executor)
    initialize = AsyncMock(return_value=True)
    execute = AsyncMock()
    with (
        patch(
            "src.infrastructure.agent.core.project_react_agent.ProjectReActAgent.initialize",
            new=initialize,
        ),
        patch(
            "src.infrastructure.agent.actor.execution.execute_project_chat",
            new=execute,
        ),
    ):
        await _spawn(orchestrator, sessions, parent_session_id="parent-local")
        assert worker is not None
        await asyncio.wait_for(worker, timeout=20)

    child_messages = [item for item in bus.messages if item.session_id != "parent-local"]
    child_session_id = child_messages[0].session_id
    record = await orchestrator.get_spawn_record(child_session_id)
    assert record is not None
    assert record.status == "failed"
    initialize.assert_not_called()
    execute.assert_not_called()
    assert child_messages[0].message_type is AgentMessageType.REQUEST
    assert child_messages[1].message_type is AgentMessageType.RESPONSE
    assert "generation_descriptor_missing" in child_messages[1].content
    assert await sessions.get_session_for_conversation("parent-local", "project") is not None


@pytest.mark.asyncio
async def test_admitted_generation_is_not_failed_before_execution() -> None:
    source = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await source.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
        nonce="bootstrap-failure-generation",
    )
    distribution = source.current_distribution
    assert distribution is not None
    actor = _actor()
    seen: dict[str, int] = {"execute": 0}

    async def executor(request: Any) -> None:
        async def execute(*_args: Any, **_kwargs: Any) -> ProjectChatResult:
            seen["execute"] += 1
            return ProjectChatResult(
                conversation_id=request.child_session_id,
                message_id="message-ok",
                content="started",
            )

        async def ready(*_args: Any, **_kwargs: Any) -> int:
            return 0

        with (
            patch(
                "src.application.services.wasm_operation_authority_v2.prepare_agent_wasm_tools_v2",
                new=ready,
            ),
            patch.object(actor, "_ensure_agent_orchestrator_v2", new=ready),
            patch(
                "src.infrastructure.agent.actor.project_agent_actor.execute_project_chat",
                new=execute,
            ),
        ):
            await actor._run_chat(
                ProjectChatRequest(
                    conversation_id=request.child_session_id,
                    message_id="message-ok",
                    user_message=request.message,
                    user_id="user",
                    agent_id=request.child_agent_id,
                    parent_session_id=request.parent_session_id,
                    plugin_generation=distribution.descriptor.to_payload(),
                    plugin_distribution=distribution.to_payload(),
                )
            )

    orchestrator, bus, sessions, _runs = _orchestrator(executor)
    try:
        await _spawn(orchestrator, sessions, parent_session_id="parent-admitted")
    finally:
        await actor._plugin_admission_v2.close()
        await source.close()

    child_session_id = next(
        item.session_id for item in bus.messages if item.message_type is AgentMessageType.REQUEST
    )
    record = await orchestrator.get_spawn_record(child_session_id)
    assert record is not None
    assert record.status == "running"
    assert seen["execute"] == 1
    assert actor._agent.initialize.await_count == 1
    assert _history_types(bus, child_session_id) == [AgentMessageType.REQUEST]


@pytest.mark.asyncio
async def test_cross_project_bootstrap_failure_does_not_change_the_spawn() -> None:
    async def executor(_request: Any) -> None:
        return None

    orchestrator, bus, sessions, _runs = _orchestrator(executor)
    spawned = await _spawn(orchestrator, sessions, parent_session_id="parent-scope")
    child_session_id = spawned.session.conversation_id
    with pytest.raises(RuntimeV2Error, match="registered spawn relationship") as error:
        await settle_unpinned_child_bootstrap_failure(
            child_session_id=child_session_id,
            child_agent_id="child",
            parent_session_id="parent-scope",
            project_id="other-project",
            request_message_id="message-scope",
            error_message="failure_class=backend code=rejected other project",
        )
    assert error.value.code == "child_bootstrap_scope_rejected"
    record = await orchestrator.get_spawn_record(child_session_id)
    assert record is not None
    assert record.status == "running"
    assert _history_types(bus, child_session_id) == [AgentMessageType.REQUEST]

    with pytest.raises(RuntimeV2Error) as wrong_parent:
        await settle_unpinned_child_bootstrap_failure(
            child_session_id=child_session_id,
            child_agent_id="child",
            parent_session_id="other-parent",
            project_id="project",
            request_message_id="message-scope",
            error_message="failure_class=backend code=rejected other parent",
        )
    assert wrong_parent.value.code == "child_bootstrap_scope_rejected"
    record = await orchestrator.get_spawn_record(child_session_id)
    assert record is not None
    assert record.status == "running"


@pytest.mark.asyncio
async def test_cancelled_spawn_is_not_replaced_by_a_late_bootstrap_failure() -> None:
    async def executor(_request: Any) -> None:
        return None

    orchestrator, bus, sessions, _runs = _orchestrator(executor)
    spawned = await _spawn(orchestrator, sessions, parent_session_id="parent-cancel")
    child_session_id = spawned.session.conversation_id
    await orchestrator.update_spawn_status(
        child_session_id,
        "cancelled",
        conversation_id="parent-cancel",
    )
    await settle_unpinned_child_bootstrap_failure(
        child_session_id=child_session_id,
        child_agent_id="child",
        parent_session_id="parent-cancel",
        project_id="project",
        request_message_id="message-cancel",
        error_message="failure_class=backend code=late late",
    )
    record = await orchestrator.get_spawn_record(child_session_id)
    assert record is not None
    assert record.status == "cancelled"
    assert _history_types(bus, child_session_id) == [AgentMessageType.REQUEST]
    assert await sessions.get_session_for_conversation("parent-cancel", "project") is not None


@pytest.mark.asyncio
async def test_detached_child_failure_leaves_the_parent_session_registered() -> None:
    actor = _actor()

    async def executor(request: Any) -> None:
        await actor._run_chat(
            ProjectChatRequest(
                conversation_id=request.child_session_id,
                message_id="message-detached",
                user_message=request.message,
                user_id="user",
                agent_id=request.child_agent_id,
                parent_session_id=request.parent_session_id,
            )
        )

    orchestrator, bus, sessions, _runs = _orchestrator(executor)
    try:
        spawned = await _spawn(
            orchestrator,
            sessions,
            parent_session_id="parent-detached",
            metadata={"detached": True},
        )
    finally:
        await actor._plugin_admission_v2.close()

    child_session_id = spawned.session.conversation_id
    record = await orchestrator.get_spawn_record(child_session_id)
    assert record is not None
    assert record.status == "failed"
    failure = next(
        item
        for item in bus.messages
        if item.session_id == child_session_id and item.message_type is AgentMessageType.RESPONSE
    )
    assert failure.metadata is not None
    assert failure.metadata["detached"] is True
    assert await sessions.get_session_for_conversation("parent-detached", "project") is not None
    assert await sessions.get_session_for_conversation(child_session_id, "project") is None
