#!/usr/bin/env python3
"""Verify Alembic-owned Avernet schema and the Rust PostgreSQL DB contract."""

# pyright: reportImplicitStringConcatenation=false, reportMissingTypeStubs=false
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false

from __future__ import annotations

import argparse
import asyncio
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import asyncpg
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPOSITORY_ROOT))

import src.configuration.config as config_module  # noqa: E402
from alembic import command  # noqa: E402
from scripts import workspace_core_legacy_sentinel as legacy_sentinel  # noqa: E402

_PARENT_REVISION = "b4e6f8a0c2d4"
_CONVERSATION_LINK_PARENT_REVISION = "727ce1982b0f"
_TASK_SESSION_SAGA_PARENT_REVISION = "e9f0a1b2c3d5"
_MESSAGE_DELIVERY_PARENT_REVISION = "5b93d2f8eac1"
_MESSAGE_AUTHORITY_PARENT_REVISION = "4a82c1e7d9b0"
_EXPECTED_TABLES = 73
_EXPECTED_TRIGGERS = 61
_DATABASE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_MESSAGE_POSTGRES_CONTRACT = (
    Path("third_party/avernet-bcs/crates/services/memstack-workspace-store/tests")
    / "postgres_message_contract.rs"
)
_TOPOLOGY_POSTGRES_CONTRACT = (
    Path("third_party/avernet-bcs/crates/services/memstack-workspace-service/tests")
    / "postgres_topology_authority.rs"
)
_TASK_POSTGRES_CONTRACT = (
    Path("third_party/avernet-bcs/crates/services/memstack-workspace-service/tests")
    / "postgres_task_authority.rs"
)
_PLAN_POSTGRES_CONTRACT = (
    Path("third_party/avernet-bcs/crates/services/memstack-workspace-service/tests")
    / "postgres_plan_authority.rs"
)
_GENE_POSTGRES_CONTRACT = (
    Path("third_party/avernet-bcs/crates/services/memstack-workspace-service/tests")
    / "postgres_gene_authority.rs"
)
_BLACKBOARD_POSTGRES_CONTRACT = (
    Path("third_party/avernet-bcs/crates/services/memstack-workspace-service/tests")
    / "postgres_blackboard_authority.rs"
)
_DIAGNOSTICS_POSTGRES_CONTRACT = (
    Path("third_party/avernet-bcs/crates/services/memstack-workspace-service/tests")
    / "postgres_diagnostics_authority.rs"
)
_FILE_POSTGRES_CONTRACT = (
    Path("third_party/avernet-bcs/crates/services/memstack-workspace-service/tests")
    / "postgres_file_authority.rs"
)
_OBJECTIVE_AUTONOMY_POSTGRES_CONTRACT = (
    Path("third_party/avernet-bcs/crates/services/memstack-workspace-service/tests")
    / "postgres_objective_autonomy_authority.rs"
)
_COLLABORATION_POSTGRES_CONTRACT = (
    Path("third_party/avernet-bcs/crates/bootstrap/memstack-workspace-core/tests")
    / "collaboration_mutations_postgres_contract.rs"
)

# Public aliases keep the focused verifier contract stable while the actual
# sentinel implementation remains reusable by the full migration rehearsal.
_LEGACY_WORKSPACE_TABLES = legacy_sentinel.LEGACY_WORKSPACE_TABLES
_legacy_workspace_write_sentinel_sql = legacy_sentinel.write_sentinel_sql
_assert_legacy_workspace_stat_delta = legacy_sentinel.assert_zero_stat_delta


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "--skip-cargo-contract",
        action="store_true",
        help="verify only Alembic upgrade, scope constraints, and downgrade",
    )
    _ = parser.add_argument(
        "--cross-store-only",
        action="store_true",
        help="run only the paired SQLite/PostgreSQL normalized-state contract",
    )
    return parser.parse_args()


async def _create_database(admin_dsn: str, database_name: str) -> None:
    connection = await asyncpg.connect(admin_dsn)
    try:
        exists = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = $1)",
            database_name,
        )
        if exists:
            raise RuntimeError(f"temporary database already exists: {database_name}")
        await connection.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await connection.close()


