"""Add Objective projection and Autonomy tick authority.

Revision ID: c39e5a7b1d2f
Revises: b28d4f6a8c0e
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "c39e5a7b1d2f"
down_revision: str | Sequence[str] | None = "b28d4f6a8c0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE avernet.workspace_objective_task_projections (
        projection_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        objective_id VARCHAR(128) NOT NULL,
        task_id VARCHAR(128) NOT NULL,
        created_by_actor_id VARCHAR(256) NOT NULL,
        committed_revision BIGINT NOT NULL,
        outbox_id VARCHAR(128) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_objective_task_projection_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_objective_task_projection_task
            FOREIGN KEY (tenant_id, project_id, workspace_id, task_id)
            REFERENCES avernet.workspace_tasks (tenant_id, project_id, workspace_id, task_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_objective_task_projection_outbox
            FOREIGN KEY (outbox_id) REFERENCES avernet.workspace_outbox (outbox_id)
            ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED,
        CONSTRAINT uq_workspace_objective_task_projection_objective
            UNIQUE (tenant_id, project_id, workspace_id, objective_id),
        CONSTRAINT uq_workspace_objective_task_projection_task
            UNIQUE (tenant_id, project_id, workspace_id, task_id),
        CONSTRAINT ck_workspace_objective_task_projection_revision
            CHECK (committed_revision > 0)
    )
    """,
    """
    CREATE TABLE avernet.workspace_autonomy_ticks (
        tick_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        root_task_id VARCHAR(128),
        actor_id VARCHAR(256) NOT NULL,
        force BOOLEAN NOT NULL DEFAULT FALSE,
        verdict VARCHAR(24) NOT NULL,
        reason VARCHAR(64) NOT NULL,
        judge_audit_id VARCHAR(128),
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_autonomy_ticks_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_autonomy_ticks_task
            FOREIGN KEY (tenant_id, project_id, workspace_id, root_task_id)
            REFERENCES avernet.workspace_tasks (tenant_id, project_id, workspace_id, task_id)
            ON DELETE SET NULL (root_task_id),
        CONSTRAINT fk_workspace_autonomy_ticks_judge_audit
            FOREIGN KEY (judge_audit_id) REFERENCES avernet.workspace_judge_audits (audit_id)
            ON DELETE RESTRICT,
        CONSTRAINT ck_workspace_autonomy_ticks_verdict
            CHECK (verdict IN ('continue', 'block', 'escalate', 'not_applicable')),
        CONSTRAINT ck_workspace_autonomy_ticks_reason
            CHECK (reason IN (
                'triggered', 'blocked_by_judge', 'escalated_by_judge',
                'no_open_root', 'cooling_down'
            )),
        CONSTRAINT ck_workspace_autonomy_ticks_judge
            CHECK (
                (verdict IN ('continue', 'block', 'escalate') AND judge_audit_id IS NOT NULL)
                OR (verdict = 'not_applicable' AND judge_audit_id IS NULL)
            )
    )
    """,
    """
    CREATE INDEX ix_avn_workspace_objective_task_projections_task
        ON avernet.workspace_objective_task_projections (workspace_id, task_id)
    """,
    """
    CREATE INDEX ix_avn_workspace_autonomy_ticks_root_created
        ON avernet.workspace_autonomy_ticks (workspace_id, root_task_id, created_at DESC)
    """,
    """
    REVOKE ALL ON TABLE avernet.workspace_objective_task_projections FROM PUBLIC
    """,
    """
    REVOKE ALL ON TABLE avernet.workspace_autonomy_ticks FROM PUBLIC
    """,
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM avernet.workspace_autonomy_ticks)
            OR EXISTS (SELECT 1 FROM avernet.workspace_objective_task_projections)
        THEN
            RAISE EXCEPTION
                'Workspace Objective or Autonomy authority contains durable data';
        END IF;
    END
    $$
    """,
    "DROP INDEX IF EXISTS avernet.ix_avn_workspace_autonomy_ticks_root_created",
    "DROP INDEX IF EXISTS avernet.ix_avn_workspace_objective_task_projections_task",
    "DROP TABLE avernet.workspace_autonomy_ticks",
    "DROP TABLE avernet.workspace_objective_task_projections",
)


def upgrade() -> None:
    for statement in _UPGRADE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_DDL:
        op.execute(statement)
