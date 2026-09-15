"""Real PostgreSQL owner fencing, cancellation races, and no automatic replay."""

import asyncio
from datetime import timedelta

import pytest

from src.infrastructure.adapters.secondary.persistence.subagent_owner_model_v2 import (
    SubAgentOwnerLeaseV2,
)
from src.infrastructure.agent.subagent.async_run_registry_v2 import (
    AsyncSubAgentRunRegistryV2,
    registry_call_v2,
)
from src.infrastructure.agent.subagent.owner_lease_v2 import (
    SubAgentExecutionOwnerV2,
    fence_subagent_owner_v2,
)
from src.infrastructure.agent.subagent.run_reservation_v2 import reserve_session_run_v2
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error
from src.tests.integration.agent import test_subagent_registry_postgres_v2 as postgres_tests

postgres_registry = postgres_tests.postgres_registry
pytestmark = pytest.mark.integration


async def _reserved(setup):
    _, sessions, scope = setup
    registry = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
    run = await reserve_session_run_v2(
        registry,
        conversation_id=scope.session_id,
        subagent_name="worker",
        task="do not replay",
        metadata={},
        requester_session_key="parent",
        max_active_runs=1,
        max_children_per_requester=1,
        max_active_runs_per_lineage=1,
    )
    assert not isinstance(run, str)
    return registry, run


async def test_reservation_and_owner_claim_are_durable_and_exclusive(postgres_registry):
    _, sessions, scope = postgres_registry
    registry, run = await _reserved(postgres_registry)
    async with sessions() as db:
        lease = await db.get(SubAgentOwnerLeaseV2, (scope.session_id, run.run_id))
        assert lease is not None
        assert lease.state == "reserved"
    async with SubAgentExecutionOwnerV2(sessions, scope.session_id, run.run_id):
        await fence_subagent_owner_v2()
        with pytest.raises(RuntimeV2Error, match="already owned"):
            async with SubAgentExecutionOwnerV2(sessions, scope.session_id, run.run_id):
                pytest.fail("a second owner acquired the same run")
        await registry_call_v2(
            registry, "mark_completed", scope.session_id, run.run_id, summary="done"
        )
    async with sessions() as db:
        lease = await db.get(SubAgentOwnerLeaseV2, (scope.session_id, run.run_id))
        assert lease.state == "closed"


def _processor(run_id, execute, *, pipeline=False, permission_manager=None):
    from unittest.mock import MagicMock

    from src.infrastructure.agent.processor.processor import (
        ProcessorConfig,
        SessionProcessor,
        ToolDefinition,
    )
    from src.infrastructure.agent.tools.hooks import ToolHookRegistry
    from src.infrastructure.agent.tools.pipeline import ToolPipeline
    from src.infrastructure.agent.tools.truncation import OutputTruncator

    definition = ToolDefinition(
        name="side_effect",
        description="test",
        parameters={},
        execute=execute,
        permission="write" if permission_manager else None,
    )
    detector = MagicMock()
    detector.should_intervene.return_value = False
    processor = SessionProcessor(
        config=ProcessorConfig(model="test", run_id=run_id, subagent_owner_required=True),
        tools=[definition],
        tool_pipeline=ToolPipeline(
            permission_manager=permission_manager or MagicMock(),
            doom_detector=detector,
            truncator=OutputTruncator(),
            hooks=ToolHookRegistry(),
        )
        if pipeline
        else None,
    )
    return processor, definition


async def _invoke(processor, definition, *, pipeline=False):
    from src.infrastructure.agent.core.message import ToolPart, ToolState

    part = ToolPart(call_id="call", tool=definition.name, status=ToolState.RUNNING)
    stream = (
        processor._execute_tool_via_pipeline(
            "session", "call", definition.name, {}, part, definition
        )
        if pipeline
        else processor._invoke_and_emit_observe(
            definition.name, {}, part, definition, "call", "session"
        )
    )
    return [event async for event in stream]


