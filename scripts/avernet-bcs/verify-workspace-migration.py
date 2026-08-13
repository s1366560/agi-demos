#!/usr/bin/env python3
"""Run the complete Workspace migration CLI contract in temporary PostgreSQL."""

# pyright: reportImplicitStringConcatenation=false, reportMissingTypeStubs=false
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false

from __future__ import annotations

import asyncio
import json
import re
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
from unittest.mock import patch

import asyncpg
from alembic.config import Config
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPOSITORY_ROOT))

import src.configuration.config as config_module  # noqa: E402
from scripts.workspace_core_legacy_sentinel import (  # noqa: E402
    DISPOSABLE_CLEANUP_CONFIRMATION,
    assert_legacy_workspace_objects_removed,
    assert_write_rejected,
    assert_zero_stat_delta,
    cleanup_disposable_legacy_workspace_tables,
    install_write_sentinel,
    workspace_stats,
)
from src.infrastructure.workspace_core.migration.contracts import (  # noqa: E402
    SOURCE_COLUMN_CONTRACTS,
)
from src.infrastructure.workspace_core.migration.legacy_models import (  # noqa: E402
    legacy_workspace_metadata,
)
from src.infrastructure.workspace_core.migration.model import (  # noqa: E402
    MigrationCommand,
    MigrationError,
    MigrationReport,
    canonical_hash,
    decode_json,
)
from src.infrastructure.workspace_core.migration.service import (  # noqa: E402
    WorkspaceMigrationService,
)

if TYPE_CHECKING:
    from sqlalchemy.sql.schema import Table

_PARENT_REVISION = "b4e6f8a0c2d4"
_DATABASE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_RESTORE_TASK_SESSION_RECEIPT_LEGACY_SHAPE_SQL = (
    """
    ALTER TABLE task_session_creation_receipts
        DROP CONSTRAINT ck_task_session_receipts_status
    """,
    "DROP INDEX ix_task_session_receipts_status_updated",
    """
    ALTER TABLE task_session_creation_receipts
        DROP COLUMN updated_at,
        DROP COLUMN last_error,
        DROP COLUMN status,
        DROP COLUMN core_receipt_id,
        ADD CONSTRAINT fk_task_session_receipts_workspace_id
            FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
        ADD CONSTRAINT fk_task_session_receipts_initial_message_id
            FOREIGN KEY (initial_message_id)
            REFERENCES workspace_messages (id) ON DELETE SET NULL
    """,
    """
CREATE FUNCTION tombstone_task_session_creation_receipt()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_TABLE_NAME = 'conversations' THEN
        UPDATE task_session_creation_receipts
        SET conversation_id = NULL,
            initial_message_id = NULL,
            response_json = json_build_object('tombstone', true)
        WHERE conversation_id = OLD.id;
    ELSIF TG_TABLE_NAME = 'workspace_messages' THEN
        UPDATE task_session_creation_receipts
        SET conversation_id = NULL,
            initial_message_id = NULL,
            response_json = json_build_object('tombstone', true)
        WHERE initial_message_id = OLD.id;
    END IF;
    RETURN OLD;
END;
$$
    """,
    """
CREATE TRIGGER trg_task_session_receipt_conversation_delete
BEFORE DELETE ON conversations
FOR EACH ROW
EXECUTE FUNCTION tombstone_task_session_creation_receipt()
    """,
    """
CREATE TRIGGER trg_task_session_receipt_message_delete
BEFORE DELETE ON workspace_messages
FOR EACH ROW
EXECUTE FUNCTION tombstone_task_session_creation_receipt()
    """,
)


