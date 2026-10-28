"""Full runtime bootstrap repair in an explicit test database; schemas are rolled back.

Set MEMSTACK_MIGRATION_TEST_DATABASE_URL, MEMSTACK_MIGRATION_TEST_EXPECTED_DATABASE
and MEMSTACK_MIGRATION_TEST_EXPECTED_PORT only for a dedicated loopback test database.
No application startup, live account bootstrap, or default database fallback is used.
"""

import importlib.util
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "alembic/versions/c86fa94f00dd_complete_chat_runtime_bootstrap.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("review_chat_bootstrap", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(
    connection: Connection, timeline_shape: str, preexisting_runtime: bool
) -> list[tuple[str, int, int]]:
    metadata = sa.MetaData()
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("profile", sa.JSON(), nullable=False),
    )
    for name in ("tenants", "projects", "workspaces", "conversations"):
        sa.Table(name, metadata, sa.Column("id", sa.String(), primary_key=True))
    sa.Table(
        "messages",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
    )
    sa.Table("mcp_apps", metadata, sa.Column("id", sa.String(), primary_key=True))
    sa.Table(
        "artifacts",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="artifacts_workspace_id_fkey"
        ),
    )
    fields = []
    if timeline_shape in ("legacy", "both"):
        fields.extend(
            [
                sa.Column("sequence_number", sa.Integer(), nullable=False),
                sa.UniqueConstraint(
                    "conversation_id", "sequence_number", name="uq_agent_events_conv_seq"
                ),
            ]
        )
    if timeline_shape in ("current", "both"):
        fields.extend(
            [
                sa.Column("event_time_us", sa.BigInteger(), nullable=False),
                sa.Column("event_counter", sa.Integer(), nullable=False),
            ]
        )
    events = sa.Table(
        "agent_execution_events",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("message_id", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        *fields,
    )
    metadata.create_all(connection)
    connection.execute(
        users.insert(),
        [
            {
                "id": "default-admin",
                "email": "admin@memstack.ai",
                "is_active": True,
                "is_superuser": False,
                "profile": {"preserve": "admin"},
            },
            {
                "id": "inactive-admin",
                "email": "disabled@example.test",
                "is_active": False,
                "is_superuser": True,
                "profile": {"preserve": "inactive"},
            },
            {
                "id": "ordinary",
                "email": "user@memstack.ai",
                "is_active": True,
                "is_superuser": False,
                "profile": {"preserve": "ordinary"},
            },
        ],
    )
    for name, value in (
        ("tenants", "tenant"),
        ("projects", "project"),
        ("workspaces", "legacy-workspace"),
        ("conversations", "conversation"),
    ):
        connection.execute(metadata.tables[name].insert().values(id=value))
    connection.execute(
        metadata.tables["messages"].insert(),
        [
            {"id": "message-a", "content": "preserve first"},
            {"id": "message-b", "content": "preserve second"},
        ],
    )
    connection.execute(metadata.tables["mcp_apps"].insert().values(id="existing-app"))
    connection.execute(
        metadata.tables["artifacts"]
        .insert()
        .values(id="existing-artifact", workspace_id="legacy-workspace")
    )
    base = datetime(2026, 1, 1, tzinfo=UTC)
    expected = []
    for index, offset in enumerate((0, 0, -1, 1)):
        values = {
            "id": str(index),
            "conversation_id": "conversation",
            "created_at": base + timedelta(seconds=offset),
        }
        time_us = int(base.timestamp()) * 1_000_000 + (1_000_000 if index == 3 else 0)
        counter = index if index < 3 else 0
        if timeline_shape in ("legacy", "both"):
            values["sequence_number"] = index
        if timeline_shape in ("current", "both"):
            values.update(event_time_us=time_us + 17, event_counter=counter)
            time_us += 17
        connection.execute(events.insert().values(**values))
        expected.append((str(index), time_us, counter))
    if preexisting_runtime:
        # Model-created deployments may already have the newer columns and data.
        connection.execute(
            sa.text("""ALTER TABLE conversations
            ADD COLUMN branch_point_message_id varchar, ADD COLUMN summary text""")
        )
        connection.execute(
            sa.text("""UPDATE conversations SET
            branch_point_message_id='message-a', summary='Preserve summary'""")
        )
        connection.execute(
            sa.text("""ALTER TABLE messages
            ADD COLUMN reply_to_id varchar, ADD COLUMN version integer NOT NULL DEFAULT 1,
            ADD COLUMN original_content text, ADD COLUMN edited_at timestamptz""")
        )
        connection.execute(sa.text("UPDATE messages SET version=7, original_content='Original'"))
        connection.execute(
            sa.text("UPDATE messages SET reply_to_id='message-a' WHERE id='message-b'")
        )
        connection.execute(
            sa.text("""ALTER TABLE mcp_apps
            ADD COLUMN ui_metadata json NOT NULL DEFAULT '{}',
            ADD COLUMN resource_mime_type varchar(100),
            ADD COLUMN resource_resolved_at timestamptz""")
        )
        connection.execute(
            sa.text("""UPDATE mcp_apps SET ui_metadata=json_build_object('preserve',true),
            resource_mime_type='text/html'""")
        )
        # Independent fixture definitions deliberately retain an extra deployment column.
        connection.execute(
            sa.text("""CREATE TABLE audit_logs (
            id varchar PRIMARY KEY, timestamp timestamptz NOT NULL DEFAULT now(),
            actor varchar, action varchar NOT NULL, resource_type varchar NOT NULL,
            resource_id varchar, tenant_id varchar, details json NOT NULL,
            ip_address varchar, user_agent varchar, deployment_note text)""")
        )
        connection.execute(
            sa.text("""CREATE TABLE prompt_templates (
            id varchar PRIMARY KEY, tenant_id varchar NOT NULL REFERENCES tenants(id),
            project_id varchar REFERENCES projects(id),
            created_by varchar NOT NULL REFERENCES users(id),
            title varchar(200) NOT NULL, content text NOT NULL, category varchar(50) NOT NULL,
            variables json NOT NULL, is_system boolean NOT NULL, usage_count integer NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz,
            deployment_note text, CONSTRAINT uq_tenant_template_title UNIQUE(tenant_id, title))""")
        )
        connection.execute(
            sa.text("""INSERT INTO audit_logs
            (id, action, resource_type, details, deployment_note)
            VALUES ('old-audit', 'preserve', 'fixture', '{}', 'do not delete')""")
        )
        connection.execute(
            sa.text("""INSERT INTO prompt_templates
            (id, tenant_id, created_by, title, content, category, variables, is_system,
             usage_count, deployment_note)
            VALUES ('old-prompt', 'tenant', 'default-admin', 'Old', 'Preserve', 'fixture',
                    '{}', false, 7, 'do not delete')""")
        )
    return expected


def _snapshot_users(connection: Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(sa.text("SELECT * FROM users ORDER BY id")).mappings()
    ]


def _verify_full(
    connection: Connection,
    expected: list[tuple[str, int, int]],
    users_before: list[dict[str, Any]],
    preexisting_runtime: bool,
) -> None:
    inspector = sa.inspect(connection)
    names = set(inspector.get_table_names())
    assert {"audit_logs", "prompt_templates"} <= names
    expected_columns = {
        "conversations": {"branch_point_message_id", "summary"},
        "messages": {"reply_to_id", "version", "original_content", "edited_at"},
        "mcp_apps": {"ui_metadata", "resource_mime_type", "resource_resolved_at"},
        "audit_logs": {"actor", "action", "resource_type", "details", "timestamp"},
        "prompt_templates": {"tenant_id", "project_id", "created_by", "variables", "usage_count"},
    }
    for table, expected_names in expected_columns.items():
        assert expected_names <= {column["name"] for column in inspector.get_columns(table)}
    assert "sequence_number" not in {
        c["name"] for c in inspector.get_columns("agent_execution_events")
    }
    assert (
        connection.execute(
            sa.text("""SELECT id, event_time_us, event_counter
        FROM agent_execution_events ORDER BY event_time_us, event_counter""")
        ).all()
        == expected
    )
    assert _snapshot_users(connection) == users_before
    version = 7 if preexisting_runtime else 1
    assert connection.execute(
        sa.text("SELECT id, content, version, reply_to_id FROM messages ORDER BY id")
    ).all() == [
        ("message-a", "preserve first", version, None),
        ("message-b", "preserve second", version, "message-a" if preexisting_runtime else None),
    ]
    assert connection.execute(
        sa.text("SELECT ui_metadata FROM mcp_apps WHERE id='existing-app'")
    ).scalar_one() == ({"preserve": True} if preexisting_runtime else {})
    assert (
        connection.execute(
            sa.text("SELECT workspace_id FROM artifacts WHERE id='existing-artifact'")
        ).scalar_one()
        == "legacy-workspace"
    )
    message_fks = inspector.get_foreign_keys("messages")
    assert (
        sum(
            fk["constrained_columns"] == ["reply_to_id"]
            and fk["referred_table"] == "messages"
            and fk["referred_columns"] == ["id"]
            for fk in message_fks
        )
        == 1
    )
    assert not any(
        fk["name"] == "artifacts_workspace_id_fkey"
        for fk in inspector.get_foreign_keys("artifacts")
    )
    assert any(
        c["column_names"] == ["conversation_id", "event_time_us", "event_counter"]
        for c in inspector.get_unique_constraints("agent_execution_events")
    )
    assert {"ix_agent_events_conv_time", "ix_agent_events_msg_time"} <= {
        index["name"] for index in inspector.get_indexes("agent_execution_events")
    }
    if preexisting_runtime:
        assert connection.execute(
            sa.text("SELECT summary, branch_point_message_id FROM conversations")
        ).one() == ("Preserve summary", "message-a")
        assert (
            connection.scalar(sa.text("SELECT original_content FROM messages WHERE id='message-a'"))
            == "Original"
        )
        assert connection.scalar(sa.text("SELECT resource_mime_type FROM mcp_apps")) == "text/html"
        assert (
            connection.execute(
                sa.text("SELECT deployment_note FROM audit_logs WHERE id='old-audit'")
            ).scalar_one()
            == "do not delete"
        )
        assert connection.execute(
            sa.text(
                "SELECT usage_count, deployment_note FROM prompt_templates WHERE id='old-prompt'"
            )
        ).one() == (7, "do not delete")
    else:
        assert {
            "ix_audit_logs_action",
            "ix_audit_logs_resource_type",
            "ix_audit_logs_tenant_id",
            "ix_audit_logs_timestamp",
            "ix_audit_logs_tenant_action",
        } <= {index["name"] for index in inspector.get_indexes("audit_logs")}
        assert {"users", "tenants", "projects"} == {
            fk["referred_table"] for fk in inspector.get_foreign_keys("prompt_templates")
        }
        assert any(
            c["column_names"] == ["tenant_id", "title"]
            for c in inspector.get_unique_constraints("prompt_templates")
        )


async def _in_owned_schema(operation: Callable[[Connection], None]) -> None:
    url = os.environ.get("MEMSTACK_MIGRATION_TEST_DATABASE_URL")
    expected_database = os.environ.get("MEMSTACK_MIGRATION_TEST_EXPECTED_DATABASE")
    expected_port = os.environ.get("MEMSTACK_MIGRATION_TEST_EXPECTED_PORT")
    if not (url and expected_database and expected_port):
        pytest.skip("An explicit dedicated PostgreSQL test URL, database and port are required")
    parsed = sa.engine.make_url(url)
    assert parsed.get_backend_name() == "postgresql"
    assert parsed.host in {"127.0.0.1", "localhost"}, "Explicit loopback test target required"
    assert expected_port and parsed.port == int(expected_port), "Explicit owned endpoint required"
    assert expected_database and parsed.database == expected_database, (
        "Explicit owned database identity required"
    )
    engine = create_async_engine(parsed.set(drivername="postgresql+asyncpg"), echo=False)
    schema = "qa_c86_full_" + uuid4().hex
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                assert (
                    await connection.scalar(sa.text("SELECT current_database()"))
                    == expected_database
                )
                await connection.execute(sa.schema.CreateSchema(schema))
                await connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
                assert await connection.scalar(sa.text("SELECT current_schema()")) == schema
                await connection.run_sync(operation)
            finally:
                await transaction.rollback()
    finally:
        try:
            async with engine.connect() as verification:
                assert (
                    await verification.scalar(
                        sa.text("SELECT count(*) FROM pg_namespace WHERE nspname=:name"),
                        {"name": schema},
                    )
                    == 0
                )
        finally:
            await engine.dispose()


@pytest.mark.parametrize("timeline_shape", ["legacy", "current", "both"])
@pytest.mark.parametrize("preexisting_runtime", [False, True])
async def test_whole_upgrade_preserves_rows_and_is_idempotent(
    timeline_shape: str,
    preexisting_runtime: bool,
) -> None:
    def run(connection: Connection) -> None:
        expected = _fixture(connection, timeline_shape, preexisting_runtime)
        users_before = _snapshot_users(connection)
        migration = _load_migration()
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            _verify_full(connection, expected, users_before, preexisting_runtime)
            migration.upgrade()
            _verify_full(connection, expected, users_before, preexisting_runtime)
        # Exercise the new FK and removal of the retired workspace authority relation.
        connection.execute(
            sa.text("UPDATE messages SET reply_to_id='message-a' WHERE id='message-b'")
        )
        connection.execute(
            sa.text(
                "INSERT INTO artifacts(id,workspace_id) "
                "VALUES ('avernet-artifact','avernet-workspace')"
            )
        )
        assert (
            connection.scalar(sa.text("SELECT reply_to_id FROM messages WHERE id='message-b'"))
            == "message-a"
        )

    await _in_owned_schema(run)


def test_downgrade_is_explicitly_forward_only() -> None:
    with pytest.raises(RuntimeError, match="forward-only"):
        _load_migration().downgrade()
