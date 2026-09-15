"""Actual migration and independently connected workers, in an isolated test schema."""

import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from src.configuration.config import get_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    Tenant,
    User,
)
from src.infrastructure.agent.subagent.async_run_registry_v2 import (
    AsyncSubAgentRunRegistryV2,
    registry_call_v2,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.delegate_subagent import (
    DelegateToolRuntime,
    _register_single_run,
)

pytestmark = pytest.mark.integration


def _migrate(connection, direction="upgrade"):
    path = Path("alembic/versions/2d6a9c18e4b7_add_durable_scoped_subagent_run_.py")
    spec = importlib.util.spec_from_file_location("subagent_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, direction)()


@pytest.fixture
async def postgres_registry():
    # Deliberately never print the application's connection URL.
    url = make_url(get_settings().postgres_url).set(drivername="postgresql+asyncpg")
    schema = "subagent_test_" + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    async with admin.begin() as connection:
        await connection.execute(CreateSchema(schema))
    engine = create_async_engine(
        url, poolclass=NullPool, connect_args={"server_settings": {"search_path": schema}}
    )
    try:
        async with engine.begin() as connection:
            for model in (User, Tenant, Project, Conversation):
                await connection.run_sync(model.__table__.create)
            await connection.run_sync(_migrate)
            await connection.run_sync(_migrate_owner)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db, db.begin():
            for model, values in (
                (
                    User,
                    {"id": "user", "email": "fixture@example.invalid", "hashed_password": "unused"},
                ),
                (Tenant, {"id": "tenant", "name": "test", "slug": "test", "owner_id": "user"}),
                (
                    Project,
                    {"id": "project", "tenant_id": "tenant", "name": "test", "owner_id": "user"},
                ),
                (
                    Conversation,
                    {
                        "id": "conversation",
                        "tenant_id": "tenant",
                        "project_id": "project",
                        "user_id": "user",
                        "title": "fixture",
                    },
                ),
            ):
                await db.execute(model.__table__.insert().values(**values))
        scope = ScopeV2(
            kind=ScopeKindV2.SESSION,
            tenant_id="tenant",
            project_id="project",
            session_id="conversation",
        )
        yield engine, sessions, scope
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await admin.dispose()


async def test_competing_workers_cannot_exceed_delegate_capacity(postgres_registry):
    _, sessions, scope = postgres_registry

    async def reserve():
        registry = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
        runtime = DelegateToolRuntime(
            execute_callback=AsyncMock(),
            run_registry=registry,
            conversation_id=scope.session_id,
            subagent_names=("worker",),
            subagent_descriptions={},
            delegation_depth=0,
            max_active_runs=1,
            max_concurrency=1,
        )
        ctx = ToolContext(
            session_id="s",
            message_id="m",
            call_id="c",
            agent_name="parent",
            conversation_id=scope.session_id,
        )
        return await _register_single_run(runtime, ctx, "worker", "task")

    outcomes = await asyncio.gather(*(reserve() for _ in range(4)))
    assert sum(not value.startswith("Error:") for value in outcomes) == 1
    registry = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
    assert await registry_call_v2(registry, "count_active_runs", scope.session_id) == 1


async def test_database_lock_wait_does_not_block_event_loop(postgres_registry):
    _, sessions, scope = postgres_registry
    async with sessions() as blocker, blocker.begin():
        await blocker.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 0x4D535352})
        registry = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
        task = asyncio.create_task(
            registry_call_v2(registry, "create_run", scope.session_id, "worker", "task")
        )
        await asyncio.sleep(0.1)
        assert not task.done()
    run = await asyncio.wait_for(task, timeout=2)
    recovered = await registry_call_v2(
        AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope),
        "get_run",
        scope.session_id,
        run.run_id,
    )
    assert recovered.run_id == run.run_id


async def test_actual_migration_preserves_all_legacy_states_and_history(postgres_registry):
    from sqlalchemy import Column, DateTime, Integer, Text

    from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
    from src.infrastructure.agent.subagent.run_repository import _serialize_snapshot

    engine, sessions, scope = postgres_registry
    memory = SubAgentRunRegistry(recover_inflight_on_boot=False)
    runs = []
    for terminal in (None, "mark_completed", "mark_failed", "mark_cancelled", "mark_timed_out"):
        run = memory.create_run(scope.session_id, "worker", "legacy task")
        memory.mark_running(scope.session_id, run.run_id)
        memory.attach_metadata(
            scope.session_id,
            run.run_id,
            {"announce_events": [{"type": "observe", "call_id": "retained"}]},
        )
        if terminal:
            args = (
                {"summary": "done"}
                if terminal == "mark_completed"
                else {"error": "error"}
                if terminal == "mark_failed"
                else {"reason": "terminal"}
            )
            getattr(memory, terminal)(scope.session_id, run.run_id, **args)
        runs.append(memory.get_run(scope.session_id, run.run_id))
    memory.create_run("unresolved-legacy-conversation", "worker", "preserve legacy")
    original = _serialize_snapshot(memory._runs_by_conversation)

    def legacy_schema(connection):
        _migrate(connection, "downgrade")
        with Operations.context(MigrationContext.configure(connection)) as operations:
            operations.create_table(
                "subagent_run_snapshots",
                Column("id", Integer, primary_key=True),
                Column("payload", Text, nullable=False),
                Column("updated_at", DateTime(timezone=True), nullable=False),
            )

    async with engine.begin() as connection:
        await connection.run_sync(legacy_schema)
        await connection.execute(
            text("INSERT INTO subagent_run_snapshots VALUES (1, :payload, now())"),
            {"payload": original},
        )
        await connection.run_sync(_migrate)
    registry = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
    restored = await registry_call_v2(registry, "list_runs", scope.session_id)
    assert {r.run_id: r.to_event_data() for r in restored} == {
        r.run_id: r.to_event_data() for r in runs
    }
    async with engine.begin() as connection:
        assert (
            await connection.scalar(text("SELECT payload FROM subagent_run_snapshots WHERE id=1"))
        ) == original
        assert (
            await connection.scalar(text("SELECT count(*) FROM subagent_run_snapshots_v2"))
        ) == 1
        await connection.run_sync(lambda connection: _migrate(connection, "downgrade"))
        assert (
            await connection.scalar(text("SELECT payload FROM subagent_run_snapshots WHERE id=1"))
        ) == original