def _postgres_dsn(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


async def _create_database(admin_dsn: str, database_name: str) -> None:
    connection = await asyncpg.connect(admin_dsn)
    try:
        _ = await connection.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await connection.close()


async def _drop_database(admin_dsn: str, database_name: str) -> None:
    connection = await asyncpg.connect(admin_dsn)
    try:
        _ = await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
    finally:
        await connection.close()


def _legacy_tables() -> list[Table]:
    selected = {
        legacy_workspace_metadata.tables[name]
        for name in (*SOURCE_COLUMN_CONTRACTS, "task_session_creation_receipts")
    }
    pending = list(selected)
    while pending:
        table = pending.pop()
        for foreign_key in table.foreign_keys:
            dependency = foreign_key.column.table
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    return [table for table in legacy_workspace_metadata.sorted_tables if table in selected]


async def _create_legacy_schema(test_url: URL) -> None:
    engine = create_async_engine(
        test_url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
    )
    try:
        async with engine.begin() as connection:
            tables = _legacy_tables()
            await connection.run_sync(
                lambda sync_connection: legacy_workspace_metadata.create_all(
                    sync_connection,
                    tables=tables,
                )
            )
            await connection.exec_driver_sql(
                "ALTER TABLE conversations ADD CONSTRAINT fk_conversations_workspace_id "
                "FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE SET NULL"
            )
            await connection.exec_driver_sql(
                "ALTER TABLE conversations "
                "ADD CONSTRAINT fk_conversations_linked_workspace_task_id "
                "FOREIGN KEY (linked_workspace_task_id) "
                "REFERENCES workspace_tasks (id) ON DELETE SET NULL"
            )
            # Offline metadata reflects the current saga journal. Reconstruct the
            # exact pre-f0a1b2c3d4e6 shape before stamping the historical parent
            # so the rehearsal cannot pass by pretending current ORM is legacy.
            for statement in _RESTORE_TASK_SESSION_RECEIPT_LEGACY_SHAPE_SQL:
                await connection.exec_driver_sql(statement)
    finally:
        await engine.dispose()


async def _insert_fixture(test_url: URL) -> None:
    engine = create_async_engine(
        test_url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
    )
    now = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)
    table = legacy_workspace_metadata.tables
    try:
        async with engine.begin() as connection:
            _ = await connection.execute(
                table["users"]
                .insert()
                .values(
                    id="user-owner",
                    email="owner@example.invalid",
                    hashed_password="not-a-real-password-hash",
                    full_name="Workspace Owner",
                    is_active=True,
                    is_superuser=False,
                    must_change_password=False,
                    profile={},
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["tenants"]
                .insert()
                .values(
                    id="tenant-1",
                    name="Tenant One",
                    slug="tenant-one",
                    owner_id="user-owner",
                    plan="enterprise",
                    max_projects=100,
                    max_users=100,
                    max_storage=10_000_000,
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["projects"]
                .insert()
                .values(
                    id="project-1",
                    tenant_id="tenant-1",
                    name="Project One",
                    owner_id="user-owner",
                    memory_rules={},
                    graph_config={},
                    sandbox_type="local",
                    sandbox_config={},
                    is_public=False,
                    agent_conversation_mode="workspace",
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["user_projects"]
                .insert()
                .values(
                    id="project-membership-1",
                    user_id="user-owner",
                    project_id="project-1",
                    role="owner",
                    permissions={"workspace:create": True},
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["agent_definitions"]
                .insert()
                .values(
                    id="agent-1",
                    tenant_id="tenant-1",
                    project_id="project-1",
                    name="builder",
                    display_name="Builder",
                    system_prompt="Build the requested change.",
                    model="test-model",
                    allowed_tools=[],
                    allowed_skills=[],
                    allowed_mcp_servers=[],
                    max_tokens=4096,
                    temperature=0.2,
                    max_iterations=10,
                    can_spawn=False,
                    max_spawn_depth=0,
                    agent_to_agent_enabled=False,
                    discoverable=True,
                    source="custom",
                    enabled=True,
                    max_retries=1,
                    total_invocations=0,
                    avg_execution_time_ms=0,
                    success_rate=0,
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspaces"]
                .insert()
                .values(
                    id="workspace-1",
                    tenant_id="tenant-1",
                    project_id="project-1",
                    name="Migration Workspace",
                    description="Full migration contract fixture",
                    created_by="user-owner",
                    is_archived=False,
                    metadata_json={"fixture": True},
                    office_status="active",
                    hex_layout_config_json={"radius": 3},
                    default_blocking_categories_json=["security"],
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_members"]
                .insert()
                .values(
                    id="member-1",
                    workspace_id="workspace-1",
                    user_id="user-owner",
                    role="owner",
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_agent_policies"]
                .insert()
                .values(
                    workspace_id="workspace-1",
                    tenant_id="tenant-1",
                    project_id="project-1",
                    revision=2,
                    roles_json={"builder": "agent-1"},
                    fallbacks_json=[],
                    reasoning_effort="medium",
                    permission_mode="ask",
                    updated_by="user-owner",
                    created_at=now,
                    updated_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_agents"]
                .insert()
                .values(
                    id="binding-1",
                    workspace_id="workspace-1",
                    agent_id="agent-1",
                    display_name="Builder",
                    description="Fixture worker",
                    config_json={"model": "test-model"},
                    is_active=True,
                    status="idle",
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_tasks"]
                .insert()
                .values(
                    id="task-1",
                    workspace_id="workspace-1",
                    title="Deliver migration",
                    description="Run every migration phase",
                    created_by="user-owner",
                    assignee_agent_id="agent-1",
                    status="in_progress",
                    priority=1,
                    metadata_json={"source": "contract"},
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_task_session_attempts"]
                .insert()
                .values(
                    id="attempt-1",
                    workspace_task_id="task-1",
                    root_goal_task_id="task-1",
                    workspace_id="workspace-1",
                    attempt_number=1,
                    status="running",
                    worker_agent_id="agent-1",
                    leader_agent_id="agent-1",
                    candidate_artifacts_json=[],
                    candidate_verifications_json=[],
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["blackboard_posts"]
                .insert()
                .values(
                    id="post-1",
                    workspace_id="workspace-1",
                    author_id="user-owner",
                    title="Migration note",
                    content="Preserve every field.",
                    status="open",
                    is_pinned=True,
                    metadata_json={"kind": "contract"},
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["blackboard_replies"]
                .insert()
                .values(
                    id="reply-1",
                    post_id="post-1",
                    workspace_id="workspace-1",
                    author_id="user-owner",
                    content="Acknowledged.",
                    metadata_json={},
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["blackboard_files"]
                .insert()
                .values(
                    id="file-1",
                    workspace_id="workspace-1",
                    parent_path="/",
                    name="contract.txt",
                    is_directory=False,
                    file_size=8,
                    content_type="text/plain",
                    storage_key="objects/contract.txt",
                    uploader_type="human",
                    uploader_id="user-owner",
                    uploader_name="Workspace Owner",
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["topology_nodes"].insert(),
                [
                    {
                        "id": "node-source",
                        "workspace_id": "workspace-1",
                        "node_type": "task",
                        "title": "Source",
                        "position_x": 0.0,
                        "position_y": 0.0,
                        "status": "active",
                        "tags_json": [],
                        "data_json": {},
                        "created_at": now,
                    },
                    {
                        "id": "node-target",
                        "workspace_id": "workspace-1",
                        "node_type": "agent",
                        "title": "Target",
                        "position_x": 1.0,
                        "position_y": 1.0,
                        "status": "active",
                        "tags_json": [],
                        "data_json": {},
                        "created_at": now,
                    },
                ],
            )
            _ = await connection.execute(
                table["topology_edges"]
                .insert()
                .values(
                    id="edge-1",
                    workspace_id="workspace-1",
                    source_node_id="node-source",
                    target_node_id="node-target",
                    label="depends",
                    direction="directed",
                    auto_created=False,
                    data_json={},
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["cyber_objectives"].insert(),
                [
                    {
                        "id": "objective-1",
                        "workspace_id": "workspace-1",
                        "title": "Migrate",
                        "obj_type": "objective",
                        "progress": 0.5,
                        "created_by": "user-owner",
                        "created_at": now,
                    },
                    {
                        "id": "objective-kr-1",
                        "workspace_id": "workspace-1",
                        "title": "Verify",
                        "obj_type": "key_result",
                        "parent_id": "objective-1",
                        "progress": 1.0,
                        "created_by": "user-owner",
                        "created_at": now,
                    },
                ],
            )
            _ = await connection.execute(
                table["cyber_genes"]
                .insert()
                .values(
                    id="gene-1",
                    workspace_id="workspace-1",
                    name="Migration Gene",
                    category="skill",
                    config_json='{"safe":true}',
                    version="1.2.3",
                    is_active=True,
                    created_by="user-owner",
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_messages"]
                .insert()
                .values(
                    id="message-1",
                    workspace_id="workspace-1",
                    sender_id="user-owner",
                    sender_type="human",
                    content="Start migration",
                    mentions_json=["binding-1"],
                    metadata_json={"channel": "workspace"},
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_collaboration_authorities"]
                .insert()
                .values(
                    workspace_id="workspace-1",
                    tenant_id="tenant-1",
                    project_id="project-1",
                    revision=4,
                    created_at=now,
                    updated_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_collaboration_mutation_receipts"]
                .insert()
                .values(
                    id="receipt-1",
                    tenant_id="tenant-1",
                    project_id="project-1",
                    workspace_id="workspace-1",
                    actor_user_id="user-owner",
                    contract_version="v1",
                    surface="task",
                    action="update",
                    idempotency_key="fixture-receipt",
                    request_hash="0" * 64,
                    expected_revision=3,
                    committed_revision=4,
                    created_at=now,
                    committed_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_plans"]
                .insert()
                .values(
                    id="plan-1",
                    workspace_id="workspace-1",
                    goal_id="task-1",
                    status="running",
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_plan_nodes"]
                .insert()
                .values(
                    id="plan-node-1",
                    plan_id="plan-1",
                    kind="task",
                    title="Execute migration",
                    description="Run the migration CLI",
                    depends_on=[],
                    inputs_schema={},
                    outputs_schema={},
                    acceptance_criteria=[],
                    recommended_capabilities=[],
                    estimated_effort={"minutes": 5},
                    priority=1,
                    intent="todo",
                    execution="running",
                    progress={"percent": 50},
                    assignee_agent_id="agent-1",
                    workspace_task_id="task-1",
                    metadata_json={},
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_plan_blackboard_entries"]
                .insert()
                .values(
                    id="plan-entry-1",
                    plan_id="plan-1",
                    key="migration.contract",
                    value_json={"ready": True},
                    published_by="agent-1",
                    version=1,
                    schema_ref="urn:memstack:migration-contract",
                    metadata_json={},
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_plan_events"]
                .insert()
                .values(
                    id="plan-event-1",
                    plan_id="plan-1",
                    workspace_id="workspace-1",
                    node_id="plan-node-1",
                    event_type="node_started",
                    source="system",
                    payload_json={},
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_plan_outbox"]
                .insert()
                .values(
                    id="plan-outbox-1",
                    plan_id="plan-1",
                    workspace_id="workspace-1",
                    event_type="plan_updated",
                    payload_json={"plan_id": "plan-1"},
                    status="processed",
                    attempt_count=1,
                    max_attempts=5,
                    processed_at=now,
                    metadata_json={},
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_blackboard_outbox"]
                .insert()
                .values(
                    id="blackboard-outbox-1",
                    workspace_id="workspace-1",
                    tenant_id="tenant-1",
                    project_id="project-1",
                    event_type="post_created",
                    payload_json={"post_id": "post-1"},
                    metadata_json={},
                    status="pending",
                    attempt_count=0,
                    max_attempts=5,
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_pipeline_contracts"]
                .insert()
                .values(
                    id="pipeline-contract-1",
                    workspace_id="workspace-1",
                    plan_id="plan-1",
                    provider="sandbox_native",
                    commands_json=["pytest"],
                    env_json={},
                    trigger_policy_json={},
                    timeout_seconds=60,
                    auto_deploy=True,
                    status="active",
                    metadata_json={},
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_pipeline_runs"]
                .insert()
                .values(
                    id="pipeline-run-1",
                    contract_id="pipeline-contract-1",
                    workspace_id="workspace-1",
                    plan_id="plan-1",
                    node_id="plan-node-1",
                    provider="sandbox_native",
                    status="completed",
                    started_at=now,
                    completed_at=now,
                    metadata_json={},
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_pipeline_stage_runs"]
                .insert()
                .values(
                    id="pipeline-stage-1",
                    run_id="pipeline-run-1",
                    workspace_id="workspace-1",
                    stage="test",
                    status="completed",
                    command="pytest",
                    exit_code=0,
                    artifact_refs_json=[],
                    started_at=now,
                    completed_at=now,
                    duration_ms=10,
                    metadata_json={},
                    created_at=now,
                )
            )
            _ = await connection.execute(
                table["workspace_deployments"]
                .insert()
                .values(
                    id="deployment-1",
                    workspace_id="workspace-1",
                    plan_id="plan-1",
                    node_id="plan-node-1",
                    pipeline_run_id="pipeline-run-1",
                    provider="sandbox_native",
                    status="running",
                    pid=123,
                    process_group_id=123,
                    port=8080,
                    required=True,
                    restart_count=0,
                    metadata_json={},
                    created_at=now,
                )
            )
    finally:
        await engine.dispose()


async def _assert_project_membership_projection(
    connection: asyncpg.Connection,
    report: MigrationReport,
) -> None:
    membership_report = next(
        (
            entity
            for entity in report.entities
            if entity.entity_type == "project_principal_membership"
        ),
        None,
    )
    if membership_report is None or (
        membership_report.source_count != 1
        or membership_report.target_primary_key_hash
        != canonical_hash(["tenant-1|project-1|user-owner"])
        or membership_report.content_hash != membership_report.target_content_hash
    ):
        raise RuntimeError("Project membership projection hash mismatch")
    membership = await connection.fetchrow(
        "SELECT user_id, participant_actor_id, source_membership_id, role, "
        "permissions_json, is_active, identity_authority "
        "FROM avernet.project_principal_memberships "
        "WHERE tenant_id = 'tenant-1' AND project_id = 'project-1' "
        "AND user_id = 'user-owner'"
    )
    projected_membership = dict(membership) if membership is not None else None
    if projected_membership is not None:
        projected_membership["permissions_json"] = decode_json(
            projected_membership["permissions_json"], default={}
        )
    if projected_membership != {
        "user_id": "user-owner",
        "participant_actor_id": "user-owner",
        "source_membership_id": "project-membership-1",
        "role": "owner",
        "permissions_json": {"workspace:create": True},
        "is_active": True,
        "identity_authority": "memstack",
    }:
        raise RuntimeError("Project membership projection content mismatch")


async def _migration_contract(test_dsn: str, export_path: Path) -> None:
    connection = await asyncpg.connect(test_dsn)
    try:
        service = WorkspaceMigrationService(connection)
        dry_run = await service.run(MigrationCommand.DRY_RUN, migration_run_id="contract-run")
        if not dry_run.ok or sum(entity.source_count for entity in dry_run.entities) < 30:
            raise RuntimeError(f"migration dry-run failed: {dry_run.to_json()}")

        execute = await service.run(MigrationCommand.EXECUTE, migration_run_id="contract-run")
        if not execute.ok or any(
            entity.source_count != entity.verified_count for entity in execute.entities
        ):
            raise RuntimeError(f"migration execute failed: {execute.to_json()}")

        validate = await service.run(MigrationCommand.VALIDATE, migration_run_id="contract-run")
        if not validate.ok or any(
            entity.source_count != entity.verified_count for entity in validate.entities
        ):
            raise RuntimeError(f"migration validate failed: {validate.to_json()}")

        await _assert_project_membership_projection(connection, validate)

        _ = await connection.execute(
            "UPDATE users SET email = 'owner-updated@example.invalid', "
            "updated_at = '2026-08-10T08:01:00+00:00' WHERE id = 'user-owner'"
        )
        rerun = await service.run(MigrationCommand.EXECUTE, migration_run_id="contract-run")
        if not rerun.ok:
            raise RuntimeError(f"migration idempotency rerun failed: {rerun.to_json()}")
        mirrored_email = await connection.fetchval(
            "SELECT email FROM avernet.workspace_principal_identities "
            "WHERE tenant_id = 'tenant-1' AND project_id = 'project-1' "
            "AND workspace_id = 'workspace-1' AND user_id = 'user-owner'"
        )
        if mirrored_email != "owner-updated@example.invalid":
            raise RuntimeError("incremental migration did not refresh the Principal email mirror")
        bcs_external_name = await connection.fetchval(
            "SELECT external_user_name FROM avernet.bcs_user_identities "
            "WHERE user_id = 'user-owner'"
        )
        if bcs_external_name != "owner-updated@example.invalid":
            raise RuntimeError("incremental migration did not refresh the BCS identity projection")

        reverse = await service.run(
            MigrationCommand.REVERSE_EXPORT,
            migration_run_id="contract-run",
            output_path=export_path,
        )
        exported = [json.loads(line) for line in export_path.read_text().splitlines()]
        if reverse.exported_records != len(exported) or not exported:
            raise RuntimeError("reverse export count mismatch")

        failed_rows = await connection.fetchval(
            "SELECT count(*) FROM avernet.workspace_migration_ledger WHERE status <> 'verified'"
        )
        min_attempts = await connection.fetchval(
            "SELECT min(attempt_count) FROM avernet.workspace_migration_ledger"
        )
        if int(failed_rows) != 0 or int(min_attempts) < 3:
            raise RuntimeError(
                f"migration ledger is not idempotent: failed={failed_rows}, min_attempts={min_attempts}"
            )

        _ = await connection.execute(
            "UPDATE avernet.workspace_tasks SET title = 'tampered' WHERE task_id = 'task-1'"
        )
        try:
            _ = await service.run(MigrationCommand.VALIDATE, migration_run_id="contract-run")
        except MigrationError:
            pass
        else:
            raise RuntimeError("validate accepted a target content mismatch")
    finally:
        await connection.close()


def main() -> None:
    database_name = f"avernet_migrate_{secrets.token_hex(6)}"
    if _DATABASE_NAME.fullmatch(database_name) is None:
        raise RuntimeError("generated an invalid PostgreSQL database name")
    base_url = make_url(config_module.get_settings().postgres_url)
    admin_dsn = _postgres_dsn(base_url)
    test_url = base_url.set(database=database_name, query={})
    test_dsn = _postgres_dsn(test_url)
    test_settings = config_module.Settings(DATABASE_URL=test_dsn)  # type: ignore[arg-type]

    asyncio.run(_create_database(admin_dsn, database_name))
    try:
        asyncio.run(_create_legacy_schema(test_url))
        alembic_config = Config(str(_REPOSITORY_ROOT / "alembic.ini"))
        with patch.object(config_module, "get_settings", return_value=test_settings):
            command.stamp(alembic_config, _PARENT_REVISION)
            command.upgrade(alembic_config, "head")
        asyncio.run(_insert_fixture(test_url))
        with TemporaryDirectory(prefix="avernet-migration-") as directory:
            export_path = Path(directory) / "reverse-export.ndjson"
            asyncio.run(_migration_contract(test_dsn, export_path))
        asyncio.run(install_write_sentinel(test_dsn))
        baseline = asyncio.run(workspace_stats(test_dsn))
        asyncio.run(assert_write_rejected(test_dsn))
        current = asyncio.run(workspace_stats(test_dsn))
        # The deliberate rejected write is a trigger-level probe and cannot mutate
        # the table counters. Any scan or mutation delta means runtime authority leaked.
        assert_zero_stat_delta(baseline, current)
        asyncio.run(
            cleanup_disposable_legacy_workspace_tables(
                test_dsn,
                baseline=current,
                confirm=DISPOSABLE_CLEANUP_CONFIRMATION,
            )
        )
        asyncio.run(assert_legacy_workspace_objects_removed(test_dsn))
    finally:
        asyncio.run(_drop_database(admin_dsn, database_name))
    print("Avernet Workspace migration contract passed")


if __name__ == "__main__":
    main()