@pytest.mark.parametrize("pipeline", [False, True])
async def test_revoked_owner_cannot_write_or_execute_again_and_recovery_never_replays(
    postgres_registry, pipeline
):
    from contextvars import Context

    from src.infrastructure.agent.subagent.owner_lease_v2 import database_now_v2
    from src.infrastructure.agent.tools.result import ToolResult

    _, sessions, scope = postgres_registry
    registry, run = await _reserved(postgres_registry)
    calls = []

    async def side_effect(**_kwargs):
        calls.append("committed-side-effect")
        return ToolResult(output="done")

    async with SubAgentExecutionOwnerV2(sessions, scope.session_id, run.run_id):
        processor, definition = _processor(run.run_id, side_effect, pipeline=pipeline)
        await _invoke(processor, definition, pipeline=pipeline)
        assert len(calls) == 1
        async with sessions() as db, db.begin():
            lease = await db.get(SubAgentOwnerLeaseV2, (scope.session_id, run.run_id))
            lease.expires_at = await database_now_v2(db) - timedelta(seconds=1)
        with pytest.raises(RuntimeV2Error, match="no longer valid"):
            await registry_call_v2(
                registry, "mark_completed", scope.session_id, run.run_id, summary="stale success"
            )
        if pipeline:
            await _invoke(processor, definition, pipeline=True)
        else:
            with pytest.raises(RuntimeV2Error, match="no longer valid"):
                await _invoke(processor, definition)
        assert calls == ["committed-side-effect"]

        async def recover():
            fresh = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
            return await registry_call_v2(fresh, "get_run", scope.session_id, run.run_id)

        restored = await asyncio.create_task(recover(), context=Context())
        assert restored.status.value == "failed"
        assert restored.metadata["recovery_status"] == "interrupted"
        assert restored.metadata["prior_tool_outcome"] == "unknown"
        assert restored.metadata["automatic_replay"] is False
        again = await asyncio.create_task(recover(), context=Context())
        assert again.to_event_data() == restored.to_event_data()
        with pytest.raises(RuntimeV2Error, match="already owned"):
            async with SubAgentExecutionOwnerV2(sessions, scope.session_id, run.run_id):
                pytest.fail("revoked work was replayed")
    assert calls == ["committed-side-effect"]


async def test_cancel_accepted_during_permission_wait_prevents_tool_dispatch(postgres_registry):
    from types import SimpleNamespace

    from src.infrastructure.agent.tools.executor import PermissionAction
    from src.infrastructure.agent.tools.result import ToolResult

    _, sessions, scope = postgres_registry
    registry, run = await _reserved(postgres_registry)
    calls = []

    class Permissions:
        def evaluate(self, *_args):
            return SimpleNamespace(action=PermissionAction.ASK)

        async def ask(self, **_kwargs):
            await registry_call_v2(
                registry,
                "attach_metadata",
                scope.session_id,
                run.run_id,
                {"cancel_requested": True},
            )
            return "allow"

    async def side_effect(**_kwargs):
        calls.append("must-not-run")
        return ToolResult(output="done")

    async with SubAgentExecutionOwnerV2(sessions, scope.session_id, run.run_id):
        processor, definition = _processor(
            run.run_id, side_effect, pipeline=True, permission_manager=Permissions()
        )
        with pytest.raises(asyncio.CancelledError):
            await _invoke(processor, definition, pipeline=True)
        assert calls == []
        await registry_call_v2(
            registry, "mark_cancelled", scope.session_id, run.run_id, reason="owner unwound"
        )


async def test_child_identity_without_owner_is_denied_before_tool_dispatch():
    async def unreachable(**_kwargs):
        pytest.fail("child without owner invoked a tool")

    processor, definition = _processor("known-child", unreachable)
    with pytest.raises(RuntimeV2Error, match="own owner lease"):
        await _invoke(processor, definition)


