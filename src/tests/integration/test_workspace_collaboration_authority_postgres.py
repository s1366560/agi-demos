"""PostgreSQL proof for Workspace Collaboration revision triggers and initialization."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import asyncpg
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.application.services.workspace_collaboration_authority import (
    WorkspaceCollaborationActor,
    WorkspaceCollaborationMutationCommand,
    WorkspaceCollaborationRevisionConflictError,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_collaboration_authority_repository import (
    SqlWorkspaceCollaborationAuthorityRepository,
)

_POSTGRES_URL = os.getenv("WORKSPACE_AUTHORITY_POSTGRES_URL") or os.getenv("DATABASE_URL")
if _POSTGRES_URL and not _POSTGRES_URL.startswith(("postgresql://", "postgresql+asyncpg://")):
    _POSTGRES_URL = None
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _POSTGRES_URL,
        reason="a PostgreSQL DATABASE_URL is required for the authority trigger proof",
    ),
]
_MIGRATION_PATH = (
    Path(__file__).parents[3]
    / "alembic"
    / "versions"
    / "d4e9f0a1b2c3_add_workspace_collaboration_authority.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "workspace_collaboration_authority_postgres_migration",
        _MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture_migration_execute_calls(*, downgrade: bool = False):
    migration = _load_migration()
    migration_op = Mock()
    migration_op.get_bind.return_value = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    migration.op = migration_op
    if downgrade:
        migration.downgrade()
    else:
        migration.upgrade()
    return migration, [call.args[0] for call in migration_op.execute.call_args_list]


def _dsn() -> str:
    assert _POSTGRES_URL is not None
    return _POSTGRES_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


def _sqlalchemy_dsn() -> str:
    assert _POSTGRES_URL is not None
    return _POSTGRES_URL.replace("postgresql://", "postgresql+asyncpg://", 1)


async def _set_search_path(connection: asyncpg.Connection, schema: str) -> None:
    await connection.execute(f'SET search_path TO "{schema}"')


async def _create_minimal_authority_schema(
    connection: asyncpg.Connection,
    *,
    schema: str,
    direct_tables: tuple[str, ...],
) -> None:
    await connection.execute(f'CREATE SCHEMA "{schema}"')
    await _set_search_path(connection, schema)
    await connection.execute(
        """
        CREATE TABLE workspaces (
            id text PRIMARY KEY,
            tenant_id text NOT NULL,
            project_id text NOT NULL
        );
        CREATE TABLE workspace_collaboration_authorities (
            workspace_id text PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
            tenant_id text NOT NULL,
            project_id text NOT NULL,
            revision bigint NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE workspace_collaboration_mutation_receipts (
            id text PRIMARY KEY,
            tenant_id text NOT NULL,
            project_id text NOT NULL,
            workspace_id text NOT NULL,
            actor_user_id text NOT NULL,
            contract_version varchar(20) NOT NULL,
            surface varchar(32) NOT NULL,
            action varchar(64) NOT NULL,
            idempotency_key varchar(256) NOT NULL,
            request_hash varchar(64) NOT NULL,
            expected_revision bigint NOT NULL,
            committed_revision bigint,
            created_at timestamptz NOT NULL DEFAULT now(),
            committed_at timestamptz
        );
        CREATE UNIQUE INDEX uq_workspace_collaboration_receipt_intent
        ON workspace_collaboration_mutation_receipts (
            workspace_id,
            actor_user_id,
            idempotency_key
        );
        CREATE TABLE conversations (
            id text PRIMARY KEY,
            workspace_id text,
            tenant_id text NOT NULL,
            project_id text NOT NULL
        );
        CREATE TABLE workspace_plan_nodes (
            id text PRIMARY KEY,
            plan_id text NOT NULL
        );
        CREATE TABLE tool_execution_records (
            id text PRIMARY KEY,
            conversation_id text NOT NULL
        );
        """
    )
    for table_name in direct_tables:
        conversation_column = (
            ", conversation_id text" if table_name == "workspace_task_session_attempts" else ""
        )
        await connection.execute(
            f"""
            CREATE TABLE {table_name} (
                id text PRIMARY KEY,
                workspace_id text NOT NULL
                {conversation_column}
            )
            """
        )


async def _install_upgrade_and_assert_backfill(
    connection: asyncpg.Connection,
    upgrade_calls: list[object],
) -> None:
    await connection.execute(
        """
        INSERT INTO workspaces (id, tenant_id, project_id)
        VALUES
            ('workspace-a', 'tenant-a', 'project-a'),
            ('workspace-b', 'tenant-b', 'project-b')
        """
    )
    for operation in upgrade_calls:
        sql = str(operation).strip()
        if sql.lower().startswith("insert into workspace_collaboration_authorities"):
            compiled = str(
                operation.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
            await connection.execute(compiled)
        elif sql.lower().startswith(("create function", "create trigger")):
            await connection.execute(sql)
    backfilled = await connection.fetch(
        """
        SELECT workspace_id, revision
        FROM workspace_collaboration_authorities
        ORDER BY workspace_id
        """
    )
    assert [(row["workspace_id"], row["revision"]) for row in backfilled] == [
        ("workspace-a", 0),
        ("workspace-b", 0),
    ]


async def _assert_worker_trigger_revisions(connection: asyncpg.Connection) -> None:
    await connection.execute(
        """
        INSERT INTO conversations (id, workspace_id, tenant_id, project_id)
        VALUES
            ('conversation-a', 'workspace-a', 'tenant-a', 'project-a'),
            ('conversation-mismatch', 'workspace-a', 'tenant-b', 'project-a'),
            ('conversation-b', 'workspace-b', 'tenant-b', 'project-b');
        INSERT INTO workspace_task_session_attempts (id, workspace_id, conversation_id)
        VALUES
            ('attempt-a', 'workspace-a', 'conversation-a'),
            ('attempt-mismatch', 'workspace-a', 'conversation-mismatch'),
            ('attempt-b', 'workspace-b', 'conversation-b');
        INSERT INTO workspace_plans (id, workspace_id)
        VALUES ('plan-a', 'workspace-a');
        INSERT INTO workspace_plan_nodes (id, plan_id)
        VALUES ('node-a', 'plan-a');
        INSERT INTO workspace_plan_outbox (id, workspace_id)
        VALUES ('outbox-a', 'workspace-a');
        INSERT INTO tool_execution_records (id, conversation_id)
        VALUES
            ('tool-a', 'conversation-a'),
            ('tool-mismatch', 'conversation-mismatch'),
            ('tool-b', 'conversation-b');
        """
    )
    revisions = {
        row["workspace_id"]: row["revision"]
        for row in await connection.fetch(
            """
            SELECT workspace_id, revision
            FROM workspace_collaboration_authorities
            ORDER BY workspace_id
            """
        )
    }
    assert revisions == {"workspace-a": 6, "workspace-b": 2}


async def _assert_concurrent_first_write(
    connection: asyncpg.Connection,
    *,
    schema: str,
) -> None:
    await connection.execute(
        """
        INSERT INTO workspaces (id, tenant_id, project_id)
        VALUES ('workspace-race', 'tenant-race', 'project-race');
        DELETE FROM workspace_collaboration_authorities
        WHERE workspace_id = 'workspace-race';
        """
    )
    actor = WorkspaceCollaborationActor(
        tenant_id="tenant-race",
        project_id="project-race",
        workspace_id="workspace-race",
        user_id="user-race",
    )
    command = WorkspaceCollaborationMutationCommand(
        contract_version="2.0.0",
        surface="discussion",
        action="create_post",
        expected_revision=0,
        idempotency_key="workspace-race-command",
        payload={"title": "Race proof"},
    )
    engine = create_async_engine(
        _sqlalchemy_dsn(),
        connect_args={"server_settings": {"search_path": schema}},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def desktop_first_write() -> str:
        try:
            async with session_factory() as session, session.begin():
                repository = SqlWorkspaceCollaborationAuthorityRepository(session)
                await repository.reserve(
                    actor=actor,
                    command=command,
                    request_hash="a" * 64,
                )
            return "reserved"
        except WorkspaceCollaborationRevisionConflictError:
            return "revision_conflict"

    async def legacy_first_write() -> None:
        legacy_connection = await asyncpg.connect(_dsn())
        try:
            await _set_search_path(legacy_connection, schema)
            async with legacy_connection.transaction():
                await legacy_connection.execute(
                    """
                    INSERT INTO workspace_task_session_attempts (id, workspace_id)
                    VALUES ('attempt-race', 'workspace-race')
                    """
                )
        finally:
            await legacy_connection.close()

    try:
        desktop_result, _legacy_result = await asyncio.gather(
            desktop_first_write(),
            legacy_first_write(),
        )
    finally:
        await engine.dispose()
    assert desktop_result in {"reserved", "revision_conflict"}
    race_rows = await connection.fetch(
        """
        SELECT revision
        FROM workspace_collaboration_authorities
        WHERE workspace_id = 'workspace-race'
        """
    )
    assert len(race_rows) == 1
    assert race_rows[0]["revision"] == 1


async def _assert_downgrade(connection: asyncpg.Connection, *, schema: str) -> None:
    _migration, downgrade_calls = _capture_migration_execute_calls(downgrade=True)
    for operation in downgrade_calls:
        await connection.execute(str(operation))
    function_count = await connection.fetchval(
        """
        SELECT count(*)
        FROM pg_proc
        JOIN pg_namespace ON pg_namespace.oid = pg_proc.pronamespace
        WHERE pg_namespace.nspname = $1
          AND pg_proc.proname LIKE 'bump_workspace_collaboration_authority%'
        """,
        schema,
    )
    assert function_count == 0


@pytest.mark.integration
async def test_postgresql_backfill_worker_triggers_and_concurrent_first_write() -> None:
    migration, upgrade_calls = _capture_migration_execute_calls()
    schema = f"workspace_authority_{uuid.uuid4().hex}"
    connection = await asyncpg.connect(_dsn())
    try:
        await _create_minimal_authority_schema(
            connection,
            schema=schema,
            direct_tables=migration._WORKSPACE_CHILD_TABLES,
        )
        await _install_upgrade_and_assert_backfill(connection, upgrade_calls)
        await _assert_worker_trigger_revisions(connection)
        await _assert_concurrent_first_write(connection, schema=schema)
        await _assert_downgrade(connection, schema=schema)
    finally:
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await connection.close()
