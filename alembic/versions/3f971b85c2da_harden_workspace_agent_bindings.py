"""Harden Workspace Agent binding geometry and public field widths.

Revision ID: 3f971b85c2da
Revises: 2d86a0c4b731
Create Date: 2026-08-11

The Workspace authority serializes geometry writes through the revision row.
These constraints provide a second deterministic guard for Cloud data while
the same checks remain in the shared PostgreSQL/SQLite application service.
"""

from alembic import op

revision = "3f971b85c2da"
down_revision = "2d86a0c4b731"
branch_labels = None
depends_on = None

_UPGRADE_DDL: tuple[str, ...] = (
    """
    ALTER TABLE avernet.workspace_agent_bindings
    ALTER COLUMN theme_color TYPE VARCHAR(32)
    """,
    """
    ALTER TABLE avernet.workspace_agent_bindings
    ADD CONSTRAINT ck_workspace_agent_bindings_hex_pair
    CHECK ((hex_q IS NULL) = (hex_r IS NULL))
    """,
    """
    ALTER TABLE avernet.workspace_agent_bindings
    ADD CONSTRAINT ck_workspace_agent_bindings_hex_radius
    CHECK (
        hex_q IS NULL OR (
            hex_q BETWEEN -24 AND 24
            AND hex_r BETWEEN -24 AND 24
            AND ABS(-(hex_q::BIGINT) - hex_r::BIGINT) <= 24
            AND NOT (hex_q = 0 AND hex_r = 0)
        )
    )
    """,
    """
    CREATE UNIQUE INDEX uq_workspace_agent_bindings_hex
    ON avernet.workspace_agent_bindings (workspace_id, hex_q, hex_r)
    WHERE hex_q IS NOT NULL AND hex_r IS NOT NULL
    """,
    """
    ALTER TABLE avernet.workspace_topology_nodes
    ADD CONSTRAINT ck_workspace_topology_nodes_hex_pair
    CHECK ((hex_q IS NULL) = (hex_r IS NULL))
    """,
    """
    ALTER TABLE avernet.workspace_topology_nodes
    ADD CONSTRAINT ck_workspace_topology_nodes_hex_radius
    CHECK (
        hex_q IS NULL OR (
            hex_q BETWEEN -24 AND 24
            AND hex_r BETWEEN -24 AND 24
            AND ABS(-(hex_q::BIGINT) - hex_r::BIGINT) <= 24
            AND NOT (hex_q = 0 AND hex_r = 0)
        )
    )
    """,
    """
    CREATE UNIQUE INDEX uq_workspace_topology_nodes_hex
    ON avernet.workspace_topology_nodes (workspace_id, hex_q, hex_r)
    WHERE hex_q IS NOT NULL AND hex_r IS NOT NULL
    """,
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP INDEX IF EXISTS avernet.uq_workspace_topology_nodes_hex",
    """
    ALTER TABLE avernet.workspace_topology_nodes
    DROP CONSTRAINT IF EXISTS ck_workspace_topology_nodes_hex_radius
    """,
    """
    ALTER TABLE avernet.workspace_topology_nodes
    DROP CONSTRAINT IF EXISTS ck_workspace_topology_nodes_hex_pair
    """,
    "DROP INDEX IF EXISTS avernet.uq_workspace_agent_bindings_hex",
    """
    ALTER TABLE avernet.workspace_agent_bindings
    DROP CONSTRAINT IF EXISTS ck_workspace_agent_bindings_hex_radius
    """,
    """
    ALTER TABLE avernet.workspace_agent_bindings
    DROP CONSTRAINT IF EXISTS ck_workspace_agent_bindings_hex_pair
    """,
    """
    ALTER TABLE avernet.workspace_agent_bindings
    ALTER COLUMN theme_color TYPE VARCHAR(20)
    """,
)


def upgrade() -> None:
    for statement in _UPGRADE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_DDL:
        op.execute(statement)