async def _drop_database(admin_dsn: str, database_name: str) -> None:
    connection = await asyncpg.connect(admin_dsn)
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
    finally:
        await connection.close()


async def _schema_contract(test_dsn: str) -> tuple[int, int, str]:
    connection = await asyncpg.connect(test_dsn)
    try:
        tables = await connection.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'avernet'"
        )
        triggers = await connection.fetchval(
            "SELECT count(*) FROM information_schema.triggers WHERE trigger_schema = 'avernet'"
        )
        revision = await connection.fetchval("SELECT version_num FROM alembic_version")
        return int(tables), int(triggers), str(revision)
    finally:
        await connection.close()


async def _create_legacy_workspace_link_fixtures(test_dsn: str) -> None:
    """Reproduce the legacy FK states consumed by the current Workspace heads."""
    connection = await asyncpg.connect(test_dsn)
    try:
        await connection.execute(
            "CREATE TABLE workspaces (id text PRIMARY KEY);"
            "CREATE TABLE workspace_tasks (id text PRIMARY KEY);"
            "CREATE TABLE workspace_messages (id text PRIMARY KEY);"
            "CREATE TABLE conversations ("
            "id text PRIMARY KEY, workspace_id text, linked_workspace_task_id text, "
            "CONSTRAINT fk_conversations_workspace_id "
            "FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE SET NULL, "
            "CONSTRAINT conversations_linked_workspace_task_id_fkey "
            "FOREIGN KEY (linked_workspace_task_id) "
            "REFERENCES workspace_tasks (id) ON DELETE SET NULL);"
            "CREATE TABLE task_session_creation_receipts ("
            "id text PRIMARY KEY, actor_user_id text NOT NULL, tenant_id text NOT NULL, "
            "project_id text NOT NULL, idempotency_key text NOT NULL, payload_hash text NOT NULL, "
            "workspace_id text NOT NULL, conversation_id text, initial_message_id text, "
            "response_json json NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), "
            "CONSTRAINT fk_task_session_receipts_workspace_id "
            "FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE, "
            "CONSTRAINT task_session_creation_receipts_initial_message_id_fkey "
            "FOREIGN KEY (initial_message_id) "
            "REFERENCES workspace_messages (id) ON DELETE SET NULL)"
        )
    finally:
        await connection.close()