async def test_actual_v2_detached_runner_receives_remote_request_and_acknowledges(  # noqa: PLR0915
    postgres_registry, monkeypatch
):
    from types import MappingProxyType

    from src.domain.model.agent.subagent import SubAgent
    from src.infrastructure.agent.core.detached_subagent_task_supervisor import (
        DetachedSubAgentTaskSupervisor,
    )
    from src.infrastructure.agent.core.subagent_tool_set_v2 import SubAgentToolSetBindingV2
    from src.infrastructure.plugins.v2.boundary import (
        clear_process_generation_host_v2,
        install_process_generation_host_v2,
        pin_agent_turn_operation_v2,
    )
    from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
    from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
    from src.infrastructure.plugins.v2.tool_set import ToolSetV2
    from src.tests.integration.agent.test_subagent_owner_recovery_v2 import _context, _tools
    from src.tests.unit.infrastructure.agent.core import (
        test_subagent_registry_authority_v2 as setup,
    )

    _, sessions, scope = postgres_registry
    registry, run = await _reserved(postgres_registry)
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(subagent_run_registry_factory=lambda _config: registry)
    )
    publication = await host.bootstrap(
        profile_path=setup._PROFILE_PATH,
        manifest_paths=(setup._MANIFEST_PATH,),
        generation=391,
        version=391,
        nonce="owner-lease-runner-test",
        profile_projector=setup._registry_authority_profile,
    )
    assert publication.accepted
    install_process_generation_host_v2(host)
    lifecycle_events = []
    agent = setup._agent(session_factory=sessions, subagent_lifecycle_hook=lifecycle_events.append)
    entered = asyncio.Event()
    subagent = SubAgent.create(
        tenant_id=scope.tenant_id,
        name="worker",
        display_name="Worker",
        system_prompt="test",
        trigger_description="test",
        trigger_keywords=[],
    )

    async def execute_subagent(**kwargs):
        assert kwargs["run_id"] == run.run_id
        await fence_subagent_owner_v2(child_run_id=run.run_id)
        entered.set()
        await asyncio.Event().wait()
        yield {}  # keeps the real runner's AsyncIterator protocol

    monkeypatch.setattr(agent._session_runner, "execute_subagent", execute_subagent)
    task = None
    try:
        async with pin_agent_turn_operation_v2(
            operation_id="parent-owner-test",
            tenant_id=scope.tenant_id,
            project_id=scope.project_id,
            session_id=scope.session_id,
        ) as operation:
            inherited = SubAgentToolSetBindingV2(operation=operation).bind(
                ToolSetV2(tools=MappingProxyType({}), definitions=())
            )
            await agent._launch_subagent_session(
                run_id=run.run_id,
                subagent=subagent,
                available_subagents=[subagent],
                user_message="test",
                conversation_context=[],
                conversation_id=scope.session_id,
                project_id=scope.project_id,
                tenant_id=scope.tenant_id,
                inherited_tool_set=inherited,
            )
            task = agent._subagent_session_tasks[run.run_id]
            await asyncio.wait_for(entered.wait(), timeout=2)
        remote = DetachedSubAgentTaskSupervisor()
        tools = _tools(
            AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope), scope, remote
        )
        requested = await tools["subagents"].execute(
            _context(scope), action="kill", run_id=run.run_id
        )
        assert not requested.is_error
        outcomes = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=5)
        assert all(isinstance(outcome, asyncio.CancelledError) for outcome in outcomes), [
            (type(outcome).__name__, getattr(outcome, "code", "")) for outcome in outcomes
        ]
        restored = await registry_call_v2(registry, "get_run", scope.session_id, run.run_id)
        assert task.done()
        assert restored.status.value == "cancelled"
        assert restored.metadata["announce_status"] == "delivered"
        killed = next(
            event["data"] for event in lifecycle_events if event.get("type") == "subagent_killed"
        )
        assert killed["run_id"] == run.run_id
        assert killed["conversation_id"] == scope.session_id
        assert killed["subagent_id"] == subagent.id
        async with sessions() as db:
            lease = await db.get(SubAgentOwnerLeaseV2, (scope.session_id, run.run_id))
            assert lease.state == "closed"
    finally:
        await agent._session_runner.deps.detached_subagent_task_supervisor.shutdown()
        clear_process_generation_host_v2(host)
        await host.close()


