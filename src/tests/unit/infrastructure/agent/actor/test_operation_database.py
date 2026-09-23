"""Independently admitted workers own their DB, including marketplace event consumers."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.actor.operation_database import admit_agent_turn_v2
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2

pytestmark = pytest.mark.unit
SCOPE = ScopeV2(
    kind=ScopeKindV2.SESSION, tenant_id="tenant", project_id="project", session_id="session"
)


@pytest.mark.parametrize("failure", [None, RuntimeError, asyncio.CancelledError])
async def test_session_owned_until_admission_disposes_and_closed_on_failure(monkeypatch, failure):
    from src.infrastructure.adapters.secondary.persistence import database

    events = []
    sessions = []

    class Session(AsyncSession):
        async def close(self):
            events.append("db-close")
            await super().close()

    def factory():
        session = Session()
        sessions.append(session)
        return session

    @asynccontextmanager
    async def admit(**kwargs):
        db = kwargs["services"][OPERATION_DB_SESSION_SERVICE_V2]
        events.append("admit")
        try:
            yield db
        finally:
            events.append("dispose")

    monkeypatch.setattr(database, "async_session_factory", factory)
    caller_db = AsyncSession()

    async def run():
        async with admit_agent_turn_v2(
            SimpleNamespace(admit=admit),
            descriptor_payload={},
            distribution_payload={},
            operation_id="turn",
            scope=SCOPE,
            services={OPERATION_DB_SESSION_SERVICE_V2: caller_db},
        ) as owned:
            assert owned is not caller_db
            assert owned is sessions[-1]
            if failure:
                raise failure()

    try:
        if failure:
            with pytest.raises(failure):
                await run()
        else:
            await asyncio.gather(run(), run())
            assert sessions[0] is not sessions[1]
        assert events.count("dispose") == len(sessions)
        assert events.count("db-close") == len(sessions)
        assert events.index("dispose") < events.index("db-close")
    finally:
        await caller_db.close()


@pytest.fixture
async def providers():
    # Use the actual production ROOT profile and Provider graph, not a fake resolver.
    from src.tests.unit.application.services.test_marketplace_cache_recovery import runtime_host

    generator = runtime_host.__wrapped__()
    value = await anext(generator)
    try:
        yield value
    finally:
        await generator.aclose()


async def test_admitted_database_drives_all_hook_events_and_mcp_provider(
    monkeypatch, providers, tmp_path
):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.application.services.marketplace_oauth_runtime import OAuthSandboxMCPServerManager
    from src.infrastructure.adapters.secondary.persistence import database
    from src.infrastructure.adapters.secondary.persistence.models import Project, ProjectSandbox
    from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
        MarketplaceRecordV3,
    )
    from src.infrastructure.plugins.v2 import agent_runtime_dispatcher
    from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
    from src.infrastructure.plugins.v2.mcp_services import MCP_APPLICATION_SERVICE_V2

    host, adapter = providers
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'hooks.db'}")
    async with engine.begin() as connection:
        for table in (Project.__table__, ProjectSandbox.__table__, MarketplaceRecordV3.__table__):
            await connection.run_sync(table.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session_factory", sessions)
    monkeypatch.setattr(
        agent_runtime_dispatcher, "_dispatch_migrated_event_v2", AsyncMock(return_value=())
    )
    async with sessions() as db:
        db.add(Project(id="project", tenant_id="tenant", name="project", owner_id="user"))
        db.add(
            ProjectSandbox(
                id="binding",
                tenant_id="tenant",
                project_id="project",
                sandbox_id="sandbox",
                status="running",
            )
        )
        hooks = [
            {"event": event, "command": "python3 ${PLUGIN_ROOT}/hook.py", "timeout_seconds": 30}
            for event in ("session_start", "before_request", "after_tool_execute")
        ]
        db.add(
            MarketplaceRecordV3(
                id="plugin",
                tenant_id="tenant",
                project_id="project",
                kind="installation",
                record_key="plugin",
                payload={
                    "status": "enabled",
                    "approved_permissions": ["process:execute"],
                    "runtime_root": "/workspace/.memstack/plugins/11111111-1111-1111-1111-111111111111/"
                    + "a" * 64,
                    "package": {"resources": {"hooks": hooks}},
                },
            )
        )
        await db.commit()

    @asynccontextmanager
    async def admit(**kwargs):
        async with pin_operation_context_v2(
            host,
            operation_id=kwargs["operation_id"],
            scope=kwargs["scope"],
            services=kwargs["services"],
        ) as operation:
            yield operation

    try:
        async with admit_agent_turn_v2(
            SimpleNamespace(admit=admit),
            descriptor_payload={},
            distribution_payload={},
            operation_id="hooks-turn",
            scope=SCOPE,
        ) as operation:
            resolver = operation.require(MCP_APPLICATION_SERVICE_V2)
            assert isinstance(
                resolver.resolve(operation).sandbox_manager, OAuthSandboxMCPServerManager
            )
            dispatcher = agent_runtime_dispatcher.PinnedAgentRuntimeDispatcherV2()
            for event in ("on_session_start", "before_response", "after_tool_execution"):
                await dispatcher.dispatch(event, {"session_id": "session", "tool_name": "echo"})
        calls = adapter.call_tool.call_args_list
        assert len(calls) == 3
        for call, event in zip(
            calls, ("session_start", "before_request", "after_tool_execute"), strict=True
        ):
            assert call.kwargs["sandbox_id"] == "sandbox"
            assert event in call.kwargs["arguments"]["command"]
    finally:
        await engine.dispose()