def _current_head(alembic_config: Config) -> str:
    heads = ScriptDirectory.from_config(alembic_config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected one Alembic head, found {heads}")
    return heads[0]


async def _rename_constraint(test_dsn: str, source: str, target: str) -> None:
    if _DATABASE_NAME.fullmatch(source) is None or _DATABASE_NAME.fullmatch(target) is None:
        raise RuntimeError("invalid conversation fixture constraint name")
    connection = await asyncpg.connect(test_dsn)
    try:
        await connection.execute(
            f'ALTER TABLE conversations RENAME CONSTRAINT "{source}" TO "{target}"'
        )
    finally:
        await connection.close()


def _unknown_conversation_link_downgrade_guard(
    alembic_config: Config,
    test_dsn: str,
    head_revision: str,
) -> None:
    canonical_name = "fk_conversations_workspace_id"
    unexpected_name = "unexpected_conversations_workspace_fk"
    asyncio.run(_rename_constraint(test_dsn, canonical_name, unexpected_name))
    try:
        command.upgrade(alembic_config, head_revision)
    except DBAPIError as error:
        if "unexpected legacy conversation Workspace FK" not in str(error.orig):
            raise RuntimeError(
                "conversation Workspace FK guard failed for an unexpected reason"
            ) from error
    else:
        raise RuntimeError("conversation Workspace FK guard accepted an unknown constraint")

    _tables, _triggers, revision = asyncio.run(_schema_contract(test_dsn))
    if revision != _CONVERSATION_LINK_PARENT_REVISION:
        raise RuntimeError(
            "failed conversation Workspace FK upgrade did not preserve its parent revision: "
            f"revision={revision}"
        )
    asyncio.run(_rename_constraint(test_dsn, unexpected_name, canonical_name))


async def _scope_contract(test_dsn: str) -> None:
    connection = await asyncpg.connect(test_dsn)
    try:
        async with connection.transaction():
            await connection.execute(
                "INSERT INTO avernet.workspace_profiles "
                "(workspace_id, tenant_id, project_id, group_id, name, created_by) "
                "VALUES ('ws_contract', 'tenant_a', 'project_a', "
                "'group_contract', 'Contract', 'user_a')"
            )
            await connection.execute(
                "INSERT INTO avernet.workspace_members "
                "(member_id, tenant_id, project_id, workspace_id, user_id, "
                "participant_actor_id, role) VALUES "
                "('member_contract', 'tenant_a', 'project_a', 'ws_contract', "
                "'user_a', 'human:user_a', 'owner')"
            )
            try:
                async with connection.transaction():
                    await connection.execute(
                        "INSERT INTO avernet.workspace_members "
                        "(member_id, tenant_id, project_id, workspace_id, user_id, "
                        "participant_actor_id, role) VALUES "
                        "('member_cross_scope', 'tenant_b', 'project_a', 'ws_contract', "
                        "'user_b', 'human:user_b', 'viewer')"
                    )
            except asyncpg.ForeignKeyViolationError:
                pass
            else:
                raise RuntimeError("cross-tenant workspace member relation was accepted")
    finally:
        await connection.close()


async def _task_session_saga_schema_contract(test_dsn: str) -> None:
    connection = await asyncpg.connect(test_dsn)
    try:
        columns = {
            str(row["column_name"]): (str(row["is_nullable"]), str(row["column_default"]))
            for row in await connection.fetch(
                "SELECT column_name, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND table_name = 'task_session_creation_receipts' "
                "AND column_name = ANY($1::text[])",
                ["core_receipt_id", "status", "last_error", "updated_at"],
            )
        }
        if set(columns) != {"core_receipt_id", "status", "last_error", "updated_at"}:
            raise RuntimeError(f"missing task-session saga journal columns: {columns}")
        if columns["status"][0] != "NO" or "pending" not in columns["status"][1]:
            raise RuntimeError(f"invalid task-session saga status contract: {columns['status']}")
        if columns["updated_at"][0] != "NO" or not columns["updated_at"][1]:
            raise RuntimeError(
                f"invalid task-session saga updated_at contract: {columns['updated_at']}"
            )

        legacy_foreign_keys = await connection.fetchval(
            "SELECT count(*) FROM pg_constraint constraint_record "
            "WHERE constraint_record.conrelid = "
            "'task_session_creation_receipts'::regclass "
            "AND constraint_record.contype = 'f' "
            "AND constraint_record.confrelid = ANY("
            "ARRAY['workspaces'::regclass, 'workspace_messages'::regclass])"
        )
        if legacy_foreign_keys != 0:
            raise RuntimeError("task-session saga journal still has legacy Workspace FKs")

        indexes = {
            str(row["indexname"]): str(row["indexdef"])
            for row in await connection.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'avernet' "
                "AND tablename = 'workspace_task_receipts' "
                "AND indexname = ANY($1::text[])",
                [
                    "uq_workspace_task_receipts_intent",
                    "uq_avn_workspace_task_receipts_task_session_scope",
                ],
            )
        }
        if set(indexes) != {
            "uq_workspace_task_receipts_intent",
            "uq_avn_workspace_task_receipts_task_session_scope",
        }:
            raise RuntimeError(f"missing Workspace receipt uniqueness contracts: {indexes}")
        task_session_index = indexes["uq_avn_workspace_task_receipts_task_session_scope"]
        if (
            "tenant_id, project_id, actor_id, idempotency_key" not in task_session_index
            or "action" not in task_session_index
            or "'create_task_session'" not in task_session_index
        ):
            raise RuntimeError(
                f"invalid task-session receipt scope uniqueness: {task_session_index}"
            )
    finally:
        await connection.close()