async def test_process_crash_recovers_only_after_its_formal_lease_is_revoked(postgres_registry):
    import json
    import sys
    from dataclasses import asdict

    from sqlalchemy import text

    engine, sessions, scope = postgres_registry
    registry, run = await _reserved(postgres_registry)
    async with engine.connect() as connection:
        schema = await connection.scalar(text("SELECT current_schema()"))
    script = """
import asyncio, json, sys
from datetime import timedelta
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from src.configuration.config import get_settings
from src.infrastructure.agent.subagent.owner_lease_v2 import SubAgentExecutionOwnerV2, fence_subagent_owner_v2
async def main():
    request=json.loads(sys.stdin.readline())
    engine=create_async_engine(make_url(get_settings().postgres_url).set(drivername="postgresql+asyncpg"), poolclass=NullPool, connect_args={"server_settings":{"search_path":request["schema"]}})
    sessions=async_sessionmaker(engine, expire_on_commit=False)
    async with SubAgentExecutionOwnerV2(sessions, request["scope"]["session_id"], request["run_id"], lease_duration=timedelta(seconds=0.6)):
        await fence_subagent_owner_v2(child_run_id=request["run_id"])
        print("ready", flush=True)
        await asyncio.Event().wait()
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
    try:
        process.stdin.write(
            (
                json.dumps({"schema": schema, "scope": asdict(scope), "run_id": run.run_id}) + "\n"
            ).encode()
        )
        await process.stdin.drain()
        assert await asyncio.wait_for(process.stdout.readline(), timeout=10) == b"ready\n"
        process.kill()
        await process.wait()
        # A missing local process alone is not a recovery verdict.
        still_leased = await registry_call_v2(registry, "get_run", scope.session_id, run.run_id)
        assert still_leased.status.value == "running"
        await asyncio.sleep(0.7)
        fresh = AsyncSubAgentRunRegistryV2(sessions, scope_provider=lambda: scope)
        recovered = await registry_call_v2(fresh, "get_run", scope.session_id, run.run_id)
        assert recovered.status.value == "failed"
        assert recovered.metadata["recovery_status"] == "interrupted"
        assert recovered.metadata["prior_tool_outcome"] == "unknown"
        assert recovered.metadata["automatic_replay"] is False
        assert (
            len(
                [
                    event
                    for event in recovered.metadata["announce_events"]
                    if event["type"] == "subagent_interrupted"
                ]
            )
            == 1
        )
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def test_owner_clock_advances_inside_transaction(postgres_registry):
    from src.infrastructure.agent.subagent.owner_lease_v2 import database_now_v2

    _, sessions, _ = postgres_registry
    async with sessions() as db, db.begin():
        before = await database_now_v2(db)
        await asyncio.sleep(0.03)
        after = await database_now_v2(db)
        assert after > before


async def test_revoked_owner_cannot_dispatch_a_model(postgres_registry, monkeypatch):
    from src.infrastructure.agent.subagent.owner_lease_v2 import database_now_v2

    _, sessions, scope = postgres_registry
    _, run = await _reserved(postgres_registry)
    calls = []

    class Stream:
        def __init__(self, *_args, **_kwargs):
            pass

        async def generate(self, *_args, **_kwargs):
            calls.append("model")
            yield None

    monkeypatch.setattr("src.infrastructure.agent.processor.processor.LLMStream", Stream)
    async with SubAgentExecutionOwnerV2(sessions, scope.session_id, run.run_id):
        async with sessions() as db, db.begin():
            lease = await db.get(SubAgentOwnerLeaseV2, (scope.session_id, run.run_id))
            lease.expires_at = await database_now_v2(db) - timedelta(seconds=1)
        processor, _ = _processor(run.run_id, None)
        with pytest.raises(RuntimeV2Error, match="no longer valid"):
            _ = [
                event
                async for event in processor._process_step(
                    "session", [{"role": "user", "content": "test"}]
                )
            ]
        assert calls == []


async def test_heartbeat_renews_lease_but_other_tenant_cannot_claim(postgres_registry):
    from dataclasses import replace

    _, sessions, scope = postgres_registry
    registry, run = await _reserved(postgres_registry)
    foreign = AsyncSubAgentRunRegistryV2(
        sessions, scope_provider=lambda: replace(scope, tenant_id="other-tenant")
    )
    with pytest.raises(RuntimeV2Error, match="outside the admitted scope"):
        async with foreign.own_execution(scope.session_id, run.run_id):
            pytest.fail("foreign scope claimed owner")
    async with SubAgentExecutionOwnerV2(
        sessions, scope.session_id, run.run_id, lease_duration=timedelta(seconds=0.6)
    ):
        async with sessions() as db:
            initial = (
                await db.get(SubAgentOwnerLeaseV2, (scope.session_id, run.run_id))
            ).expires_at
        await asyncio.sleep(0.8)
        await fence_subagent_owner_v2(child_run_id=run.run_id)
        async with sessions() as db:
            renewed = await db.get(SubAgentOwnerLeaseV2, (scope.session_id, run.run_id))
            assert renewed.expires_at > initial
        await registry_call_v2(
            registry, "mark_completed", scope.session_id, run.run_id, summary="done"
        )


async def test_unclaimed_reservation_recovers_without_inventing_tool_execution(postgres_registry):
    from src.infrastructure.agent.subagent.owner_lease_v2 import database_now_v2

    _, sessions, scope = postgres_registry
    registry, run = await _reserved(postgres_registry)
    async with sessions() as db, db.begin():
        lease = await db.get(SubAgentOwnerLeaseV2, (scope.session_id, run.run_id))
        lease.expires_at = await database_now_v2(db) - timedelta(seconds=1)
    restored = await registry_call_v2(registry, "get_run", scope.session_id, run.run_id)
    assert restored.status.value == "failed"
    assert restored.metadata["prior_tool_outcome"] == "not_started"
    with pytest.raises(RuntimeV2Error, match="already owned"):
        async with SubAgentExecutionOwnerV2(sessions, scope.session_id, run.run_id):
            pytest.fail("revoked admission was replayed")


async def test_owner_migration_downgrade_preserves_existing_run_data(postgres_registry):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    engine, _, scope = postgres_registry
    _, run = await _reserved(postgres_registry)
    spec = importlib.util.spec_from_file_location(
        "owner_migration_roundtrip",
        Path("alembic/versions/71e6b3a29c84_add_subagent_execution_owner_leases.py"),
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def roundtrip(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()

    async with engine.begin() as connection:
        before = await connection.scalar(text("SELECT runs FROM subagent_run_snapshots_v2"))
        await connection.run_sync(roundtrip)
        after = await connection.scalar(text("SELECT runs FROM subagent_run_snapshots_v2"))
        assert after == before
        assert run.run_id in after
        assert after[run.run_id]["conversation_id"] == scope.session_id
        assert await connection.scalar(text("SELECT count(*) FROM subagent_owner_leases_v2")) == 0
