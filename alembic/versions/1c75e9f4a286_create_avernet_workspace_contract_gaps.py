"""Create normalized Workspace identity, context, and message contracts.

Revision ID: 1c75e9f4a286
Revises: 0b64d8e2f375
Create Date: 2026-08-10

The existing identity and Project tables remain authoritative. These tables
are queryable projections and correlation models required before Workspace
Core may own create, context-switch, or message writes.
"""

from collections.abc import Iterable

import sqlalchemy as sa

from alembic import op

revision = "1c75e9f4a286"
down_revision = "0b64d8e2f375"
branch_labels = None
depends_on = None

SCHEMA = "avernet"

_TABLE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE avernet.project_principal_memberships (
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        user_id VARCHAR(128) NOT NULL,
        participant_actor_id VARCHAR(256) NOT NULL,
        source_membership_id VARCHAR(128) NOT NULL,
        role VARCHAR(64) NOT NULL,
        permissions_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        is_active BOOLEAN NOT NULL,
        identity_authority VARCHAR(32) NOT NULL,
        source_created_at TIMESTAMPTZ NOT NULL,
        source_updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (tenant_id, project_id, user_id),
        CONSTRAINT uq_project_principal_membership_actor
            UNIQUE (tenant_id, project_id, participant_actor_id),
        CONSTRAINT uq_project_principal_membership_source
            UNIQUE (source_membership_id),
        CONSTRAINT ck_project_principal_membership_authority
            CHECK (identity_authority = 'memstack')
    )
    """,
    """
    CREATE TABLE avernet.workspace_contexts (
        user_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        revision BIGINT NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_context_membership
            FOREIGN KEY (tenant_id, project_id, user_id)
            REFERENCES avernet.project_principal_memberships
                (tenant_id, project_id, user_id)
            ON DELETE CASCADE,
        CONSTRAINT ck_workspace_context_revision CHECK (revision >= 0)
    )
    """,
    """
    CREATE TABLE avernet.workspace_context_events (
        event_id VARCHAR(128) PRIMARY KEY,
        user_id VARCHAR(128) NOT NULL,
        actor_api_key_id VARCHAR(128),
        from_tenant_id VARCHAR(128),
        from_project_id VARCHAR(128),
        to_tenant_id VARCHAR(128) NOT NULL,
        to_project_id VARCHAR(128) NOT NULL,
        revision BIGINT NOT NULL,
        idempotency_key VARCHAR(256) NOT NULL,
        value_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_context_event_context
            FOREIGN KEY (user_id)
            REFERENCES avernet.workspace_contexts (user_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_context_event_membership
            FOREIGN KEY (to_tenant_id, to_project_id, user_id)
            REFERENCES avernet.project_principal_memberships
                (tenant_id, project_id, user_id),
        CONSTRAINT uq_workspace_context_event_intent
            UNIQUE (user_id, idempotency_key),
        CONSTRAINT uq_workspace_context_event_revision
            UNIQUE (user_id, revision),
        CONSTRAINT ck_workspace_context_event_revision CHECK (revision > 0)
    )
    """,
    """
    CREATE TABLE avernet.workspace_message_correlations (
        correlation_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        legacy_message_id VARCHAR(128) NOT NULL,
        conversation_id VARCHAR(128) NOT NULL,
        bcs_session_id VARCHAR(128) NOT NULL,
        bcs_message_id VARCHAR(128) NOT NULL,
        task_id VARCHAR(128),
        plan_node_id VARCHAR(128),
        runtime_correlation_id VARCHAR(128),
        message_kind VARCHAR(32) NOT NULL,
        is_terminal BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_message_correlations_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles
                (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_message_correlations_legacy
            UNIQUE (workspace_id, legacy_message_id),
        CONSTRAINT uq_workspace_message_correlations_bcs
            UNIQUE (bcs_session_id, bcs_message_id)
    )
    """,
)

_INDEX_DDL: tuple[str, ...] = (
    """
    CREATE INDEX ix_avn_project_principal_membership_user
        ON avernet.project_principal_memberships (tenant_id, user_id, project_id)
    """,
    """
    CREATE INDEX ix_avn_workspace_context_scope
        ON avernet.workspace_contexts (tenant_id, project_id)
    """,
    """
    CREATE INDEX ix_avn_workspace_context_events_user_revision
        ON avernet.workspace_context_events (user_id, revision DESC)
    """,
    """
    CREATE INDEX ix_avn_workspace_message_correlations_conversation
        ON avernet.workspace_message_correlations
            (tenant_id, project_id, workspace_id, conversation_id)
    """,
    """
    CREATE INDEX ix_avn_workspace_message_correlations_runtime
        ON avernet.workspace_message_correlations (runtime_correlation_id)
        WHERE runtime_correlation_id IS NOT NULL
    """,
)

_TRIGGER_DDL: tuple[str, ...] = (
    """
    CREATE TRIGGER trg_workspace_contexts_touch_updated_at
    BEFORE UPDATE ON avernet.workspace_contexts
    FOR EACH ROW EXECUTE FUNCTION avernet.touch_updated_at()
    """,
    """
    CREATE TRIGGER trg_workspace_message_correlations_touch_updated_at
    BEFORE UPDATE ON avernet.workspace_message_correlations
    FOR EACH ROW EXECUTE FUNCTION avernet.touch_updated_at()
    """,
)

_TABLES_IN_DROP_ORDER: tuple[str, ...] = (
    "workspace_message_correlations",
    "workspace_context_events",
    "workspace_contexts",
    "project_principal_memberships",
)


def _execute_all(statements: Iterable[str]) -> None:
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade() -> None:
    _execute_all(_TABLE_DDL)
    _execute_all(_INDEX_DDL)
    _execute_all(_TRIGGER_DDL)


def downgrade() -> None:
    for table_name in _TABLES_IN_DROP_ORDER:
        op.execute(sa.text(f"DROP TABLE IF EXISTS {SCHEMA}.{table_name}"))