async def _task_session_saga_downgrade_contract(test_dsn: str) -> None:
    connection = await asyncpg.connect(test_dsn)
    try:
        columns = {
            str(row["column_name"])
            for row in await connection.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND table_name = 'task_session_creation_receipts' "
                "AND column_name = ANY($1::text[])",
                ["core_receipt_id", "status", "last_error", "updated_at"],
            )
        }
        if columns:
            raise RuntimeError(f"task-session saga columns survived downgrade: {columns}")
        foreign_keys = {
            str(row["conname"])
            for row in await connection.fetch(
                "SELECT conname FROM pg_constraint constraint_record "
                "WHERE constraint_record.conrelid = "
                "'task_session_creation_receipts'::regclass "
                "AND constraint_record.contype = 'f' "
                "AND constraint_record.confrelid = ANY("
                "ARRAY['workspaces'::regclass, 'workspace_messages'::regclass])"
            )
        }
        expected_foreign_keys = {
            "fk_task_session_receipts_workspace_id",
            "fk_task_session_receipts_initial_message_id",
        }
        if foreign_keys != expected_foreign_keys:
            raise RuntimeError(
                f"task-session saga downgrade did not restore legacy FKs: {foreign_keys}"
            )
    finally:
        await connection.close()


async def _objective_autonomy_schema_contract(test_dsn: str) -> None:
    connection = await asyncpg.connect(test_dsn)
    try:
        constraints = {
            str(row["conname"]): (bool(row["condeferrable"]), bool(row["condeferred"]))
            for row in await connection.fetch(
                "SELECT conname, condeferrable, condeferred FROM pg_constraint "
                "WHERE connamespace = 'avernet'::regnamespace "
                "AND conrelid = "
                "'avernet.workspace_objective_task_projections'::regclass"
            )
        }
        if "fk_workspace_objective_task_projection_objective" in constraints:
            raise RuntimeError("Objective projection must preserve deleted Objective provenance")
        outbox_constraint = constraints.get("fk_workspace_objective_task_projection_outbox")
        if outbox_constraint != (True, True):
            raise RuntimeError(
                "Objective projection outbox relation must be initially deferred: "
                f"{outbox_constraint}"
            )
        required = {
            "fk_workspace_objective_task_projection_profile",
            "fk_workspace_objective_task_projection_task",
            "fk_workspace_objective_task_projection_outbox",
            "uq_workspace_objective_task_projection_objective",
            "uq_workspace_objective_task_projection_task",
            "ck_workspace_objective_task_projection_revision",
        }
        missing = required - constraints.keys()
        if missing:
            raise RuntimeError(
                f"missing Objective projection authority constraints: {sorted(missing)}"
            )
    finally:
        await connection.close()


async def _message_authority_schema_contract(test_dsn: str) -> None:
    connection = await asyncpg.connect(test_dsn)
    try:
        columns = {
            str(row["column_name"])
            for row in await connection.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'avernet' "
                "AND table_name = 'workspace_message_correlations' "
                "AND column_name = ANY($1::text[])",
                ["idempotency_key", "request_hash", "event_outbox_id"],
            )
        }
        if columns != {"idempotency_key", "request_hash", "event_outbox_id"}:
            raise RuntimeError(f"missing Workspace message authority columns: {sorted(columns)}")

        constraints = {
            str(row["conname"])
            for row in await connection.fetch(
                "SELECT conname FROM pg_constraint "
                "WHERE connamespace = 'avernet'::regnamespace "
                "AND conrelid = 'avernet.workspace_message_correlations'::regclass "
                "AND conname = ANY($1::text[])",
                [
                    "ck_workspace_message_correlations_authority_triplet",
                    "ck_workspace_message_correlations_request_hash",
                    "uq_workspace_message_correlations_idempotency",
                    "fk_workspace_message_correlations_outbox",
                ],
            )
        }
        expected_constraints = {
            "ck_workspace_message_correlations_authority_triplet",
            "ck_workspace_message_correlations_request_hash",
            "uq_workspace_message_correlations_idempotency",
            "fk_workspace_message_correlations_outbox",
        }
        if constraints != expected_constraints:
            raise RuntimeError(
                "missing Workspace message authority constraints: "
                f"{sorted(expected_constraints - constraints)}"
            )

        index_exists = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_indexes "
            "WHERE schemaname = 'avernet' "
            "AND tablename = 'bcs_messages' "
            "AND indexname = 'ix_avn_bcs_messages_mentions_gin')"
        )
        if not index_exists:
            raise RuntimeError("missing BCS message mention GIN index")
    finally:
        await connection.close()


