"""A second process can fail a spawn only from shared records.

This is not a Ray cluster. The child is a spawned interpreter. It shares the
local Postgres and Redis with the parent and does not inherit the process-local
spawn owner map. Redis and Postgres here are the project's local services.
"""

from __future__ import annotations

import multiprocessing
import uuid
from typing import Any

import pytest
from sqlalchemy import delete

from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.ports.services.agent_message_bus_port import AgentMessageType
from src.infrastructure.adapters.secondary.messaging.redis_agent_message_bus import (
    RedisAgentMessageBusAdapter,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
    Project,
    Tenant,
    ToolExecutionRecord,
    User,
)
from src.infrastructure.agent.orchestration.bootstrap_failure_settlement import _owners
from src.infrastructure.agent.orchestration.redis_spawn_manager import RedisSpawnManager
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    agent_worker_redis_runtime_factory_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
async def _reset_shared_engine() -> Any:
    """Drop pooled connections so the next test's loop can open its own."""
    from src.infrastructure.adapters.secondary.persistence.database import engine

    await engine.dispose()
    yield
    await engine.dispose()


def _child(operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Run in a fresh interpreter. The parent owner map is not visible here."""
    import asyncio

    from src.infrastructure.agent.orchestration.bootstrap_failure_settlement import (
        _owners as child_owners,
        settle_unpinned_child_bootstrap_failure,
    )
    from src.infrastructure.agent.orchestration.durable_child_bootstrap import (
        settle_durable_child_bootstrap_failure,
    )

    async def _run() -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for operation in operations:
            kind = operation["kind"]
            try:
                if kind == "memory":
                    await settle_unpinned_child_bootstrap_failure(**operation["kwargs"])
                else:
                    await settle_durable_child_bootstrap_failure(**operation["kwargs"])
            except RuntimeV2Error as exc:
                results.append({"ok": False, "code": exc.code})
            else:
                results.append({"ok": True})
        return results

    return {"owners": len(child_owners), "results": asyncio.run(_run())}


async def _seed(suffix: str) -> dict[str, str]:
    user_id = f"user-{suffix}"
    tenant_id = f"tenant-{suffix}"
    project_id = f"project-{suffix}"
    parent_id = f"parent-{suffix}"
    child_id = f"child-{suffix}"
    async with async_session_factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"{suffix}@bootstrap.test",
                hashed_password="not-a-credential",
                is_active=True,
                is_superuser=False,
                profile={},
            )
        )
        session.add(
            Tenant(
                id=tenant_id,
                name=f"tenant-{suffix}",
                slug=f"slug-{suffix}",
                owner_id=user_id,
                plan="free",
                max_projects=1,
                max_users=1,
                max_storage=1,
            )
        )
        session.add(
            Project(
                id=project_id,
                tenant_id=tenant_id,
                name=f"project-{suffix}",
                owner_id=user_id,
                memory_rules={},
                graph_config={},
                sandbox_type="cloud",
                sandbox_config={},
                is_public=False,
            )
        )
        session.add(
            Conversation(
                id=parent_id,
                project_id=project_id,
                tenant_id=tenant_id,
                user_id=user_id,
                title="parent",
                status="active",
                message_count=0,
                current_mode="build",
                participant_agents=[],
            )
        )
        await session.flush()
        session.add(
            Conversation(
                id=child_id,
                project_id=project_id,
                tenant_id=tenant_id,
                user_id=user_id,
                title="child",
                status="active",
                message_count=0,
                current_mode="build",
                participant_agents=[],
                parent_conversation_id=parent_id,
                meta={
                    "spawned_by_agent_id": "parent-agent",
                    "spawned_agent_id": "child-agent",
                    "detached": True,
                },
            )
        )
        await session.flush()
        session.add(
            AgentRunAuthorityModel(
                id=f"run-parent-{suffix}",
                tenant_id=tenant_id,
                project_id=project_id,
                conversation_id=parent_id,
                run_kind="chat",
                idempotency_key=f"parent-{suffix}",
                message_id=f"parent-message-{suffix}",
                request_message="parent",
                status="running",
                revision=1,
                permission_profile="read_only",
                authorization_snapshot={"detached": True},
            )
        )
        session.add(
            AgentRunAuthorityModel(
                id=f"run-child-{suffix}",
                tenant_id=tenant_id,
                project_id=project_id,
                conversation_id=child_id,
                run_kind="chat",
                idempotency_key=f"child-{suffix}",
                message_id=f"child-message-{suffix}",
                request_message="ping",
                status="queued",
                revision=1,
                permission_profile="read_only",
                authorization_snapshot={"detached": True},
            )
        )
        session.add(
            ToolExecutionRecord(
                id=f"tool-child-{suffix}",
                conversation_id=child_id,
                message_id=f"child-message-{suffix}",
                call_id=f"call-{suffix}",
                tool_name="echo",
                tool_input={},
                status="running",
                sequence_number=1,
            )
        )
        session.add(
            ToolExecutionRecord(
                id=f"tool-parent-{suffix}",
                conversation_id=parent_id,
                message_id=f"parent-message-{suffix}",
                call_id=f"parent-call-{suffix}",
                tool_name="echo",
                tool_input={},
                status="running",
                sequence_number=1,
            )
        )
        await session.commit()
    client = await agent_worker_redis_runtime_factory_v2()
    try:
        await RedisSpawnManager(client).register_spawn(
            parent_agent_id="parent-agent",
            child_agent_id="child-agent",
            child_session_id=child_id,
            project_id=project_id,
            mode=SpawnMode.RUN,
            task_summary="ping",
            parent_session_id=parent_id,
        )
        await RedisAgentMessageBusAdapter(client).send_message(
            from_agent_id="parent-agent",
            to_agent_id="child-agent",
            session_id=child_id,
            content="ping",
            message_type=AgentMessageType.REQUEST,
        )
    finally:
        await client.aclose()
    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "parent_id": parent_id,
        "child_id": child_id,
    }


async def _cleanup(ids: dict[str, str]) -> None:
    async with async_session_factory() as session:
        await session.execute(
            delete(ToolExecutionRecord).where(
                ToolExecutionRecord.conversation_id.in_([ids["child_id"], ids["parent_id"]])
            )
        )
        await session.execute(
            delete(AgentRunAuthorityModel).where(
                AgentRunAuthorityModel.conversation_id.in_([ids["child_id"], ids["parent_id"]])
            )
        )
        await session.execute(delete(Conversation).where(Conversation.id == ids["child_id"]))
        await session.execute(delete(Conversation).where(Conversation.id == ids["parent_id"]))
        await session.execute(delete(Project).where(Project.id == ids["project_id"]))
        await session.execute(delete(Tenant).where(Tenant.id == ids["tenant_id"]))
        await session.execute(delete(User).where(User.id == ids["user_id"]))
        await session.commit()
    client = await agent_worker_redis_runtime_factory_v2()
    try:
        await client.delete(
            f"agent:spawn:{ids['child_id']}",
            f"agent:spawn:children:{ids['parent_id']}",
            f"agent:spawn:project:{ids['project_id']}",
            f"agent:messages:{ids['child_id']}",
            f"agent:spawn:{ids['child_id']}:bootstrap-lock",
        )
    finally:
        await client.aclose()


def _kwargs(ids: dict[str, str], *, project_id: str | None = None) -> dict[str, str]:
    return {
        "child_session_id": ids["child_id"],
        "child_agent_id": "child-agent",
        "parent_session_id": ids["parent_id"],
        "project_id": ids["project_id"] if project_id is None else project_id,
        "request_message_id": "message-1",
        "error_message": "failure_class=backend code=generation_descriptor_missing admission failed",
    }


async def _assert_observed(
    live: dict[str, str],
    cancelled_record: Any,
    orphan_record: Any,
    history: list[Any],
    cancelled_history: list[Any],
) -> None:
    assert cancelled_record is not None and cancelled_record.status == "cancelled"
    assert orphan_record is not None and orphan_record.status == "running"
    assert [item.message_type for item in history] == [
        AgentMessageType.REQUEST,
        AgentMessageType.RESPONSE,
    ]
    assert history[1].metadata is not None and history[1].metadata["detached"] is True
    assert "generation_descriptor_missing" in history[1].content
    assert [item.message_type for item in cancelled_history] == [AgentMessageType.REQUEST]
    suffix = live["child_id"].removeprefix("child-")
    async with async_session_factory() as session:
        child_run = await session.get(AgentRunAuthorityModel, f"run-child-{suffix}")
        parent_run = await session.get(AgentRunAuthorityModel, f"run-parent-{suffix}")
        child_tool = await session.get(ToolExecutionRecord, f"tool-child-{suffix}")
        parent_tool = await session.get(ToolExecutionRecord, f"tool-parent-{suffix}")
    assert child_run is not None and child_run.status == "failed"
    assert parent_run is not None and parent_run.status == "running"
    assert child_tool is not None and child_tool.status == "failed"
    assert parent_tool is not None and parent_tool.status == "running"


def _durable(ids: dict[str, str], **overrides: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "durable",
        "kwargs": {**_kwargs(ids), "tenant_id": ids["tenant_id"]},
    }
    payload["kwargs"].update(overrides)
    return payload


@pytest.mark.asyncio
async def test_other_process_settles_only_the_registered_spawn() -> None:
    assert len(_owners) == 0
    live = await _seed(uuid.uuid4().hex[:12])
    cancelled = await _seed(uuid.uuid4().hex[:12])
    orphan = await _seed(uuid.uuid4().hex[:12])
    client = await agent_worker_redis_runtime_factory_v2()
    try:
        await RedisSpawnManager(client).update_status(cancelled["child_id"], "cancelled")
        async with async_session_factory() as session:
            parent = await session.get(Conversation, orphan["parent_id"])
            assert parent is not None
            parent.status = "archived"
            await session.commit()
    finally:
        await client.aclose()

    context = multiprocessing.get_context("spawn")
    try:
        with context.Pool(1) as pool:
            outcome = pool.apply(
                _child,
                (
                    [
                        {
                            "kind": "memory",
                            "kwargs": {
                                "child_session_id": live["child_id"],
                                "child_agent_id": "child-agent",
                                "parent_session_id": live["parent_id"],
                                "project_id": live["project_id"],
                                "request_message_id": "message-1",
                                "error_message": _kwargs(live)["error_message"],
                            },
                        },
                        _durable(live, project_id="other-project"),
                        _durable(orphan),
                        _durable(cancelled),
                        _durable(live),
                        _durable(live),
                    ],
                ),
            )
        assert outcome["owners"] == 0
        assert outcome["results"] == [
            {"ok": False, "code": "child_bootstrap_owner_missing"},
            {"ok": False, "code": "child_bootstrap_scope_rejected"},
            {"ok": False, "code": "child_bootstrap_parent_missing"},
            {"ok": True},
            {"ok": True},
            {"ok": True},
        ]

        client = await agent_worker_redis_runtime_factory_v2()
        try:
            live_record = await RedisSpawnManager(client).get_record(live["child_id"])
            cancelled_record = await RedisSpawnManager(client).get_record(cancelled["child_id"])
            orphan_record = await RedisSpawnManager(client).get_record(orphan["child_id"])
            history = await RedisAgentMessageBusAdapter(client).get_message_history(
                live["child_id"]
            )
            cancelled_history = await RedisAgentMessageBusAdapter(client).get_message_history(
                cancelled["child_id"]
            )
        finally:
            await client.aclose()
        await _assert_observed(live, cancelled_record, orphan_record, history, cancelled_history)
        assert live_record is not None and live_record.status == "failed"
    finally:
        for ids in (live, cancelled, orphan):
            await _cleanup(ids)


def _settle_once(kwargs: dict[str, str]) -> dict[str, Any]:
    """One fresh interpreter, so two settlements can overlap."""
    import asyncio

    from src.infrastructure.agent.orchestration.durable_child_bootstrap import (
        settle_durable_child_bootstrap_failure,
    )
    from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

    async def _run() -> dict[str, Any]:
        try:
            await settle_durable_child_bootstrap_failure(**kwargs)
        except RuntimeV2Error as exc:
            return {"ok": False, "code": exc.code}
        return {"ok": True}

    return asyncio.run(_run())


async def _reject(kwargs: dict[str, str]) -> str:
    from src.infrastructure.agent.orchestration.durable_child_bootstrap import (
        settle_durable_child_bootstrap_failure,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await settle_durable_child_bootstrap_failure(**kwargs)
    return error.value.code


@pytest.mark.asyncio
async def test_concurrent_settlement_keeps_one_response_and_rejects_bad_identity() -> None:
    ids = await _seed(uuid.uuid4().hex[:12])
    try:
        assert await _reject(
            {**_kwargs(ids), "tenant_id": ids["tenant_id"], "child_session_id": "missing"}
        ) == "child_bootstrap_record_missing"
        assert await _reject({**_kwargs(ids), "tenant_id": "other-tenant"}) == (
            "child_bootstrap_scope_rejected"
        )
        assert await _reject(
            {**_kwargs(ids), "tenant_id": ids["tenant_id"], "child_agent_id": "other-agent"}
        ) == "child_bootstrap_scope_rejected"
        client = await agent_worker_redis_runtime_factory_v2()
        try:
            await RedisSpawnManager(client).register_spawn(
                parent_agent_id="parent-agent",
                child_agent_id="imposter",
                child_session_id=ids["child_id"],
                project_id=ids["project_id"],
                mode=SpawnMode.RUN,
                parent_session_id=ids["parent_id"],
            )
        finally:
            await client.aclose()
        assert await _reject({**_kwargs(ids), "tenant_id": ids["tenant_id"]}) == (
            "child_bootstrap_scope_rejected"
        )
        client = await agent_worker_redis_runtime_factory_v2()
        try:
            await RedisSpawnManager(client).register_spawn(
                parent_agent_id="parent-agent",
                child_agent_id="child-agent",
                child_session_id=ids["child_id"],
                project_id=ids["project_id"],
                mode=SpawnMode.RUN,
                parent_session_id=ids["parent_id"],
            )
        finally:
            await client.aclose()
        payload = {**_kwargs(ids), "tenant_id": ids["tenant_id"]}
        with multiprocessing.get_context("spawn").Pool(2) as pool:
            results = pool.map(_settle_once, [payload, payload])
        assert any(item["ok"] for item in results)
        from src.infrastructure.agent.orchestration.durable_child_bootstrap import (
            settle_durable_child_bootstrap_failure,
        )

        await settle_durable_child_bootstrap_failure(**payload)
        client = await agent_worker_redis_runtime_factory_v2()
        try:
            history = await RedisAgentMessageBusAdapter(client).get_message_history(
                ids["child_id"]
            )
            record = await RedisSpawnManager(client).get_record(ids["child_id"])
        finally:
            await client.aclose()
        assert record is not None and record.status == "failed"
        assert [item.message_type for item in history].count(AgentMessageType.RESPONSE) == 1
    finally:
        await _cleanup(ids)


class _FailingSpawnRedis:
    """Accepts the request write and then fails the spawn-record pipeline."""

    def pipeline(self) -> _FailingSpawnRedis:
        return self

    def setex(self, *_args: object, **_kwargs: object) -> _FailingSpawnRedis:
        return self

    def sadd(self, *_args: object, **_kwargs: object) -> _FailingSpawnRedis:
        return self

    async def execute(self) -> None:
        raise ConnectionError("shared spawn write failed")

    async def get(self, _key: str) -> None:
        return None

    async def smembers(self, _key: str) -> set[str]:
        return set()

    async def set(self, *_args: object, **_kwargs: object) -> bool:
        return True

    async def delete(self, *_args: object) -> int:
        return 1

    async def xadd(self, *_args: object, **_kwargs: object) -> str:
        return "1-0"


@pytest.mark.asyncio
async def test_failed_shared_registration_does_not_start_the_child() -> None:
    from unittest.mock import AsyncMock, Mock

    from src.domain.model.agent.agent_role import AgentRole
    from src.infrastructure.agent.orchestration.orchestrator import AgentOrchestrator
    from src.infrastructure.agent.orchestration.session_registry import AgentSessionRegistry
    from src.infrastructure.agent.orchestration.spawn_manager import SpawnManager

    started = False

    async def executor(_request: object) -> None:
        nonlocal started
        started = True

    sessions = AgentSessionRegistry()
    agents = Mock()

    def _agent(agent_id: str, **kwargs: object) -> Mock:
        agent = Mock()
        agent.id = agent_id
        agent.name = agent_id
        agent.display_name = agent_id
        agent.tenant_id = kwargs.get("tenant_id") or "tenant"
        agent.project_id = kwargs.get("project_id") or "project"
        agent.enabled = True
        agent.discoverable = True
        agent.max_spawn_depth = 3
        agent.role = AgentRole.ORCHESTRATOR
        return agent

    agents.get_by_id = AsyncMock(side_effect=_agent)
    agents.get_by_name = AsyncMock(return_value=None)
    orchestrator = AgentOrchestrator(
        agents,
        sessions,
        SpawnManager(session_registry=sessions),
        RedisAgentMessageBusAdapter(_FailingSpawnRedis()),  # type: ignore[arg-type]
        spawn_executor=executor,
    )
    await sessions.register(agent_id="parent", conversation_id="parent", project_id="project")
    with pytest.raises(RuntimeV2Error, match="shared spawn relationship"):
        await orchestrator.spawn_agent(
            parent_agent_id="parent",
            target_agent_id="child",
            message="ping",
            mode=SpawnMode.RUN,
            parent_session_id="parent",
            project_id="project",
            tenant_id="tenant",
            user_id="user",
        )
    assert started is False
    failed = await orchestrator._spawn_manager.find_children("parent")
    assert failed and failed[0].status == "failed"
