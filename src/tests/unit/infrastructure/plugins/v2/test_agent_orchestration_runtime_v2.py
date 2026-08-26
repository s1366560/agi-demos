"""Tests for the generation-owned Agent orchestration runtime."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.agent.orchestration.orchestrator import AgentOrchestrator
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.plugins.v2.agent_orchestration_runtime import (
    AgentOrchestrationRuntimeV2,
    AgentOrchestratorResourceV2,
    create_agent_orchestrator_resource_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


async def test_runtime_reuses_owner_binding_and_disposes_resources_lifo() -> None:
    run_registry = SubAgentRunRegistry()
    owners = (object(), object())
    orchestrators = (
        MagicMock(spec=AgentOrchestrator),
        MagicMock(spec=AgentOrchestrator),
    )
    disposed: list[int] = []
    factory_calls: list[SubAgentRunRegistry] = []

    async def factory(
        registry: SubAgentRunRegistry,
        _spawn_executor: object,
        _session_turn_executor: object,
    ) -> AgentOrchestratorResourceV2:
        index = len(factory_calls)
        factory_calls.append(registry)

        async def dispose() -> None:
            disposed.append(index)

        return AgentOrchestratorResourceV2(
            orchestrator=orchestrators[index],
            dispose=dispose,
        )

    runtime = AgentOrchestrationRuntimeV2(
        run_registry=run_registry,
        factory=factory,
    )
    spawn_executor = MagicMock()
    session_turn_executor = MagicMock()

    first = await runtime.bind(
        owner=owners[0],
        spawn_executor=spawn_executor,
        session_turn_executor=session_turn_executor,
    )
    repeated = await runtime.bind(
        owner=owners[0],
        spawn_executor=spawn_executor,
        session_turn_executor=session_turn_executor,
    )
    second = await runtime.bind(
        owner=owners[1],
        spawn_executor=spawn_executor,
        session_turn_executor=session_turn_executor,
    )

    assert first is orchestrators[0]
    assert repeated is orchestrators[0]
    assert second is orchestrators[1]
    assert factory_calls == [run_registry, run_registry]

    await runtime.close()
    await runtime.close()

    assert disposed == [1, 0]
    run_registry.close()


async def test_runtime_rejects_new_binding_after_generation_disposal() -> None:
    run_registry = SubAgentRunRegistry()
    runtime = AgentOrchestrationRuntimeV2(
        run_registry=run_registry,
        factory=MagicMock(),
    )
    await runtime.close()

    with pytest.raises(RuntimeV2Error) as error:
        await runtime.bind(
            owner=object(),
            spawn_executor=MagicMock(),
            session_turn_executor=MagicMock(),
        )

    assert error.value.code == "disposed_agent_orchestration_runtime"
    run_registry.close()


async def test_runtime_continues_lifo_cleanup_after_disposer_failure() -> None:
    run_registry = SubAgentRunRegistry()
    disposed: list[int] = []

    async def factory(
        _registry: SubAgentRunRegistry,
        _spawn_executor: object,
        _session_turn_executor: object,
    ) -> AgentOrchestratorResourceV2:
        index = len(disposed_resources)

        async def dispose() -> None:
            disposed.append(index)
            if index == 1:
                raise RuntimeError("second disposer failed")

        resource = AgentOrchestratorResourceV2(
            orchestrator=MagicMock(spec=AgentOrchestrator),
            dispose=dispose,
        )
        disposed_resources.append(resource)
        return resource

    disposed_resources: list[AgentOrchestratorResourceV2] = []
    runtime = AgentOrchestrationRuntimeV2(
        run_registry=run_registry,
        factory=factory,
    )
    for owner in (object(), object()):
        await runtime.bind(
            owner=owner,
            spawn_executor=MagicMock(),
            session_turn_executor=MagicMock(),
        )

    with pytest.raises(RuntimeV2Error) as error:
        await runtime.close()

    assert error.value.code == "agent_orchestration_dispose_failed"
    assert disposed == [1, 0]
    run_registry.close()


async def test_default_factory_closes_db_session_when_redis_setup_fails() -> None:
    run_registry = SubAgentRunRegistry()
    db_session = MagicMock()
    db_session.close = AsyncMock()

    with (
        patch(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            return_value=db_session,
        ),
        patch(
            "src.infrastructure.agent.state.agent_worker_state.get_redis_client",
            new=AsyncMock(side_effect=RuntimeError("redis unavailable")),
        ),
        pytest.raises(RuntimeError, match="redis unavailable"),
    ):
        await create_agent_orchestrator_resource_v2(
            run_registry,
            MagicMock(),
            MagicMock(),
        )

    db_session.close.assert_awaited_once_with()
    run_registry.close()