async def _message_delivery_schema_contract(test_dsn: str) -> None:
    connection = await asyncpg.connect(test_dsn)
    try:
        expected_columns = {
            "tenant_id",
            "project_id",
            "workspace_id",
            "bcs_message_id",
            "group_id",
            "target_order",
            "agent_id",
            "bot_uuid",
            "display_name",
            "status",
            "attempt_count",
            "max_attempts",
            "next_attempt_at_ms",
            "lease_owner",
            "lease_expires_at_ms",
            "last_error",
            "delivered_at_ms",
            "created_at_ms",
        }
        columns = {
            str(row["column_name"])
            for row in await connection.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'avernet' "
                "AND table_name = 'workspace_message_delivery_outbox'"
            )
        }
        if columns != expected_columns:
            raise RuntimeError(
                "unexpected Workspace message delivery columns: "
                f"missing={sorted(expected_columns - columns)}, "
                f"extra={sorted(columns - expected_columns)}"
            )
        bot_uuid_width = await connection.fetchval(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_schema = 'avernet' "
            "AND table_name = 'workspace_message_delivery_outbox' "
            "AND column_name = 'bot_uuid'"
        )
        if bot_uuid_width != 256:
            raise RuntimeError(
                "Workspace message delivery bot_uuid does not preserve the source width"
            )

        expected_constraints = {
            "pk_workspace_message_delivery_outbox",
            "uq_workspace_message_delivery_outbox_order",
            "fk_workspace_message_delivery_outbox_profile",
            "fk_workspace_message_delivery_outbox_message",
            "ck_workspace_message_delivery_outbox_status",
            "ck_workspace_message_delivery_outbox_attempts",
            "ck_workspace_message_delivery_outbox_timestamps",
            "ck_workspace_message_delivery_outbox_lease",
            "ck_workspace_message_delivery_outbox_delivered",
        }
        constraints = {
            str(row["conname"])
            for row in await connection.fetch(
                "SELECT conname FROM pg_constraint "
                "WHERE connamespace = 'avernet'::regnamespace "
                "AND conrelid = 'avernet.workspace_message_delivery_outbox'::regclass"
            )
        }
        if constraints != expected_constraints:
            raise RuntimeError(
                "unexpected Workspace message delivery constraints: "
                f"missing={sorted(expected_constraints - constraints)}, "
                f"extra={sorted(constraints - expected_constraints)}"
            )

        expected_indexes = {
            "ix_avn_workspace_message_delivery_ready",
            "ix_avn_workspace_message_delivery_lease",
            "pk_workspace_message_delivery_outbox",
            "uq_workspace_message_delivery_outbox_order",
        }
        indexes = {
            str(row["indexname"])
            for row in await connection.fetch(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'avernet' "
                "AND tablename = 'workspace_message_delivery_outbox'"
            )
        }
        if indexes != expected_indexes:
            raise RuntimeError(
                "unexpected Workspace message delivery indexes: "
                f"missing={sorted(expected_indexes - indexes)}, "
                f"extra={sorted(indexes - expected_indexes)}"
            )

        immutable_trigger = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.triggers "
            "WHERE trigger_schema = 'avernet' "
            "AND event_object_table = 'workspace_message_delivery_outbox' "
            "AND trigger_name = 'trg_workspace_message_delivery_snapshot_immutable')"
        )
        if not immutable_trigger:
            raise RuntimeError("missing Workspace message delivery immutable snapshot trigger")
    finally:
        await connection.close()


