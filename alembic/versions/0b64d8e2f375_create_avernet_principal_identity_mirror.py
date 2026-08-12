"""Create the scoped Principal identity mirror used by Workspace Core reads.

Revision ID: 0b64d8e2f375
Revises: f53c9d7e1a64
Create Date: 2026-08-10

The existing identity system remains authoritative. This table is an explicit,
queryable projection for Workspace Core and does not repurpose the upstream BCS
``external_user_name`` field as an email address.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0b64d8e2f375"
down_revision: str | Sequence[str] | None = "f53c9d7e1a64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE avernet.workspace_principal_identities (
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        user_id VARCHAR(128) NOT NULL,
        participant_actor_id VARCHAR(256) NOT NULL,
        email VARCHAR(320) NOT NULL,
        display_name VARCHAR(256),
        is_active BOOLEAN NOT NULL,
        identity_authority VARCHAR(32) NOT NULL,
        source_created_at TIMESTAMPTZ NOT NULL,
        source_updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (tenant_id, project_id, workspace_id, user_id),
        CONSTRAINT fk_workspace_principal_identity_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_principal_identity_member
            FOREIGN KEY (workspace_id, user_id)
            REFERENCES avernet.workspace_members (workspace_id, user_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_principal_identity_actor
            UNIQUE (tenant_id, project_id, workspace_id, participant_actor_id),
        CONSTRAINT ck_workspace_principal_identity_authority
            CHECK (identity_authority = 'memstack')
    )
    """,
    """
    CREATE INDEX ix_avn_ws_principal_identity_email
        ON avernet.workspace_principal_identities
        (tenant_id, project_id, email)
    """,
    """
    CREATE OR REPLACE FUNCTION avernet.touch_updated_at() RETURNS TRIGGER
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.updated_at IS NOT DISTINCT FROM OLD.updated_at THEN
            NEW.updated_at = CURRENT_TIMESTAMP;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION avernet.touch_gmt_modified() RETURNS TRIGGER
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.gmt_modified IS NOT DISTINCT FROM OLD.gmt_modified THEN
            NEW.gmt_modified = CURRENT_TIMESTAMP;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    """
    CREATE OR REPLACE FUNCTION avernet.touch_gmt_modified() RETURNS TRIGGER
    LANGUAGE plpgsql AS $$
    BEGIN
        NEW.gmt_modified = CURRENT_TIMESTAMP;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION avernet.touch_updated_at() RETURNS TRIGGER
    LANGUAGE plpgsql AS $$
    BEGIN
        NEW.updated_at = CURRENT_TIMESTAMP;
        RETURN NEW;
    END;
    $$
    """,
    "DROP INDEX IF EXISTS avernet.ix_avn_ws_principal_identity_email",
    "DROP TABLE IF EXISTS avernet.workspace_principal_identities",
)


def upgrade() -> None:
    for statement in _UPGRADE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_DDL:
        op.execute(statement)
