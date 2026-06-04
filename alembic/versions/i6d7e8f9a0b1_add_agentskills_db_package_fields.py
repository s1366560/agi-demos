"""add agentskills db package fields

Revision ID: i6d7e8f9a0b1
Revises: h5c6d7e8f9a0
Create Date: 2026-06-04

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "i6d7e8f9a0b1"
down_revision: str | Sequence[str] | None = "h5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist complete AgentSkills.io package metadata on DB skills."""
    bind = op.get_bind()
    bind.exec_driver_sql("SET LOCAL lock_timeout = '10s'")

    op.add_column("skills", sa.Column("resource_files", sa.JSON(), nullable=True))
    op.add_column("skills", sa.Column("license", sa.String(length=200), nullable=True))
    op.add_column("skills", sa.Column("compatibility", sa.String(length=500), nullable=True))
    op.add_column("skills", sa.Column("allowed_tools_raw", sa.Text(), nullable=True))
    op.add_column(
        "skills",
        sa.Column("spec_version", sa.String(length=32), server_default="1.0", nullable=False),
    )

    bind.execute(
        sa.text(
            """
            UPDATE skills
            SET
                license = COALESCE(license, metadata_json #>> '{agentskills,license}'),
                compatibility = COALESCE(
                    compatibility,
                    metadata_json #>> '{agentskills,compatibility}'
                ),
                allowed_tools_raw = COALESCE(
                    allowed_tools_raw,
                    metadata_json #>> '{agentskills,allowed_tools}'
                ),
                spec_version = COALESCE(
                    NULLIF(metadata_json #>> '{agentskills,spec_version}', ''),
                    spec_version,
                    '1.0'
                )
            WHERE metadata_json IS NOT NULL
            """
        )
    )

    bind.execute(
        sa.text(
            """
            WITH latest AS (
                SELECT DISTINCT ON (skill_id)
                    skill_id,
                    resource_files
                FROM skill_versions
                ORDER BY skill_id, version_number DESC
            )
            UPDATE skills
            SET resource_files = latest.resource_files
            FROM latest
            WHERE skills.id = latest.skill_id
              AND latest.resource_files IS NOT NULL
            """
        )
    )

    bind.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY tenant_id, scope, name
                        ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST, id DESC
                    ) AS rn
                FROM skills
                WHERE project_id IS NULL
            )
            UPDATE skills
            SET name = left(name, 55) || '-' || left(id, 8)
            WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
            """
        )
    )
    bind.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY tenant_id, project_id, name
                        ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST, id DESC
                    ) AS rn
                FROM skills
                WHERE project_id IS NOT NULL
            )
            UPDATE skills
            SET name = left(name, 55) || '-' || left(id, 8)
            WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
            """
        )
    )

    op.create_index(
        "uq_skills_tenant_scope_name",
        "skills",
        ["tenant_id", "scope", "name"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
    )
    op.create_index(
        "uq_skills_tenant_project_name",
        "skills",
        ["tenant_id", "project_id", "name"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop AgentSkills.io package metadata columns."""
    bind = op.get_bind()
    bind.exec_driver_sql("SET LOCAL lock_timeout = '10s'")

    op.drop_index("uq_skills_tenant_project_name", table_name="skills")
    op.drop_index("uq_skills_tenant_scope_name", table_name="skills")
    op.drop_column("skills", "spec_version")
    op.drop_column("skills", "allowed_tools_raw")
    op.drop_column("skills", "compatibility")
    op.drop_column("skills", "license")
    op.drop_column("skills", "resource_files")