async def _seed_message_delivery(test_dsn: str) -> None:
    connection = await asyncpg.connect(test_dsn)
    try:
        async with connection.transaction():
            await connection.execute(
                "INSERT INTO avernet.bcs_messages "
                "(message_id, group_id, session_id, session_seq, env, sender_id, "
                "sender_type, message_type, content, created_at, workspace_id) VALUES "
                "('bcs_message_delivery_contract', 'group_contract', "
                "'session_delivery_contract', 1, 'prod', 'human:user_a', "
                "'human', 'chat', 'Delivery contract', 1, 'ws_contract')"
            )
            await connection.execute(
                "INSERT INTO avernet.workspace_message_delivery_outbox "
                "(tenant_id, project_id, workspace_id, bcs_message_id, group_id, "
                "target_order, agent_id, bot_uuid, display_name, next_attempt_at_ms, "
                "created_at_ms) VALUES "
                "('tenant_a', 'project_a', 'ws_contract', "
                "'bcs_message_delivery_contract', 'group_contract', 0, "
                "'agent_delivery_contract', 'bot_delivery_contract', "
                "'Delivery Contract', 1, 1)"
            )
            try:
                async with connection.transaction():
                    await connection.execute(
                        "UPDATE avernet.workspace_message_delivery_outbox "
                        "SET display_name = 'Tampered Contract' "
                        "WHERE workspace_id = 'ws_contract' "
                        "AND bcs_message_id = 'bcs_message_delivery_contract' "
                        "AND agent_id = 'agent_delivery_contract'"
                    )
            except asyncpg.RaiseError as error:
                if "snapshot columns are immutable" not in str(error):
                    raise RuntimeError(
                        "message delivery snapshot update failed unexpectedly"
                    ) from error
            else:
                raise RuntimeError("message delivery immutable snapshot update was accepted")
    finally:
        await connection.close()


async def _clear_message_delivery(test_dsn: str) -> None:
    connection = await asyncpg.connect(test_dsn)
    try:
        async with connection.transaction():
            await connection.execute(
                "DELETE FROM avernet.workspace_message_delivery_outbox "
                "WHERE workspace_id = 'ws_contract' "
                "AND bcs_message_id = 'bcs_message_delivery_contract' "
                "AND agent_id = 'agent_delivery_contract'"
            )
            await connection.execute(
                "DELETE FROM avernet.bcs_messages "
                "WHERE message_id = 'bcs_message_delivery_contract'"
            )
    finally:
        await connection.close()


def _message_delivery_downgrade_guard(
    alembic_config: Config,
    test_dsn: str,
    head_revision: str,
) -> None:
    asyncio.run(_seed_message_delivery(test_dsn))
    try:
        command.downgrade(alembic_config, _MESSAGE_DELIVERY_PARENT_REVISION)
    except DBAPIError as error:
        if "contains durable delivery data" not in str(error.orig):
            raise RuntimeError(
                "message delivery downgrade failed for an unexpected reason"
            ) from error
    else:
        raise RuntimeError("message delivery downgrade accepted durable delivery data")

    tables, triggers, revision = asyncio.run(_schema_contract(test_dsn))
    if (tables, triggers, revision) != (
        _EXPECTED_TABLES,
        _EXPECTED_TRIGGERS,
        head_revision,
    ):
        raise RuntimeError(
            "failed message delivery downgrade did not preserve the schema head: "
            f"tables={tables}, triggers={triggers}, revision={revision}"
        )
    asyncio.run(_clear_message_delivery(test_dsn))


async def _seed_message_authority(test_dsn: str) -> None:
    connection = await asyncpg.connect(test_dsn)
    try:
        async with connection.transaction():
            await connection.execute(
                "INSERT INTO avernet.workspace_outbox "
                "(outbox_id, tenant_id, project_id, workspace_id, aggregate_type, "
                "aggregate_id, event_type, stream_name, event_sequence, payload_json, "
                "metadata_json, idempotency_key) VALUES "
                "('outbox_message_authority', 'tenant_a', 'project_a', 'ws_contract', "
                "'message', 'message_authority', 'workspace_message_created', "
                "'workspace:ws_contract:messages', 4611686018427387905, '{}'::jsonb, "
                "'{}'::jsonb, 'message-authority-contract')"
            )
            await connection.execute(
                "INSERT INTO avernet.workspace_message_correlations "
                "(correlation_id, tenant_id, project_id, workspace_id, legacy_message_id, "
                "conversation_id, bcs_session_id, bcs_message_id, message_kind, "
                "idempotency_key, request_hash, event_outbox_id) VALUES "
                "('correlation_message_authority', 'tenant_a', 'project_a', 'ws_contract', "
                "'legacy_message_authority', 'conversation_message_authority', "
                "'session_message_authority', 'bcs_message_authority', 'chat', "
                "'message-authority-contract', "
                "'0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef', "
                "'outbox_message_authority')"
            )
    finally:
        await connection.close()


