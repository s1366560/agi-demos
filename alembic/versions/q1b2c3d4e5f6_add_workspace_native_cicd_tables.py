"""add workspace native cicd tables

Revision ID: q1b2c3d4e5f6
Revises: n2b3c4d5e6f7, p3a4b5c6d7e8
Create Date: 2026-04-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "q1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = ("n2b3c4d5e6f7", "p3a4b5c6d7e8")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(
        index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def upgrade() -> None:  # noqa: C901
    if not _has_table("workspace_pipeline_contracts"):
        op.create_table(
            "workspace_pipeline_contracts",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("plan_id", sa.String(), nullable=True),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("code_root", sa.String(), nullable=True),
            sa.Column(
                "commands_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'::json"),
            ),
            sa.Column(
                "env_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column(
                "trigger_policy_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="600"),
            sa.Column("auto_deploy", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("preview_port", sa.Integer(), nullable=True),
            sa.Column("health_url", sa.String(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column(
                "metadata_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["plan_id"], ["workspace_plans.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "workspace_id",
                "plan_id",
                name="uq_workspace_pipeline_contract_workspace_plan",
            ),
        )
    if not _has_index("workspace_pipeline_contracts", "ix_workspace_pipeline_contracts_workspace"):
        op.create_index(
            "ix_workspace_pipeline_contracts_workspace",
            "workspace_pipeline_contracts",
            ["workspace_id"],
        )
    if not _has_index("workspace_pipeline_contracts", "ix_workspace_pipeline_contracts_plan"):
        op.create_index(
            "ix_workspace_pipeline_contracts_plan",
            "workspace_pipeline_contracts",
            ["plan_id"],
        )

    if not _has_table("workspace_pipeline_runs"):
        op.create_table(
            "workspace_pipeline_runs",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("contract_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("plan_id", sa.String(), nullable=True),
            sa.Column("node_id", sa.String(), nullable=True),
            sa.Column("attempt_id", sa.String(), nullable=True),
            sa.Column("commit_ref", sa.String(), nullable=True),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "metadata_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["contract_id"], ["workspace_pipeline_contracts.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["plan_id"], ["workspace_plans.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    for index_name, columns in {
        "ix_workspace_pipeline_runs_workspace_created": ["workspace_id", "created_at"],
        "ix_workspace_pipeline_runs_plan_node": ["plan_id", "node_id"],
        "ix_workspace_pipeline_runs_attempt": ["attempt_id"],
        "ix_workspace_pipeline_runs_status": ["status"],
    }.items():
        if not _has_index("workspace_pipeline_runs", index_name):
            op.create_index(index_name, "workspace_pipeline_runs", columns)

    if not _has_table("workspace_pipeline_stage_runs"):
        op.create_table(
            "workspace_pipeline_stage_runs",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("stage", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("command", sa.Text(), nullable=True),
            sa.Column("exit_code", sa.Integer(), nullable=True),
            sa.Column("stdout_preview", sa.Text(), nullable=True),
            sa.Column("stderr_preview", sa.Text(), nullable=True),
            sa.Column("log_ref", sa.String(), nullable=True),
            sa.Column(
                "artifact_refs_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'::json"),
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column(
                "metadata_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["run_id"], ["workspace_pipeline_runs.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    for index_name, columns in {
        "ix_workspace_pipeline_stage_runs_run": ["run_id"],
        "ix_workspace_pipeline_stage_runs_workspace_status": ["workspace_id", "status"],
    }.items():
        if not _has_index("workspace_pipeline_stage_runs", index_name):
            op.create_index(index_name, "workspace_pipeline_stage_runs", columns)

    if not _has_table("workspace_deployments"):
        op.create_table(
            "workspace_deployments",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("plan_id", sa.String(), nullable=True),
            sa.Column("node_id", sa.String(), nullable=True),
            sa.Column("pipeline_run_id", sa.String(), nullable=True),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("command", sa.Text(), nullable=True),
            sa.Column("pid", sa.Integer(), nullable=True),
            sa.Column("process_group_id", sa.Integer(), nullable=True),
            sa.Column("port", sa.Integer(), nullable=True),
            sa.Column("preview_url", sa.String(), nullable=True),
            sa.Column("health_url", sa.String(), nullable=True),
            sa.Column("restart_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_healthy_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rollback_ref", sa.String(), nullable=True),
            sa.Column("log_ref", sa.String(), nullable=True),
            sa.Column(
                "metadata_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["plan_id"], ["workspace_plans.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["pipeline_run_id"], ["workspace_pipeline_runs.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    for index_name, columns in {
        "ix_workspace_deployments_workspace_created": ["workspace_id", "created_at"],
        "ix_workspace_deployments_plan_node": ["plan_id", "node_id"],
        "ix_workspace_deployments_pipeline_run": ["pipeline_run_id"],
        "ix_workspace_deployments_status": ["status"],
    }.items():
        if not _has_index("workspace_deployments", index_name):
            op.create_index(index_name, "workspace_deployments", columns)


def downgrade() -> None:
    for table_name, indexes in {
        "workspace_deployments": (
            "ix_workspace_deployments_status",
            "ix_workspace_deployments_pipeline_run",
            "ix_workspace_deployments_plan_node",
            "ix_workspace_deployments_workspace_created",
        ),
        "workspace_pipeline_stage_runs": (
            "ix_workspace_pipeline_stage_runs_workspace_status",
            "ix_workspace_pipeline_stage_runs_run",
        ),
        "workspace_pipeline_runs": (
            "ix_workspace_pipeline_runs_status",
            "ix_workspace_pipeline_runs_attempt",
            "ix_workspace_pipeline_runs_plan_node",
            "ix_workspace_pipeline_runs_workspace_created",
        ),
        "workspace_pipeline_contracts": (
            "ix_workspace_pipeline_contracts_plan",
            "ix_workspace_pipeline_contracts_workspace",
        ),
    }.items():
        for index_name in indexes:
            if _has_index(table_name, index_name):
                op.drop_index(index_name, table_name=table_name)
    for table_name in (
        "workspace_deployments",
        "workspace_pipeline_stage_runs",
        "workspace_pipeline_runs",
        "workspace_pipeline_contracts",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)
