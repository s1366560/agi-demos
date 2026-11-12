"""Complete schema changes previously provided only by ORM startup.

Revision ID: c86fa94f00dd
Revises: 37d3b107b19c

Generated with Alembic autogenerate against a complete historical replay, then
reviewed to retain only missing runtime tables/columns and retired authority.
Existing create_all deployments keep their already-present structures and data.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c86fa94f00dd"
down_revision: str | Sequence[str] | None = "37d3b107b19c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Make normal migration replay sufficient for the chat runtime."""
    _event_timeline()
    _runtime_tables()
    _missing_columns()
    # Avernet workspace IDs are authority references, not legacy workspaces IDs.
    if sa.inspect(op.get_bind()).has_table("artifacts"):
        op.execute(
            sa.text("ALTER TABLE artifacts DROP CONSTRAINT IF EXISTS artifacts_workspace_id_fkey")
        )


def _event_timeline() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("agent_execution_events"):
        return
    columns = {column["name"] for column in inspector.get_columns("agent_execution_events")}
    timeline = {"event_time_us", "event_counter"}
    if not timeline.issubset(columns):
        if timeline.intersection(columns) or "sequence_number" not in columns:
            raise RuntimeError("Cannot migrate an incomplete agent event timeline schema")
        op.add_column("agent_execution_events", sa.Column("event_time_us", sa.BigInteger()))
        op.add_column("agent_execution_events", sa.Column("event_counter", sa.Integer()))
        # Preserve legacy sequence order even when timestamps repeat or move
        # backwards. This mirrors the monotonic time/counter runtime protocol.
        op.execute(
            sa.text("""
            WITH monotonic AS (
                SELECT id, conversation_id, sequence_number,
                    MAX(FLOOR(EXTRACT(EPOCH FROM created_at) * 1000000)::bigint)
                    OVER (PARTITION BY conversation_id ORDER BY sequence_number
                          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS time_us
                FROM agent_execution_events
            ), ordered AS (
                SELECT id, time_us,
                    (ROW_NUMBER() OVER (
                        PARTITION BY conversation_id, time_us ORDER BY sequence_number
                    ) - 1)::integer AS counter
                FROM monotonic
            )
            UPDATE agent_execution_events AS event
            SET event_time_us = ordered.time_us, event_counter = ordered.counter
            FROM ordered WHERE event.id = ordered.id
        """)
        )
        op.alter_column("agent_execution_events", "event_time_us", nullable=False)
        op.alter_column("agent_execution_events", "event_counter", nullable=False)
    constraints = {
        item["name"] for item in inspector.get_unique_constraints("agent_execution_events")
    }
    if "uq_agent_events_conv_time" not in constraints:
        op.create_unique_constraint(
            "uq_agent_events_conv_time",
            "agent_execution_events",
            ["conversation_id", "event_time_us", "event_counter"],
        )
    for name, fields in (
        ("ix_agent_events_conv_time", "conversation_id, event_time_us, event_counter"),
        ("ix_agent_events_msg_time", "message_id, event_time_us, event_counter"),
    ):
        op.execute(
            sa.text(f"CREATE INDEX IF NOT EXISTS {name} ON agent_execution_events ({fields})")
        )
    if "sequence_number" in columns:
        op.drop_column("agent_execution_events", "sequence_number")


def _missing_columns() -> None:
    inspector = sa.inspect(op.get_bind())
    additions = {
        "conversations": (
            sa.Column("branch_point_message_id", sa.String(), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
        ),
        "mcp_apps": (
            sa.Column(
                "ui_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
            ),
            sa.Column("resource_mime_type", sa.String(length=100), nullable=True),
            sa.Column("resource_resolved_at", sa.DateTime(timezone=True), nullable=True),
        ),
        "messages": (
            sa.Column("reply_to_id", sa.String(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("original_content", sa.Text(), nullable=True),
            sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        ),
    }
    for table, definitions in additions.items():
        if not inspector.has_table(table):
            continue
        present = {column["name"] for column in inspector.get_columns(table)}
        for definition in definitions:
            if definition.name not in present:
                op.add_column(table, definition)
    if inspector.has_table("messages"):
        op.execute(
            sa.text("CREATE INDEX IF NOT EXISTS ix_messages_reply_to_id ON messages (reply_to_id)")
        )
        if not any(
            foreign_key["constrained_columns"] == ["reply_to_id"]
            for foreign_key in inspector.get_foreign_keys("messages")
        ):
            op.create_foreign_key(
                "messages_reply_to_id_fkey",
                "messages",
                "messages",
                ["reply_to_id"],
                ["id"],
            )


def _runtime_tables() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column(
                "timestamp",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("actor", sa.String(), nullable=True),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("resource_type", sa.String(), nullable=False),
            sa.Column("resource_id", sa.String(), nullable=True),
            sa.Column("tenant_id", sa.String(), nullable=True),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("ip_address", sa.String(), nullable=True),
            sa.Column("user_agent", sa.String(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        for column in ("action", "resource_type", "tenant_id", "timestamp"):
            op.create_index(f"ix_audit_logs_{column}", "audit_logs", [column])
        op.create_index("ix_audit_logs_tenant_action", "audit_logs", ["tenant_id", "action"])
    if (
        inspector.has_table("users")
        and inspector.has_table("tenants")
        and inspector.has_table("projects")
        and not inspector.has_table("prompt_templates")
    ):
        op.create_table(
            "prompt_templates",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("category", sa.String(length=50), nullable=False),
            sa.Column("variables", sa.JSON(), nullable=False),
            sa.Column("is_system", sa.Boolean(), nullable=False),
            sa.Column("usage_count", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "title", name="uq_tenant_template_title"),
        )
        for column in ("category", "project_id", "tenant_id"):
            op.create_index(f"ix_prompt_templates_{column}", "prompt_templates", [column])


def downgrade() -> None:
    """Retained runtime tables stay in place; they are not dropped on the way down."""
    return