async def _clear_message_authority(test_dsn: str) -> None:
    connection = await asyncpg.connect(test_dsn)
    try:
        async with connection.transaction():
            await connection.execute(
                "DELETE FROM avernet.workspace_message_correlations "
                "WHERE correlation_id = 'correlation_message_authority'"
            )
            await connection.execute(
                "DELETE FROM avernet.workspace_outbox WHERE outbox_id = 'outbox_message_authority'"
            )
    finally:
        await connection.close()


def _message_authority_downgrade_guard(
    alembic_config: Config,
    test_dsn: str,
    head_revision: str,
) -> None:
    asyncio.run(_seed_message_authority(test_dsn))
    try:
        command.downgrade(alembic_config, _MESSAGE_AUTHORITY_PARENT_REVISION)
    except DBAPIError as error:
        if "contains new message authority data" not in str(error.orig):
            raise RuntimeError(
                "message authority downgrade failed for an unexpected reason"
            ) from error
    else:
        raise RuntimeError("message authority downgrade accepted authoritative message data")

    tables, triggers, revision = asyncio.run(_schema_contract(test_dsn))
    if (tables, triggers, revision) != (
        _EXPECTED_TABLES,
        _EXPECTED_TRIGGERS,
        head_revision,
    ):
        raise RuntimeError(
            "failed message authority downgrade did not preserve the schema head: "
            f"tables={tables}, triggers={triggers}, revision={revision}"
        )
    asyncio.run(_clear_message_authority(test_dsn))


async def _downgrade_contract(test_dsn: str) -> tuple[bool, str]:
    connection = await asyncpg.connect(test_dsn)
    try:
        schema_exists = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = 'avernet')"
        )
        revision = await connection.fetchval("SELECT version_num FROM alembic_version")
        return bool(schema_exists), str(revision)
    finally:
        await connection.close()


