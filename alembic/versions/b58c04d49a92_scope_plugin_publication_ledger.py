"""Scope plugin publication ledger and persist version allocation heads.

Revision ID: b58c04d49a92
Revises: a47a93b38981

Reviewed from isolated PostgreSQL autogenerate output. Scope columns and the
referenced publication key precede composite foreign keys. DDL is frozen here,
independent of the current ORM and protocol implementation.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "b58c04d49a92"
down_revision: str | None = "a47a93b38981"
branch_labels: str | None = None
depends_on: str | None = None

_ROOT = "0c7db1f10e1daaad62b5a58e3cd779dc19ded0fbdd5b44d760e95e9f0fdcb659"
_PUBLICATIONS = "platform_plugin_v2_publications"
_STATES = "platform_plugin_v2_apply_states"
_EVENTS = "platform_plugin_v2_apply_state_events"
_HEADS = "platform_plugin_v2_scope_heads"
_TABLE_LABELS = (
    (_PUBLICATIONS, "publication"),
    (_STATES, "apply"),
    (_EVENTS, "apply_event"),
)
_SHAPE = (
    "(scope_kind = 'root' AND tenant_id IS NULL AND project_id IS NULL "
    "AND session_id IS NULL) OR "
    "(scope_kind = 'tenant' AND tenant_id IS NOT NULL AND project_id IS NULL "
    "AND session_id IS NULL) OR "
    "(scope_kind = 'project' AND tenant_id IS NOT NULL AND project_id IS NOT NULL "
    "AND session_id IS NULL) OR "
    "(scope_kind = 'session' AND tenant_id IS NOT NULL AND project_id IS NOT NULL "
    "AND session_id IS NOT NULL)"
)
_IDS = (
    "(tenant_id IS NULL OR length(trim(tenant_id)) > 0) AND "
    "(project_id IS NULL OR length(trim(project_id)) > 0) AND "
    "(session_id IS NULL OR length(trim(session_id)) > 0)"
)
_CHECKS = (("scope_key", "length(scope_key) = 64"), ("scope_shape", _SHAPE), ("scope_ids", _IDS))
_REFERENCES = (
    (
        _PUBLICATIONS,
        "publication",
        "republished_from_id",
        "fk_platform_plugin_v2_publication_republished_from",
    ),
    (
        _STATES,
        "apply",
        "requested_publication_id",
        "platform_plugin_v2_apply_states_requested_publication_id_fkey",
    ),
    (
        _STATES,
        "apply",
        "applied_publication_id",
        "platform_plugin_v2_apply_states_applied_publication_id_fkey",
    ),
    (
        _EVENTS,
        "apply_event",
        "requested_publication_id",
        "platform_plugin_v2_apply_state_ev_requested_publication_id_fkey",
    ),
    (
        _EVENTS,
        "apply_event",
        "applied_publication_id",
        "platform_plugin_v2_apply_state_even_applied_publication_id_fkey",
    ),
)


def upgrade() -> None:
    """Backfill old rows as ROOT without rewriting nonce, version, or receipt."""
    for table, label in _TABLE_LABELS:
        op.add_column(
            table, sa.Column("scope_key", sa.String(64), nullable=False, server_default=_ROOT)
        )
        op.add_column(
            table, sa.Column("scope_kind", sa.String(16), nullable=False, server_default="root")
        )
        for name in ("tenant_id", "project_id", "session_id"):
            op.add_column(table, sa.Column(name, sa.String(255), nullable=True))
        for suffix, condition in _CHECKS:
            op.create_check_constraint(f"ck_plugin_v2_{label}_{suffix}", table, condition)

    op.create_table(
        _HEADS,
        sa.Column("scope_key", sa.String(64), nullable=False, server_default=_ROOT),
        sa.Column("scope_kind", sa.String(16), nullable=False, server_default="root"),
        sa.Column("tenant_id", sa.String(255), nullable=True),
        sa.Column("project_id", sa.String(255), nullable=True),
        sa.Column("session_id", sa.String(255), nullable=True),
        sa.Column("version_high_watermark", sa.BigInteger(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("scope_key"),
        *(
            sa.CheckConstraint(condition, name=f"ck_plugin_v2_head_{suffix}")
            for suffix, condition in _CHECKS
        ),
        sa.CheckConstraint("version_high_watermark >= 0", name="ck_plugin_v2_head_version"),
    )
    op.execute(
        sa.text(
            f"INSERT INTO {_HEADS} (scope_key, scope_kind, version_high_watermark) "
            f"SELECT '{_ROOT}', 'root', COALESCE(MAX(requested_version), 0) FROM {_PUBLICATIONS}"
        )
    )
    # This key supports ownership FKs; requested_version intentionally stays non-unique.
    op.create_unique_constraint(
        "uq_plugin_v2_publication_scope_id", _PUBLICATIONS, ["scope_key", "id"]
    )
    for table, label, column, old_name in _REFERENCES:
        op.drop_constraint(op.f(old_name), table, type_="foreignkey")
        op.create_foreign_key(
            f"fk_plugin_v2_{label}_{column}",
            table,
            _PUBLICATIONS,
            ["scope_key", column],
            ["scope_key", "id"],
            ondelete="RESTRICT",
        )
    op.drop_constraint(
        op.f("platform_plugin_v2_apply_states_data_plane_id_key"), _STATES, type_="unique"
    )
    op.create_unique_constraint(
        "uq_plugin_v2_apply_scope_plane", _STATES, ["scope_key", "data_plane_id"]
    )
    op.create_index(
        "ix_plugin_v2_publication_scope_latest",
        _PUBLICATIONS,
        ["scope_key", "requested_version", "created_at", "id"],
    )
    op.create_index(
        "ix_plugin_v2_apply_event_scope_plane",
        _EVENTS,
        ["scope_key", "data_plane_id", "recorded_at"],
    )


def downgrade() -> None:
    """Only ROOT-only ledgers can return to the previous global authority schema."""
    # Prevent a scoped insert between the guard and the destructive schema changes.
    op.execute(
        f"LOCK TABLE {_PUBLICATIONS}, {_STATES}, {_EVENTS}, {_HEADS} IN ACCESS EXCLUSIVE MODE"
    )
    for table in (_PUBLICATIONS, _STATES, _EVENTS, _HEADS):
        op.execute(
            sa.text(
                "DO $$ BEGIN IF EXISTS (SELECT 1 FROM "
                + table
                + f" WHERE scope_key <> '{_ROOT}' OR scope_kind <> 'root' "
                "OR tenant_id IS NOT NULL OR project_id IS NOT NULL OR session_id IS NOT NULL) "
                "THEN RAISE EXCEPTION 'scoped plugin ledger downgrade requires ROOT-only data'; "
                "END IF; END $$"
            )
        )
    # All dependants must release the composite key before it can be removed.
    for table, label, column, _old_name in _REFERENCES:
        op.drop_constraint(f"fk_plugin_v2_{label}_{column}", table, type_="foreignkey")
    for table, _label, column, old_name in _REFERENCES:
        op.create_foreign_key(
            op.f(old_name), table, _PUBLICATIONS, [column], ["id"], ondelete="RESTRICT"
        )
    op.drop_constraint("uq_plugin_v2_publication_scope_id", _PUBLICATIONS, type_="unique")
    op.drop_constraint("uq_plugin_v2_apply_scope_plane", _STATES, type_="unique")
    op.create_unique_constraint(
        op.f("platform_plugin_v2_apply_states_data_plane_id_key"), _STATES, ["data_plane_id"]
    )
    op.drop_index("ix_plugin_v2_publication_scope_latest", table_name=_PUBLICATIONS)
    op.drop_index("ix_plugin_v2_apply_event_scope_plane", table_name=_EVENTS)
    for table, label in _TABLE_LABELS:
        for suffix, _condition in _CHECKS:
            op.drop_constraint(f"ck_plugin_v2_{label}_{suffix}", table, type_="check")
        for name in ("session_id", "project_id", "tenant_id", "scope_kind", "scope_key"):
            op.drop_column(table, name)
    op.drop_table(_HEADS)
