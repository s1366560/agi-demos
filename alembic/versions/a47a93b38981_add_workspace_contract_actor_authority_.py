"""Add the append-only Workspace contract actor authority audit.

Revision ID: a47a93b38981
Revises: f43f5cd2fb21
Create Date: 2026-08-30
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "a47a93b38981"
down_revision: str | Sequence[str] | None = "f43f5cd2fb21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE avernet.workspace_contract_actor_resolution_audits (
        audit_id VARCHAR(36) PRIMARY KEY,
        service_principal_id VARCHAR(128) NOT NULL,
        operation_id VARCHAR(256) NOT NULL,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        purpose VARCHAR(32) NOT NULL,
        request_hash CHAR(64) NOT NULL,
        outcome VARCHAR(16) NOT NULL,
        reason VARCHAR(32) NOT NULL,
        resolved_actor_user_id VARCHAR(128),
        resolved_participant_actor_id VARCHAR(256),
        authority_revision BIGINT,
        policy_version VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_workspace_contract_actor_audit_operation
            UNIQUE (service_principal_id, operation_id),
        CONSTRAINT ck_workspace_contract_actor_audit_hash
            CHECK (request_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_workspace_contract_actor_audit_purpose
            CHECK (purpose IN (
                'planner_turn',
                'supervisor_turn',
                'verifier_turn',
                'worktree_turn',
                'iteration_review_turn'
            )),
        CONSTRAINT ck_workspace_contract_actor_audit_outcome
            CHECK (outcome IN ('resolved', 'rejected')),
        CONSTRAINT ck_workspace_contract_actor_audit_reason
            CHECK (reason IN (
                'resolved',
                'scope_unavailable',
                'workspace_inactive',
                'owner_unavailable',
                'owner_ambiguous'
            )),
        CONSTRAINT ck_workspace_contract_actor_audit_revision
            CHECK (authority_revision IS NULL OR authority_revision >= 0),
        CONSTRAINT ck_workspace_contract_actor_audit_resolution
            CHECK (
                (
                    outcome = 'resolved'
                    AND reason = 'resolved'
                    AND resolved_actor_user_id IS NOT NULL
                    AND resolved_participant_actor_id IS NOT NULL
                    AND authority_revision IS NOT NULL
                )
                OR
                (
                    outcome = 'rejected'
                    AND reason <> 'resolved'
                    AND resolved_actor_user_id IS NULL
                    AND resolved_participant_actor_id IS NULL
                )
            )
    )
    """,
    """
    CREATE INDEX ix_avn_workspace_contract_actor_audit_scope
        ON avernet.workspace_contract_actor_resolution_audits
        (tenant_id, project_id, workspace_id, created_at)
    """,
    """
    CREATE OR REPLACE FUNCTION avernet.reject_workspace_contract_actor_audit_mutation()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RAISE EXCEPTION 'Workspace contract actor authority audit is append-only'
            USING ERRCODE = '55000';
    END;
    $$
    """,
    """
    CREATE TRIGGER trg_workspace_contract_actor_audit_append_only
    BEFORE UPDATE OR DELETE
    ON avernet.workspace_contract_actor_resolution_audits
    FOR EACH ROW
    EXECUTE FUNCTION avernet.reject_workspace_contract_actor_audit_mutation()
    """,
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    """
    DROP TRIGGER IF EXISTS trg_workspace_contract_actor_audit_append_only
        ON avernet.workspace_contract_actor_resolution_audits
    """,
    "DROP INDEX IF EXISTS avernet.ix_avn_workspace_contract_actor_audit_scope",
    "DROP TABLE IF EXISTS avernet.workspace_contract_actor_resolution_audits",
    "DROP FUNCTION IF EXISTS avernet.reject_workspace_contract_actor_audit_mutation()",
)


def upgrade() -> None:
    """Create the immutable service-principal actor-resolution authority."""
    for statement in _UPGRADE_DDL:
        op.execute(statement)


def downgrade() -> None:
    """Remove only the contract actor authority audit."""
    for statement in _DOWNGRADE_DDL:
        op.execute(statement)