def _postgres_dsn(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _cargo_environment(test_url: URL) -> dict[str, str]:
    rust_url = test_url.set(
        drivername="postgresql",
        query={"sslmode": "disable"},
    ).render_as_string(hide_password=False)
    environment = os.environ.copy()
    environment["BCS_TEST_POSTGRES_URL"] = rust_url
    return environment


def _run_ignored_cargo_test(
    repository_root: Path,
    environment: dict[str, str],
    package: str,
    target: str | None,
) -> None:
    command_line = [
        str(repository_root / "scripts" / "avernet-bcs" / "cargo.sh"),
        "test",
        "-p",
        package,
    ]
    command_line.extend(["--test", target] if target is not None else ["--tests"])
    command_line.extend(["--locked", "--", "--ignored", "--test-threads=1"])
    _ = subprocess.run(
        command_line,
        cwd=repository_root,
        env=environment,
        check=True,
    )


def _run_cargo_contract(repository_root: Path, test_url: URL) -> None:
    for contract in (
        _MESSAGE_POSTGRES_CONTRACT,
        _TOPOLOGY_POSTGRES_CONTRACT,
        _TASK_POSTGRES_CONTRACT,
        _PLAN_POSTGRES_CONTRACT,
        _GENE_POSTGRES_CONTRACT,
        _BLACKBOARD_POSTGRES_CONTRACT,
        _DIAGNOSTICS_POSTGRES_CONTRACT,
        _FILE_POSTGRES_CONTRACT,
        _OBJECTIVE_AUTONOMY_POSTGRES_CONTRACT,
        _COLLABORATION_POSTGRES_CONTRACT,
    ):
        contract_path = repository_root / contract
        if not contract_path.is_file():
            raise RuntimeError(
                f"required PostgreSQL Workspace contract is missing: {contract_path}"
            )

    environment = _cargo_environment(test_url)
    contracts: tuple[tuple[str, str | None], ...] = (
        ("bcs-db-postgres", None),
        ("memstack-workspace-core", "collaboration_mutations_postgres_contract"),
        *(
            ("memstack-workspace-service", target)
            for target in (
                "postgres_topology_authority",
                "postgres_task_authority",
                "postgres_plan_authority",
                "postgres_gene_authority",
                "postgres_blackboard_authority",
                "postgres_diagnostics_authority",
                "postgres_file_authority",
                "postgres_objective_autonomy_authority",
            )
        ),
        ("memstack-workspace-store", "postgres_mutation_contract"),
        ("memstack-workspace-store", "postgres_message_contract"),
        ("memstack-workspace-service", "postgres_public_mutations"),
        ("memstack-workspace-service", "postgres_policy_contract"),
        ("memstack-workspace-service", "postgres_context_contract"),
        ("memstack-workspace-service", "postgres_agent_mutations"),
        ("memstack-workspace-core", "outbox_postgres_contract"),
        ("memstack-workspace-core", "runtime_postgres_contract"),
    )
    for package, target in contracts:
        _run_ignored_cargo_test(repository_root, environment, package, target)


def _run_cross_store_contract(repository_root: Path, test_url: URL) -> None:
    _run_ignored_cargo_test(
        repository_root,
        _cargo_environment(test_url),
        "memstack-workspace-store",
        "cross_store_state_contract",
    )


def main() -> None:
    args = _arguments()
    repository_root = _REPOSITORY_ROOT
    database_name = f"avernet_verify_{secrets.token_hex(6)}"
    if _DATABASE_NAME.fullmatch(database_name) is None:
        raise RuntimeError("generated an invalid PostgreSQL database name")

    base_url = make_url(config_module.get_settings().postgres_url)
    admin_dsn = _postgres_dsn(base_url)
    test_url = base_url.set(database=database_name, query={})
    test_dsn = _postgres_dsn(test_url)
    test_settings = config_module.Settings(DATABASE_URL=test_dsn)  # type: ignore[arg-type]

    asyncio.run(_create_database(admin_dsn, database_name))
    try:
        alembic_config = Config(str(repository_root / "alembic.ini"))
        head_revision = _current_head(alembic_config)
        asyncio.run(_create_legacy_workspace_link_fixtures(test_dsn))
        with patch.object(config_module, "get_settings", return_value=test_settings):
            command.stamp(alembic_config, _PARENT_REVISION)
            command.upgrade(alembic_config, _CONVERSATION_LINK_PARENT_REVISION)
            _unknown_conversation_link_downgrade_guard(
                alembic_config,
                test_dsn,
                head_revision,
            )
            command.upgrade(alembic_config, "head")

            tables, triggers, revision = asyncio.run(_schema_contract(test_dsn))
            if (tables, triggers, revision) != (
                _EXPECTED_TABLES,
                _EXPECTED_TRIGGERS,
                head_revision,
            ):
                raise RuntimeError(
                    "unexpected Avernet schema contract: "
                    f"tables={tables}, triggers={triggers}, revision={revision}"
                )
            asyncio.run(_scope_contract(test_dsn))
            asyncio.run(_task_session_saga_schema_contract(test_dsn))
            asyncio.run(_objective_autonomy_schema_contract(test_dsn))
            asyncio.run(_message_authority_schema_contract(test_dsn))
            asyncio.run(_message_delivery_schema_contract(test_dsn))
            if args.cross_store_only:
                _run_cross_store_contract(repository_root, test_url)
                return
            _message_delivery_downgrade_guard(alembic_config, test_dsn, head_revision)
            _message_authority_downgrade_guard(alembic_config, test_dsn, head_revision)
            command.downgrade(alembic_config, _TASK_SESSION_SAGA_PARENT_REVISION)
            asyncio.run(_task_session_saga_downgrade_contract(test_dsn))
            command.upgrade(alembic_config, "head")
            if not args.skip_cargo_contract:
                _run_cargo_contract(repository_root, test_url)

            command.downgrade(alembic_config, _PARENT_REVISION)
            schema_exists, revision = asyncio.run(_downgrade_contract(test_dsn))
            if schema_exists or revision != _PARENT_REVISION:
                raise RuntimeError(
                    "unexpected Avernet downgrade contract: "
                    f"schema_exists={schema_exists}, revision={revision}"
                )
    finally:
        asyncio.run(_drop_database(admin_dsn, database_name))

    cargo_status = "skipped" if args.skip_cargo_contract else "passed"
    print(
        "Avernet PostgreSQL schema verification passed "
        f"(tables={_EXPECTED_TABLES}, triggers={_EXPECTED_TRIGGERS}, "
        f"cargo_contract={cargo_status})"
    )


if __name__ == "__main__":
    main()
