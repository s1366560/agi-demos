"""Exact task content survives the real PostgreSQL title-width boundary."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanVersionModel,
    AgentTaskModel,
    Conversation,
    Project,
    Tenant,
    User,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.todo_tools import make_todo_tools

pytestmark = pytest.mark.integration


@pytest.fixture
async def title_sessions():
    url = make_url(get_settings().postgres_url).set(drivername="postgresql+asyncpg")
    schema = "qa_task_title_" + uuid4().hex
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
                AgentTaskModel,
                AgentPlanVersionModel,
            ):
                await connection.run_sync(model.__table__.create)
            await connection.execute(
                User.__table__.insert().values(
                    id="user",
                    email="task-title@example.invalid",
                    hashed_password="unused",
                )
            )
            await connection.execute(
                Tenant.__table__.insert().values(
                    id="tenant",
                    name="qa",
                    slug="qa",
                    owner_id="user",
                )
            )
            await connection.execute(
                Project.__table__.insert().values(
                    id="project",
                    tenant_id="tenant",
                    name="qa",
                    owner_id="user",
                )
            )
            await connection.execute(
                Conversation.__table__.insert().values(
                    id="conversation",
                    tenant_id="tenant",
                    project_id="project",
                    user_id="user",
                    title="qa",
                )
            )
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        if created:
            async with admin.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await admin.dispose()


@pytest.mark.parametrize("action", ["replace", "add"])
async def test_real_postgres_keeps_full_unicode_content_and_bounded_titles(title_sessions, action):
    content = "准确原始脚本𠀀\n" * 130
    explicit_title = "中𠀀" * 250
    tool = make_todo_tools(session_factory=title_sessions)["todowrite"]
    result = await tool.execute(
        ToolContext(
            session_id="conversation",
            conversation_id="conversation",
            message_id="message",
            call_id="call",
            agent_name="fixture",
        ),
        action=action,
        todos=[{"content": content}, {"content": content, "title": explicit_title}],
    )
    assert not result.is_error
    async with title_sessions() as db:
        rows = list(
            (await db.scalars(select(AgentTaskModel).order_by(AgentTaskModel.order_index))).all()
        )
        assert [row.content for row in rows] == [content, content]
        assert [row.title for row in rows] == [content[:500], explicit_title]
        assert all(len(row.title) == 500 for row in rows)
        if action == "replace":
            plan = await db.scalar(select(AgentPlanVersionModel))
            assert plan.tasks_json[0]["content"] == content
            assert plan.tasks_json[1]["title"] == explicit_title
