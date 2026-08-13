"""Contracts for the Alembic-owned Avernet Workspace schema."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_BASE_REVISION = "a9c0d1e2f3a4"
_DOMAIN_REVISION = "a0b1c2d3e4f5"
_EXECUTION_REVISION = "e42b8c6d0f53"
_RECOVERY_REVISION = "f53c9d7e1a64"
_IDENTITY_REVISION = "0b64d8e2f375"
_CONTRACT_REVISION = "1c75e9f4a286"
_TOMBSTONE_REVISION = "2d86a0c4b731"
_AGENT_BINDING_REVISION = "3f971b85c2da"
_CONTEXT_RUNTIME_REVISION = "4a82c1e7d9b0"
_MESSAGE_AUTHORITY_REVISION = "5b93d2f8eac1"
_MESSAGE_DELIVERY_REVISION = "6c04e3a7b8d2"
_TASK_DISPATCH_REVISION = "7d15f4b8c9e3"
_OUTBOX_PUBLICATION_REVISION = "8e26a5c9d0f4"
_TOPOLOGY_CONTRACT_REVISION = "9f37c2a1b6d8"
_GENE_CONTRACT_REVISION = "a17c3e5f7b9d"
_FILE_AUTHORITY_REVISION = "b28d4f6a8c0e"
_OBJECTIVE_AUTONOMY_REVISION = "c39e5a7b1d2f"
_AUTHORITY_BACKFILL_REVISION = "727ce1982b0f"
_CONVERSATION_LINK_RELAXATION_REVISION = "e9f0a1b2c3d5"
_TASK_SESSION_SAGA_REVISION = "f0a1b2c3d4e6"

_DOMAIN_TABLES = {
    "workspace_profiles",
    "workspace_members",
    "workspace_agent_policies",
    "workspace_agent_bindings",
    "workspace_tasks",
    "workspace_task_attempts",
    "workspace_task_receipts",
    "workspace_blackboard_posts",
    "workspace_blackboard_replies",
    "workspace_files",
    "workspace_topology_nodes",
    "workspace_topology_edges",
    "workspace_objectives",
    "workspace_genes",
}

_EXECUTION_TABLES = {
    "workspace_authorities",
    "workspace_revision_credentials",
    "workspace_mutation_receipts",
    "workspace_plans",
    "workspace_plan_nodes",
    "workspace_plan_blackboard_entries",
    "workspace_plan_events",
    "workspace_outbox",
    "workspace_pipeline_contracts",
    "workspace_pipeline_runs",
    "workspace_pipeline_stage_runs",
    "workspace_deployments",
    "workspace_agent_runtime_correlations",
    "workspace_execution_terminals",
    "workspace_migration_ledger",
    "workspace_judge_audits",
}

_CONTRACT_TABLES = {
    "project_principal_memberships",
    "workspace_contexts",
    "workspace_context_events",
    "workspace_message_correlations",
}

_CONTEXT_RUNTIME_TABLES = {"workspace_context_outbox"}


class _Recorder:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: Any) -> None:
        self.statements.append(str(statement))


def _repository_root() -> Path:
    return next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "alembic" / "versions").is_dir()
    )


def _load_migration_rehearsal() -> ModuleType:
    path = _repository_root() / "scripts/avernet-bcs/verify-workspace-migration.py"
    spec = importlib.util.spec_from_file_location("verify_workspace_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_migration(revision: str, filename: str) -> ModuleType:
    path = _repository_root() / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"avernet_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _domain_migration() -> ModuleType:
    return _load_migration(
        _DOMAIN_REVISION,
        "a0b1c2d3e4f5_create_avernet_workspace_domain.py",
    )


def _execution_migration() -> ModuleType:
    return _load_migration(
        _EXECUTION_REVISION,
        "e42b8c6d0f53_create_avernet_workspace_execution.py",
    )


def _recovery_migration() -> ModuleType:
    return _load_migration(
        _RECOVERY_REVISION,
        "f53c9d7e1a64_add_avernet_runtime_recovery.py",
    )


def _identity_migration() -> ModuleType:
    return _load_migration(
        _IDENTITY_REVISION,
        "0b64d8e2f375_create_avernet_principal_identity_mirror.py",
    )


def _contract_migration() -> ModuleType:
    return _load_migration(
        _CONTRACT_REVISION,
        "1c75e9f4a286_create_avernet_workspace_contract_gaps.py",
    )


def _outbox_publication_migration() -> ModuleType:
    return _load_migration(
        _OUTBOX_PUBLICATION_REVISION,
        "8e26a5c9d0f4_split_workspace_outbox_publication_attempts.py",
    )


def _topology_contract_migration() -> ModuleType:
    return _load_migration(
        _TOPOLOGY_CONTRACT_REVISION,
        "9f37c2a1b6d8_align_workspace_topology_contract.py",
    )


def _gene_contract_migration() -> ModuleType:
    return _load_migration(
        _GENE_CONTRACT_REVISION,
        "a17c3e5f7b9d_align_workspace_gene_contract.py",
    )


def _file_authority_migration() -> ModuleType:
    return _load_migration(
        _FILE_AUTHORITY_REVISION,
        "b28d4f6a8c0e_add_workspace_file_authority.py",
    )


def _objective_autonomy_migration() -> ModuleType:
    return _load_migration(
        _OBJECTIVE_AUTONOMY_REVISION,
        "c39e5a7b1d2f_add_workspace_objective_autonomy_authority.py",
    )


def _authority_backfill_migration() -> ModuleType:
    return _load_migration(
        _AUTHORITY_BACKFILL_REVISION,
        "727ce1982b0f_backfill_missing_workspace_authorities.py",
    )


def _conversation_link_relaxation_migration() -> ModuleType:
    return _load_migration(
        _CONVERSATION_LINK_RELAXATION_REVISION,
        "e9f0a1b2c3d5_relax_conversation_workspace_links.py",
    )


def _task_session_saga_migration() -> ModuleType:
    return _load_migration(
        _TASK_SESSION_SAGA_REVISION,
        "f0a1b2c3d4e6_add_task_session_saga_journal.py",
    )


def _tombstone_migration() -> ModuleType:
    return _load_migration(
        _TOMBSTONE_REVISION,
        "2d86a0c4b731_add_workspace_profile_tombstones.py",
    )


def _agent_binding_migration() -> ModuleType:
    return _load_migration(
        _AGENT_BINDING_REVISION,
        "3f971b85c2da_harden_workspace_agent_bindings.py",
    )


def _context_runtime_migration() -> ModuleType:
    return _load_migration(
        _CONTEXT_RUNTIME_REVISION,
        "4a82c1e7d9b0_add_workspace_context_runtime_authority.py",
    )


def _message_authority_migration() -> ModuleType:
    return _load_migration(
        _MESSAGE_AUTHORITY_REVISION,
        "5b93d2f8eac1_add_workspace_message_authority.py",
    )


def _message_delivery_migration() -> ModuleType:
    return _load_migration(
        _MESSAGE_DELIVERY_REVISION,
        "6c04e3a7b8d2_add_workspace_message_delivery_outbox.py",
    )


def _task_dispatch_migration() -> ModuleType:
    return _load_migration(
        _TASK_DISPATCH_REVISION,
        "7d15f4b8c9e3_add_workspace_task_dispatch_outbox.py",
    )


def _table_definitions(migration: ModuleType) -> dict[str, str]:
    definitions: dict[str, str] = {}
    for statement in migration._TABLE_DDL:
        match = re.search(r"CREATE TABLE avernet\.([a-z0-9_]+)", statement)
        assert match is not None
        definitions[match.group(1)] = statement
    return definitions


def test_workspace_migrations_form_one_linear_chain() -> None:
    chain = (
        (_domain_migration, _DOMAIN_REVISION, _BASE_REVISION),
        (_execution_migration, _EXECUTION_REVISION, _DOMAIN_REVISION),
        (_recovery_migration, _RECOVERY_REVISION, _EXECUTION_REVISION),
        (_identity_migration, _IDENTITY_REVISION, _RECOVERY_REVISION),
        (_contract_migration, _CONTRACT_REVISION, _IDENTITY_REVISION),
        (_tombstone_migration, _TOMBSTONE_REVISION, _CONTRACT_REVISION),
        (_agent_binding_migration, _AGENT_BINDING_REVISION, _TOMBSTONE_REVISION),
        (_context_runtime_migration, _CONTEXT_RUNTIME_REVISION, _AGENT_BINDING_REVISION),
        (_message_authority_migration, _MESSAGE_AUTHORITY_REVISION, _CONTEXT_RUNTIME_REVISION),
        (_message_delivery_migration, _MESSAGE_DELIVERY_REVISION, _MESSAGE_AUTHORITY_REVISION),
        (_task_dispatch_migration, _TASK_DISPATCH_REVISION, _MESSAGE_DELIVERY_REVISION),
        (_outbox_publication_migration, _OUTBOX_PUBLICATION_REVISION, _TASK_DISPATCH_REVISION),
        (_topology_contract_migration, _TOPOLOGY_CONTRACT_REVISION, _OUTBOX_PUBLICATION_REVISION),
        (_gene_contract_migration, _GENE_CONTRACT_REVISION, _TOPOLOGY_CONTRACT_REVISION),
        (_file_authority_migration, _FILE_AUTHORITY_REVISION, _GENE_CONTRACT_REVISION),
        (_objective_autonomy_migration, _OBJECTIVE_AUTONOMY_REVISION, _FILE_AUTHORITY_REVISION),
        (_authority_backfill_migration, _AUTHORITY_BACKFILL_REVISION, _OBJECTIVE_AUTONOMY_REVISION),
        (
            _conversation_link_relaxation_migration,
            _CONVERSATION_LINK_RELAXATION_REVISION,
            _AUTHORITY_BACKFILL_REVISION,
        ),
        (
            _task_session_saga_migration,
            _TASK_SESSION_SAGA_REVISION,
            _CONVERSATION_LINK_RELAXATION_REVISION,
        ),
    )

    for load_migration, revision, down_revision in chain:
        migration = load_migration()
        assert migration.revision == revision
        assert migration.down_revision == down_revision


def test_conversation_link_relaxation_accepts_only_known_historical_foreign_keys() -> None:
    migration = _conversation_link_relaxation_migration()
    statement = migration._DROP_WORKSPACE_LINK_FOREIGN_KEYS_SQL

    for constraint_name in (
        "fk_conversations_workspace_id",
        "conversations_workspace_id_fkey",
        "fk_conversations_linked_workspace_task_id",
        "conversations_linked_workspace_task_id_fkey",
    ):
        assert constraint_name in statement
    assert "unexpected legacy conversation Workspace FK" in statement
    assert "missing legacy conversation Workspace FK" in statement
    assert "confdeltype = 'n'" in statement
    assert "cardinality(candidate_names) <> 1" in statement

    recorder = _Recorder()
    migration.op = recorder
    migration.upgrade()
    assert recorder.statements == ["SET LOCAL lock_timeout = '10s'", statement]


def test_conversation_link_relaxation_downgrade_restores_canonical_historical_names() -> None:
    migration = _conversation_link_relaxation_migration()
    recorder = _Recorder()
    migration.op = recorder

    migration.downgrade()

    rendered = "\n".join(recorder.statements)
    assert "fk_conversations_workspace_id" in rendered
    assert "fk_conversations_linked_workspace_task_id" in rendered
    assert "conversations_workspace_id_fkey" not in rendered
    assert "cannot restore legacy conversation Workspace FKs" in rendered


def test_task_session_saga_upgrade_is_fail_closed_and_adds_recovery_contract() -> None:
    migration = _task_session_saga_migration()
    foreign_key_statement = migration._DROP_LEGACY_RECEIPT_FOREIGN_KEYS_SQL

    for constraint_name in (
        "fk_task_session_receipts_workspace_id",
        "task_session_creation_receipts_workspace_id_fkey",
        "fk_task_session_receipts_initial_message_id",
        "task_session_creation_receipts_initial_message_id_fkey",
    ):
        assert constraint_name in foreign_key_statement
    assert "unexpected legacy task-session receipt FK" in foreign_key_statement
    assert "ambiguous legacy task-session receipt FK" in foreign_key_statement
    assert "invalid legacy task-session receipt FK" in foreign_key_statement
    assert "cardinality(candidate_names) > 1" in foreign_key_statement
    assert "IF cardinality(candidate_names) = 1" in foreign_key_statement

    recorder = _Recorder()
    migration.op = recorder
    migration.upgrade()

    rendered = "\n".join(recorder.statements)
    assert "core_receipt_id VARCHAR(128)" in rendered
    assert "status VARCHAR(32) NOT NULL DEFAULT 'pending'" in rendered
    assert "last_error TEXT" in rendered
    assert "updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP" in rendered
    for status in ("pending", "core_committed", "completed", "retryable_error"):
        assert status in rendered
    assert "uq_avn_workspace_task_receipts_task_session_scope" in rendered
    assert "tenant_id, project_id, actor_id, idempotency_key" in rendered
    assert "WHERE action = 'create_task_session'" in rendered
    assert "DROP CONSTRAINT uq_workspace_task_receipts_intent" not in rendered


def test_task_session_saga_downgrade_restores_legacy_contract() -> None:
    migration = _task_session_saga_migration()
    recorder = _Recorder()
    migration.op = recorder

    migration.downgrade()

    rendered = "\n".join(recorder.statements)
    assert "cannot restore legacy task-session receipt FKs" in rendered
    assert "fk_task_session_receipts_workspace_id" in rendered
    assert "fk_task_session_receipts_initial_message_id" in rendered
    assert "CREATE TRIGGER trg_task_session_receipt_message_delete" in rendered
    assert "DROP COLUMN core_receipt_id" in rendered
    assert "DROP INDEX avernet.uq_avn_workspace_task_receipts_task_session_scope" in rendered


def test_migration_rehearsal_reconstructs_historical_task_session_receipt_shape() -> None:
    rehearsal = _load_migration_rehearsal()
    rendered = "\n".join(rehearsal._RESTORE_TASK_SESSION_RECEIPT_LEGACY_SHAPE_SQL)

    assert "DROP CONSTRAINT ck_task_session_receipts_status" in rendered
    assert "DROP INDEX ix_task_session_receipts_status_updated" in rendered
    for column in ("core_receipt_id", "status", "last_error", "updated_at"):
        assert f"DROP COLUMN {column}" in rendered
    assert "fk_task_session_receipts_workspace_id" in rendered
    assert "FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE" in rendered
    assert "fk_task_session_receipts_initial_message_id" in rendered
    assert "REFERENCES workspace_messages (id) ON DELETE SET NULL" in rendered


def test_workspace_authority_backfill_is_explicit_idempotent_and_non_destructive() -> None:
    migration = _authority_backfill_migration()
    statement = migration._BACKFILL_SQL

    assert "INSERT INTO avernet.workspace_authorities" in statement
    assert "FROM avernet.workspace_profiles profile" in statement
    assert "LEFT JOIN avernet.workspace_authorities authority" in statement
    assert "WHERE authority.workspace_id IS NULL" in statement
    assert "ON CONFLICT (workspace_id) DO NOTHING" in statement
    assert re.search(r"profile\.project_id,\s+0,", statement) is not None

    recorder = _Recorder()
    migration.op = recorder
    migration.upgrade()
    assert recorder.statements == [statement]
    migration.downgrade()
    assert recorder.statements == [statement]


def test_workspace_task_dispatch_snapshot_is_durable_fenced_and_fail_closed() -> None:
    migration = _task_dispatch_migration()
    upgrade = "\n".join(migration._UPGRADE_DDL)
    downgrade = "\n".join(migration._DOWNGRADE_DDL)

    assert "CREATE TABLE avernet.workspace_task_dispatch_outbox" in upgrade
    for field in (
        "dispatch_id",
        "task_id",
        "attempt_id",
        "plan_id",
        "plan_node_id",
        "user_id",
        "agent_id",
        "workspace_agent_binding_id",
        "bot_uuid",
        "group_id",
        "conversation_id",
        "delivery_request_id",
        "task_title",
        "task_description",
        "attempt_count",
        "max_attempts",
        "next_attempt_at_ms",
        "lease_owner",
        "lease_expires_at_ms",
        "lease_generation",
        "last_error",
        "delivered_at_ms",
        "created_at_ms",
    ):
        assert field in upgrade
    assert "uq_workspace_task_dispatch_delivery" in upgrade
    assert "fk_workspace_task_dispatch_profile" in upgrade
    assert "fk_workspace_task_dispatch_task" in upgrade
    assert "ck_workspace_task_dispatch_status" in upgrade
    assert "ck_workspace_task_dispatch_attempts" in upgrade
    assert "ck_workspace_task_dispatch_timestamps" in upgrade
    assert "ck_workspace_task_dispatch_lease" in upgrade
    assert "ck_workspace_task_dispatch_delivered" in upgrade
    assert "ix_avn_workspace_task_dispatch_ready" in upgrade
    assert "ix_avn_workspace_task_dispatch_lease" in upgrade
    assert "reject_workspace_task_dispatch_snapshot_update" in upgrade
    assert "trg_workspace_task_dispatch_snapshot_immutable" in upgrade
    assert "snapshot columns are immutable" in upgrade

    assert "contains durable dispatch data" in downgrade
    assert downgrade.index("RAISE EXCEPTION") < downgrade.index("DROP TABLE")
    assert downgrade.index("DROP TABLE") < downgrade.index("DROP FUNCTION")

    upgrade_recorder = _Recorder()
    migration.op = upgrade_recorder
    migration.upgrade()
    assert upgrade_recorder.statements == list(migration._UPGRADE_DDL)

    downgrade_recorder = _Recorder()
    migration.op = downgrade_recorder
    migration.downgrade()
    assert downgrade_recorder.statements == list(migration._DOWNGRADE_DDL)


def test_workspace_message_delivery_snapshot_is_durable_fenced_and_fail_closed() -> None:
    migration = _message_delivery_migration()
    upgrade = "\n".join(migration._UPGRADE_DDL)
    downgrade = "\n".join(migration._DOWNGRADE_DDL)

    assert "CREATE TABLE avernet.workspace_message_delivery_outbox" in upgrade
    for field in (
        "bcs_message_id",
        "group_id",
        "target_order",
        "agent_id",
        "bot_uuid",
        "display_name",
        "attempt_count",
        "max_attempts",
        "next_attempt_at_ms",
        "lease_owner",
        "lease_expires_at_ms",
        "last_error",
        "delivered_at_ms",
        "created_at_ms",
    ):
        assert field in upgrade
    assert "PRIMARY KEY (workspace_id, bcs_message_id, agent_id)" in upgrade
    assert "UNIQUE (workspace_id, bcs_message_id, target_order)" in upgrade
    assert "bot_uuid VARCHAR(256) NOT NULL" in upgrade
    assert "fk_workspace_message_delivery_outbox_profile" in upgrade
    assert "fk_workspace_message_delivery_outbox_message" in upgrade
    assert "ck_workspace_message_delivery_outbox_status" in upgrade
    assert "ck_workspace_message_delivery_outbox_attempts" in upgrade
    assert "ck_workspace_message_delivery_outbox_timestamps" in upgrade
    assert "ck_workspace_message_delivery_outbox_lease" in upgrade
    assert "ck_workspace_message_delivery_outbox_delivered" in upgrade
    assert "ix_avn_workspace_message_delivery_ready" in upgrade
    assert "ix_avn_workspace_message_delivery_lease" in upgrade
    assert "reject_workspace_message_delivery_snapshot_update" in upgrade
    assert "trg_workspace_message_delivery_snapshot_immutable" in upgrade
    assert "snapshot columns are immutable" in upgrade

    assert "contains durable delivery data" in downgrade
    assert downgrade.index("RAISE EXCEPTION") < downgrade.index("DROP TABLE")
    assert downgrade.index("DROP TABLE") < downgrade.index("DROP FUNCTION")

    upgrade_recorder = _Recorder()
    migration.op = upgrade_recorder
    migration.upgrade()
    assert upgrade_recorder.statements == list(migration._UPGRADE_DDL)

    downgrade_recorder = _Recorder()
    migration.op = downgrade_recorder
    migration.downgrade()
    assert downgrade_recorder.statements == list(migration._DOWNGRADE_DDL)


def test_workspace_message_authority_is_idempotent_queryable_and_fail_closed() -> None:
    migration = _message_authority_migration()
    upgrade = "\n".join(migration._UPGRADE_DDL)
    downgrade = "\n".join(migration._DOWNGRADE_DDL)

    for field in ("idempotency_key", "request_hash", "event_outbox_id"):
        assert f"ADD COLUMN {field}" in upgrade
    assert "ck_workspace_message_correlations_authority_triplet" in upgrade
    assert "ck_workspace_message_correlations_request_hash" in upgrade
    assert "uq_workspace_message_correlations_idempotency" in upgrade
    assert "UNIQUE (workspace_id, idempotency_key)" in upgrade
    assert "fk_workspace_message_correlations_outbox" in upgrade
    assert "REFERENCES avernet.workspace_outbox (outbox_id)" in upgrade
    assert "USING GIN (mentions_json)" in upgrade

    assert "workspace_message_correlations contains new message authority data" in downgrade
    assert "WHERE idempotency_key IS NOT NULL" in downgrade
    assert "OR request_hash IS NOT NULL" in downgrade
    assert "OR event_outbox_id IS NOT NULL" in downgrade
    assert downgrade.index("RAISE EXCEPTION") < downgrade.index("DROP INDEX")

    upgrade_recorder = _Recorder()
    migration.op = upgrade_recorder
    migration.upgrade()
    assert upgrade_recorder.statements == list(migration._UPGRADE_DDL)

    downgrade_recorder = _Recorder()
    migration.op = downgrade_recorder
    migration.downgrade()
    assert downgrade_recorder.statements == list(migration._DOWNGRADE_DDL)


def test_workspace_context_runtime_authority_is_durable_and_reversible() -> None:
    migration = _context_runtime_migration()
    tables = _table_definitions(migration)
    combined = "\n".join(migration._UPGRADE_DDL)

    assert set(tables) == _CONTEXT_RUNTIME_TABLES
    assert "workspace_context_events must be empty" in combined
    assert "request_hash CHAR(64) NOT NULL" in combined
    assert "ck_workspace_context_events_request_hash" in combined
    assert "ALTER COLUMN tenant_id DROP NOT NULL" in combined
    assert "ALTER COLUMN project_id DROP NOT NULL" in combined
    assert "ADD COLUMN user_id VARCHAR(128)" in combined
    assert "ck_workspace_judge_audits_scope_pair" in combined
    assert "ck_workspace_judge_audits_scope" in combined

    outbox = tables["workspace_context_outbox"]
    for field in (
        "user_id",
        "tenant_id",
        "project_id",
        "event_sequence",
        "payload_json JSONB",
        "metadata_json JSONB",
        "idempotency_key",
        "attempt_count",
        "max_attempts",
        "lease_owner",
        "lease_expires_at",
        "dispatched_at",
    ):
        assert field in outbox
    assert "uq_workspace_context_outbox_intent" in outbox
    assert "uq_workspace_context_outbox_sequence" in outbox
    assert "ck_workspace_context_outbox_status" in outbox
    assert "ck_workspace_context_outbox_lease" in outbox
    assert "ix_avn_ws_context_outbox_ready" in combined
    assert "ix_avn_ws_context_outbox_reclaim" in combined
    assert "trg_workspace_context_outbox_touch_updated_at" in combined

    upgrade_recorder = _Recorder()
    migration.op = upgrade_recorder
    migration.upgrade()
    assert upgrade_recorder.statements == list(migration._UPGRADE_DDL)

    downgrade_recorder = _Recorder()
    migration.op = downgrade_recorder
    migration.downgrade()
    assert downgrade_recorder.statements == list(migration._DOWNGRADE_DDL)


def test_workspace_outbox_publication_budget_is_independent_and_reversible() -> None:
    migration = _outbox_publication_migration()
    upgrade = "\n".join(migration._UPGRADE_DDL)
    downgrade = "\n".join(migration._DOWNGRADE_DDL)

    assert migration.down_revision == _TASK_DISPATCH_REVISION
    assert "ADD COLUMN publication_attempt_count" in upgrade
    assert "ADD COLUMN publication_max_attempts" in upgrade
    assert "ck_workspace_outbox_publication_attempts" in upgrade
    assert "event_type NOT IN" in upgrade
    for event_type in migration._PLAN_RUNTIME_EVENT_TYPES:
        assert event_type in upgrade
    assert "ix_avn_ws_outbox_publication_ready" in upgrade
    assert "DROP COLUMN IF EXISTS publication_attempt_count" in downgrade
    assert "DROP COLUMN IF EXISTS publication_max_attempts" in downgrade

    upgrade_recorder = _Recorder()
    migration.op = upgrade_recorder
    migration.upgrade()
    assert upgrade_recorder.statements == list(migration._UPGRADE_DDL)

    downgrade_recorder = _Recorder()
    migration.op = downgrade_recorder
    migration.downgrade()
    assert downgrade_recorder.statements == list(migration._DOWNGRADE_DDL)


def test_workspace_topology_schema_preserves_nullable_direction_and_legacy_widths() -> None:
    migration = _topology_contract_migration()
    upgrade = "\n".join(migration._UPGRADE_DDL)
    downgrade = "\n".join(migration._DOWNGRADE_DDL)

    assert migration.down_revision == _OUTBOX_PUBLICATION_REVISION
    assert "ref_id TYPE VARCHAR(255)" in upgrade
    assert "status TYPE VARCHAR(32)" in upgrade
    assert "direction DROP NOT NULL" in upgrade
    assert "direction DROP DEFAULT" in upgrade
    assert "SET direction = 'directed'" in downgrade
    assert "direction SET NOT NULL" in downgrade

    upgrade_recorder = _Recorder()
    migration.op = upgrade_recorder
    migration.upgrade()
    assert upgrade_recorder.statements == list(migration._UPGRADE_DDL)

    downgrade_recorder = _Recorder()
    migration.op = downgrade_recorder
    migration.downgrade()
    assert downgrade_recorder.statements == list(migration._DOWNGRADE_DDL)


def test_workspace_gene_schema_preserves_nullable_legacy_update_timestamp() -> None:
    migration = _gene_contract_migration()
    upgrade = "\n".join(migration._UPGRADE_DDL)
    downgrade = "\n".join(migration._DOWNGRADE_DDL)

    assert migration.down_revision == _TOPOLOGY_CONTRACT_REVISION
    assert "updated_at DROP NOT NULL" in upgrade
    assert "updated_at IS NULL" in downgrade
    assert "RAISE EXCEPTION" in downgrade
    assert "updated_at SET NOT NULL" in downgrade
    assert downgrade.index("RAISE EXCEPTION") < downgrade.index("updated_at SET NOT NULL")

    upgrade_recorder = _Recorder()
    migration.op = upgrade_recorder
    migration.upgrade()
    assert upgrade_recorder.statements == list(migration._UPGRADE_DDL)

    downgrade_recorder = _Recorder()
    migration.op = downgrade_recorder
    migration.downgrade()
    assert downgrade_recorder.statements == list(migration._DOWNGRADE_DDL)


def test_workspace_objective_projection_preserves_historical_task_provenance() -> None:
    migration = _objective_autonomy_migration()
    upgrade = "\n".join(migration._UPGRADE_DDL)
    downgrade = "\n".join(migration._DOWNGRADE_DDL)

    assert migration.down_revision == _FILE_AUTHORITY_REVISION
    assert "CREATE TABLE avernet.workspace_objective_task_projections" in upgrade
    assert "fk_workspace_objective_task_projection_objective" not in upgrade
    assert "fk_workspace_objective_task_projection_task" in upgrade
    assert "fk_workspace_objective_task_projection_outbox" in upgrade
    assert "DEFERRABLE INITIALLY DEFERRED" in upgrade
    assert "contains durable data" in downgrade
    assert downgrade.index("RAISE EXCEPTION") < downgrade.index("DROP TABLE")

    upgrade_recorder = _Recorder()
    migration.op = upgrade_recorder
    migration.upgrade()
    assert upgrade_recorder.statements == list(migration._UPGRADE_DDL)

    downgrade_recorder = _Recorder()
    migration.op = downgrade_recorder
    migration.downgrade()
    assert downgrade_recorder.statements == list(migration._DOWNGRADE_DDL)


def test_workspace_agent_binding_migration_enforces_public_geometry_contract() -> None:
    migration = _agent_binding_migration()
    combined = "\n".join(migration._UPGRADE_DDL)

    assert "theme_color TYPE VARCHAR(32)" in combined
    assert "ck_workspace_agent_bindings_hex_pair" in combined
    assert "ck_workspace_agent_bindings_hex_radius" in combined
    assert "uq_workspace_agent_bindings_hex" in combined
    assert "ck_workspace_topology_nodes_hex_pair" in combined
    assert "ck_workspace_topology_nodes_hex_radius" in combined
    assert "uq_workspace_topology_nodes_hex" in combined
    assert "NOT (hex_q = 0 AND hex_r = 0)" in combined

    upgrade_recorder = _Recorder()
    migration.op = upgrade_recorder
    migration.upgrade()
    assert upgrade_recorder.statements == list(migration._UPGRADE_DDL)

    downgrade_recorder = _Recorder()
    migration.op = downgrade_recorder
    migration.downgrade()
    assert downgrade_recorder.statements == list(migration._DOWNGRADE_DDL)


def test_workspace_profile_tombstones_preserve_replay_authority() -> None:
    migration = _tombstone_migration()
    combined = "\n".join(migration._UPGRADE_DDL)

    assert "deleted_at TIMESTAMPTZ" in combined
    assert "deleted_by VARCHAR(128)" in combined
    assert "ck_workspace_profiles_tombstone_actor" in combined
    assert "uq_workspace_profiles_project_name_active" in combined
    assert "WHERE deleted_at IS NULL" in combined
    assert "workspace_outbox" not in combined
    assert "workspace_mutation_receipts" not in combined

    upgrade_recorder = _Recorder()
    migration.op = upgrade_recorder
    migration.upgrade()
    assert upgrade_recorder.statements == list(migration._UPGRADE_DDL)

    downgrade_recorder = _Recorder()
    migration.op = downgrade_recorder
    migration.downgrade()
    assert downgrade_recorder.statements == list(migration._DOWNGRADE_DDL)


def test_contract_gap_tables_are_normalized_scoped_and_queryable() -> None:
    tables = _table_definitions(_contract_migration())

    assert set(tables) == _CONTRACT_TABLES

    membership = tables["project_principal_memberships"]
    for field in (
        "tenant_id",
        "project_id",
        "user_id",
        "participant_actor_id",
        "role",
        "permissions_json",
        "is_active",
        "identity_authority",
        "source_membership_id",
    ):
        assert field in membership

    context = tables["workspace_contexts"]
    assert "revision BIGINT NOT NULL" in context
    assert "fk_workspace_context_membership" in context

    context_event = tables["workspace_context_events"]
    assert "UNIQUE (user_id, idempotency_key)" in context_event
    assert "UNIQUE (user_id, revision)" in context_event

    correlation = tables["workspace_message_correlations"]
    for field in (
        "legacy_message_id",
        "conversation_id",
        "bcs_session_id",
        "bcs_message_id",
        "task_id",
        "plan_node_id",
        "runtime_correlation_id",
        "is_terminal",
    ):
        assert field in correlation
    assert "fk_workspace_message_correlations_profile" in correlation

    combined_ddl = "\n".join(tables.values()).lower()
    assert " extensions " not in combined_ddl
    assert "extension_json" not in combined_ddl


def test_principal_identity_mirror_is_scoped_and_keeps_email_explicit() -> None:
    migration = _identity_migration()
    combined = "\n".join(migration._UPGRADE_DDL)

    for field in (
        "tenant_id",
        "project_id",
        "workspace_id",
        "user_id",
        "participant_actor_id",
        "email",
        "display_name",
        "is_active",
        "identity_authority",
        "source_created_at",
        "source_updated_at",
    ):
        assert field in combined
    assert "fk_workspace_principal_identity_profile" in combined
    assert "fk_workspace_principal_identity_member" in combined
    assert "NEW.updated_at IS NOT DISTINCT FROM OLD.updated_at" in combined
    assert "NEW.gmt_modified IS NOT DISTINCT FROM OLD.gmt_modified" in combined

    upgrade_recorder = _Recorder()
    migration.op = upgrade_recorder
    migration.upgrade()
    assert upgrade_recorder.statements == list(migration._UPGRADE_DDL)

    downgrade_recorder = _Recorder()
    migration.op = downgrade_recorder
    migration.downgrade()
    assert downgrade_recorder.statements == list(migration._DOWNGRADE_DDL)


def test_runtime_recovery_migration_adds_claim_and_callback_authority() -> None:
    migration = _recovery_migration()
    combined = "\n".join(migration._UPGRADE_DDL)

    for field in (
        "user_id",
        "bcs_group_id",
        "provider_id",
        "provider_bot_ref",
        "recovery_lease_owner",
        "recovery_lease_expires_at",
        "recovery_attempt_count",
        "recovery_disposition",
        "callback_completed_at",
        "callback_attempt_count",
    ):
        assert field in combined
    assert "ix_avn_ws_runtime_recovery_ready" in combined

    upgrade_recorder = _Recorder()
    migration.op = upgrade_recorder
    migration.upgrade()
    assert upgrade_recorder.statements == list(migration._UPGRADE_DDL)

    downgrade_recorder = _Recorder()
    migration.op = downgrade_recorder
    migration.downgrade()
    assert downgrade_recorder.statements == list(migration._DOWNGRADE_DDL)


def test_workspace_domain_tables_are_explicit_and_complete() -> None:
    tables = _table_definitions(_domain_migration())

    assert set(tables) == _DOMAIN_TABLES
    assert "role IN ('owner', 'editor', 'viewer')" in tables["workspace_members"]
    assert "bot_uuid" in tables["workspace_agent_bindings"]
    assert "participant_actor_id" in tables["workspace_agent_bindings"]
    assert "content_hash" in tables["workspace_genes"]
    assert "source_version VARCHAR(50) NOT NULL" in tables["workspace_genes"]
    assert "parent_objective_id VARCHAR(128)" in tables["workspace_objectives"]
    assert "progress DOUBLE PRECISION NOT NULL" in tables["workspace_objectives"]
    assert "uploader_type VARCHAR(16) NOT NULL" in tables["workspace_files"]
    assert "source_hex_q INTEGER" in tables["workspace_topology_edges"]

    combined_ddl = "\n".join(tables.values()).lower()
    assert " extensions " not in combined_ddl
    assert "extension_json" not in combined_ddl


def test_workspace_children_carry_tenant_project_and_workspace_scope() -> None:
    tables = {
        **_table_definitions(_domain_migration()),
        **_table_definitions(_execution_migration()),
    }

    for table_name, definition in tables.items():
        if table_name == "workspace_profiles":
            continue
        assert "tenant_id" in definition, table_name
        assert "project_id" in definition, table_name
        assert "workspace_id" in definition, table_name


def test_workspace_execution_tables_preserve_terminal_and_audit_authority() -> None:
    tables = _table_definitions(_execution_migration())

    assert set(tables) == _EXECUTION_TABLES
    terminal = tables["workspace_execution_terminals"]
    assert "terminal_message_id VARCHAR(128) NOT NULL" in terminal
    assert "terminal_event_id VARCHAR(128) NOT NULL" in terminal
    assert "completion_outbox_id VARCHAR(128) NOT NULL" in terminal

    plan_node = tables["workspace_plan_nodes"]
    for field in (
        "parent_id",
        "inputs_schema_json",
        "outputs_schema_json",
        "feature_checkpoint_json",
        "handoff_package_json",
        "recommended_capabilities_json",
        "estimated_effort_json",
        "progress_json",
    ):
        assert field in plan_node

    assert "title VARCHAR(500) NOT NULL" in plan_node
    assert "fk_workspace_plan_nodes_parent" in plan_node
    assert "legacy_status VARCHAR(20)" in tables["workspace_outbox"]

    assert "migration_version VARCHAR(32) NOT NULL" in tables["workspace_migration_ledger"]

    audit = tables["workspace_judge_audits"]
    for field in ("agent_id", "tool_name", "input_json", "output_json", "rationale", "latency_ms"):
        assert field in audit


@pytest.mark.parametrize(
    ("migration_factory", "expected_tables"),
    [
        (_domain_migration, _DOMAIN_TABLES),
        (_execution_migration, _EXECUTION_TABLES),
        (_contract_migration, _CONTRACT_TABLES),
        (_context_runtime_migration, _CONTEXT_RUNTIME_TABLES),
    ],
)
def test_upgrade_and_downgrade_cover_every_declared_table(
    migration_factory: Any,
    expected_tables: set[str],
) -> None:
    migration = migration_factory()
    upgrade_recorder = _Recorder()
    migration.op = upgrade_recorder

    migration.upgrade()

    created = {
        match.group(1)
        for statement in upgrade_recorder.statements
        if (match := re.search(r"CREATE TABLE avernet\.([a-z0-9_]+)", statement))
    }
    assert created == expected_tables

    downgrade_recorder = _Recorder()
    migration.op = downgrade_recorder
    migration.downgrade()

    dropped = {
        match.group(1)
        for statement in downgrade_recorder.statements
        if (match := re.search(r"DROP TABLE IF EXISTS avernet\.([a-z0-9_]+)", statement))
    }
    assert dropped == expected_tables
