"""Actual PostgreSQL transactions in a disposable, task-owned schema."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    Conversation,
    Project,
    Tenant,
    ToolExecutionRecord,
    User,
)
from src.infrastructure.plugins.v2 import session_event_log_store as store_module
from src.infrastructure.plugins.v2.session_event_log_store import SqlSessionEventLogStoreV2
from src.tests.unit.infrastructure.plugins.v2.test_tool_execution_producer_projection import event

pytestmark = pytest.mark.integration


@pytest.fixture
async def postgres_producer(monkeypatch):
    url = make_url(get_settings().postgres_url).set(drivername="postgresql+asyncpg")
    schema = "qa_tool_projection_" + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url, poolclass=NullPool, connect_args={"server_settings": {"search_path": schema}}
    )
    created = False
    try:
        async with admin.begin() as connection:
            await connection.execute(CreateSchema(schema))
            created = True
        async with engine.begin() as connection:
            assert connection.dialect.name == "postgresql"
            for model in (
                User,
                Tenant,
                Project,
                Conversation,
                ToolExecutionRecord,
                AgentExecutionEvent,
            ):
                await connection.run_sync(model.__table__.create)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db, db.begin():
            await db.execute(
                User.__table__.insert().values(
                    id="user", email="qa@example.invalid", hashed_password="unused"
                )
            )
            for suffix in ("a", "b"):
                await db.execute(
                    Tenant.__table__.insert().values(
                        id="tenant-" + suffix, name="qa", slug="qa-" + suffix, owner_id="user"
                    )
                )
                await db.execute(
                    Project.__table__.insert().values(
                        id="project-" + suffix,
                        tenant_id="tenant-" + suffix,
                        name="qa",
                        owner_id="user",
                    )
                )
                await db.execute(
                    Conversation.__table__.insert().values(
                        id="cid-" + suffix,
                        tenant_id="tenant-" + suffix,
                        project_id="project-" + suffix,
                        user_id="user",
                        title="qa",
                    )
                )
        monkeypatch.setattr(store_module, "async_session_factory", sessions)
        yield SqlSessionEventLogStoreV2(), sessions
    finally:
        await engine.dispose()
        if created:
            async with admin.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await admin.dispose()


async def append(store, events, cid="cid-a", message="turn"):
    await store.append_stream_events(
        conversation_id=cid, message_id=message, events=events, correlation_id=None
    )


async def test_postgres_concurrent_replay_and_late_act(postgres_producer):
    store, sessions = postgres_producer
    batch = [
        event("act", 1, tool_input={"value": "original"}),
        event("observe", 2, status="success", result="done"),
    ]
    await asyncio.gather(*(append(store, batch) for _ in range(8)))
    await append(store, [event("act", 3, tool_input={"value": "late"})])
    async with sessions() as db:
        rows = list((await db.execute(select(ToolExecutionRecord))).scalars())
        assert len(rows) == 1
        assert rows[0].status == "success"
        assert rows[0].tool_output == "done"
        assert rows[0].tool_input == {"value": "original"}
        assert len(list((await db.execute(select(AgentExecutionEvent))).scalars())) == 3


async def test_postgres_cross_tenant_identity_collision_rolls_back(postgres_producer):
    store, sessions = postgres_producer
    await append(store, [event("act", 1)])
    results = await asyncio.gather(
        append(store, [event("observe", 2, status="success", result="owner")]),
        append(store, [event("observe", 2, status="success", result="foreign")], cid="cid-b"),
        return_exceptions=True,
    )
    assert results[0] is None
    assert isinstance(results[1], ValueError)
    async with sessions() as db:
        row = await db.get(ToolExecutionRecord, "exact-execution")
        assert (row.conversation_id, row.message_id, row.call_id, row.tool_name) == (
            "cid-a",
            "turn",
            "exact-call",
            "opaque_tool",
        )
        assert row.status == "success" and row.tool_output == "owner"
        assert (
            list(
                (
                    await db.execute(
                        select(AgentExecutionEvent).where(
                            AgentExecutionEvent.conversation_id == "cid-b"
                        )
                    )
                ).scalars()
            )
            == []
        )


async def test_postgres_cancel_rolls_back_both_projections(postgres_producer, monkeypatch):
    store, sessions = postgres_producer
    original = store_module.apply_tool_execution_event_projection

    async def cancel(*args, **kwargs):
        await original(*args, **kwargs)
        raise asyncio.CancelledError

    monkeypatch.setattr(store_module, "apply_tool_execution_event_projection", cancel)
    with pytest.raises(asyncio.CancelledError):
        await append(store, [event("act", 1)])
    async with sessions() as db:
        assert list((await db.execute(select(ToolExecutionRecord))).scalars()) == []
        assert list((await db.execute(select(AgentExecutionEvent))).scalars()) == []