async def test_concurrent_announce_appends_survive_new_worker(postgres_registry):
    from src.infrastructure.agent.tools.subagent_sessions import _record_announce_event

    _, sessions, scope = postgres_registry

    def worker():
        return AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)

    run = await registry_call_v2(worker(), "create_run", scope.session_id, "worker", "task")
    await asyncio.gather(
        *(
            _record_announce_event(
                run_registry=worker(),
                conversation_id=scope.session_id,
                run_id=run.run_id,
                event_type="observe",
                payload={"sequence": i},
            )
            for i in range(10)
        )
    )
    restored = await registry_call_v2(worker(), "get_run", scope.session_id, run.run_id)
    assert sorted(event["sequence"] for event in restored.metadata["announce_events"]) == list(
        range(10)
    )


async def test_competing_terminal_cas_commits_exactly_one_transition(postgres_registry):
    from src.domain.model.agent.subagent_run import SubAgentRunStatus

    _, sessions, scope = postgres_registry
    first = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
    second = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
    run = await registry_call_v2(first, "create_run", scope.session_id, "worker", "task")
    await registry_call_v2(first, "mark_running", scope.session_id, run.run_id)
    results = await asyncio.gather(
        registry_call_v2(
            first,
            "mark_completed",
            scope.session_id,
            run.run_id,
            summary="done",
            expected_statuses=[SubAgentRunStatus.RUNNING],
        ),
        registry_call_v2(
            second,
            "mark_cancelled",
            scope.session_id,
            run.run_id,
            reason="cancel",
            expected_statuses=[SubAgentRunStatus.RUNNING],
        ),
    )
    assert sum(result is not None for result in results) == 1
    restored = await registry_call_v2(second, "get_run", scope.session_id, run.run_id)
    assert restored.to_event_data() == next(
        result.to_event_data() for result in results if result is not None
    )


async def test_production_tool_history_recovers_in_a_new_process(postgres_registry):
    import json
    import sys
    from dataclasses import asdict

    from src.infrastructure.agent.tools.subagent_sessions import make_session_tool_defs

    engine, sessions, scope = postgres_registry
    registry = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)

    async def completed_child(_name, _task, run_id, **_options):
        async with registry.own_execution(scope.session_id, run_id):
            await registry_call_v2(
                registry,
                "mark_completed",
                scope.session_id,
                run_id,
                summary="PERSISTED_CHILD_RESULT",
                tokens_used=17,
            )
            return run_id

    tools = make_session_tool_defs(
        run_registry=registry,
        conversation_id=scope.session_id,
        requester_session_key="parent",
        visibility_default="self",
        observability_stats_provider=None,
        subagent_names=["worker"],
        subagent_descriptions={"worker": "test"},
        spawn_callback=completed_child,
        cancel_callback=AsyncMock(return_value=True),
        max_active_runs=1,
        max_active_runs_per_lineage=1,
        max_children_per_requester=1,
        delegation_depth=0,
        max_delegation_depth=2,
    )
    by_name = {tool.name: tool for tool in tools}
    ctx = ToolContext(
        session_id="parent",
        message_id="message",
        call_id="call",
        agent_name="parent",
        conversation_id=scope.session_id,
    )
    spawned = await by_name["sessions_spawn"]._tool_instance.execute(
        ctx, subagent_name="worker", task="test task"
    )
    assert not spawned.is_error
    history = await by_name["sessions_history"]._tool_instance.execute(ctx)
    expected = json.loads(history.output)
    assert expected["count"] == 1
    assert expected["runs"][0]["status"] == "completed"
    async with engine.connect() as connection:
        schema = await connection.scalar(text("SELECT current_schema()"))
    script = """
import asyncio, json, sys
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from src.configuration.config import get_settings
from src.domain.model.plugins.generated_v2 import ScopeV2, ScopeKindV2
from src.infrastructure.agent.subagent.async_run_registry_v2 import AsyncSubAgentRunRegistryV2, registry_call_v2
async def main():
    request = json.loads(sys.stdin.read())
    request["scope"]["kind"] = ScopeKindV2(request["scope"]["kind"])
    scope = ScopeV2(**request["scope"])
    engine = create_async_engine(make_url(get_settings().postgres_url).set(drivername="postgresql+asyncpg"), poolclass=NullPool, connect_args={"server_settings":{"search_path":request["schema"]}})
    try:
        registry = AsyncSubAgentRunRegistryV2(async_sessionmaker(engine, expire_on_commit=False), scope_provider=lambda:scope)
        runs = await registry_call_v2(registry,"list_runs_for_requester",scope.session_id,"parent",visibility="self")
        print(json.dumps([run.to_event_data() for run in runs]))
    finally:
        await engine.dispose()
asyncio.run(main())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await asyncio.wait_for(
        process.communicate(json.dumps({"scope": asdict(scope), "schema": schema}).encode()),
        timeout=15,
    )
    assert process.returncode == 0
    assert json.loads(stdout) == expected["runs"]


def _migrate_owner(connection):
    path = Path("alembic/versions/71e6b3a29c84_add_subagent_execution_owner_leases.py")
    spec = importlib.util.spec_from_file_location("subagent_owner_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()
