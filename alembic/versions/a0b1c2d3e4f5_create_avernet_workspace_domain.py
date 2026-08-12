"""Create normalized Avernet Workspace domain tables.

Revision ID: a0b1c2d3e4f5
Revises: a9c0d1e2f3a4
Create Date: 2026-08-10

These tables are the queryable MemStack domain extension to Avernet BCS. They
deliberately preserve source identifiers and tenant/project scope instead of
placing Workspace data in generic BCS extension JSON.
"""

from collections.abc import Iterable

import sqlalchemy as sa

from alembic import op

revision = "a0b1c2d3e4f5"
down_revision = "a9c0d1e2f3a4"
branch_labels = None
depends_on = None

SCHEMA = "avernet"

_TABLE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE avernet.workspace_profiles (
        workspace_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        group_id VARCHAR(64) NOT NULL,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        created_by VARCHAR(128) NOT NULL,
        is_archived BOOLEAN NOT NULL DEFAULT FALSE,
        office_status VARCHAR(20) NOT NULL DEFAULT 'inactive',
        hex_layout_config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        default_blocking_categories_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        source_hash CHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_workspace_profiles_scope_id
            UNIQUE (tenant_id, project_id, workspace_id),
        CONSTRAINT uq_workspace_profiles_group UNIQUE (group_id),
        CONSTRAINT uq_workspace_profiles_project_name
            UNIQUE (tenant_id, project_id, name),
        CONSTRAINT ck_workspace_profiles_source_hash
            CHECK (source_hash IS NULL OR source_hash ~ '^[0-9a-f]{64}$')
    )
    """,
    """
    CREATE TABLE avernet.workspace_members (
        member_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        user_id VARCHAR(128) NOT NULL,
        participant_actor_id VARCHAR(256) NOT NULL,
        role VARCHAR(20) NOT NULL,
        invited_by VARCHAR(128),
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_members_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_members_user UNIQUE (workspace_id, user_id),
        CONSTRAINT uq_workspace_members_actor UNIQUE (workspace_id, participant_actor_id),
        CONSTRAINT ck_workspace_members_role CHECK (role IN ('owner', 'editor', 'viewer'))
    )
    """,
    """
    CREATE TABLE avernet.workspace_agent_policies (
        workspace_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        revision BIGINT NOT NULL DEFAULT 0,
        roles_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        fallbacks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        reasoning_effort VARCHAR(16) NOT NULL DEFAULT 'medium',
        permission_mode VARCHAR(24) NOT NULL DEFAULT 'ask',
        updated_by VARCHAR(128),
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_agent_policies_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT ck_workspace_agent_policies_revision CHECK (revision >= 0)
    )
    """,
    """
    CREATE TABLE avernet.workspace_agent_bindings (
        binding_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        agent_id VARCHAR(128) NOT NULL,
        bot_uuid VARCHAR(256) NOT NULL,
        participant_actor_id VARCHAR(256) NOT NULL,
        display_name VARCHAR(255),
        description TEXT,
        config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        hex_q INTEGER,
        hex_r INTEGER,
        theme_color VARCHAR(20),
        label VARCHAR(100),
        status VARCHAR(20) NOT NULL DEFAULT 'idle',
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_agent_bindings_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_agent_bindings_agent UNIQUE (workspace_id, agent_id),
        CONSTRAINT uq_workspace_agent_bindings_bot UNIQUE (workspace_id, bot_uuid),
        CONSTRAINT uq_workspace_agent_bindings_actor
            UNIQUE (workspace_id, participant_actor_id)
    )
    """,
    """
    CREATE TABLE avernet.workspace_tasks (
        task_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        title VARCHAR(255) NOT NULL,
        description TEXT,
        created_by VARCHAR(128) NOT NULL,
        assignee_user_id VARCHAR(128),
        assignee_agent_id VARCHAR(128),
        status VARCHAR(40) NOT NULL DEFAULT 'todo',
        priority INTEGER NOT NULL DEFAULT 0,
        estimated_effort VARCHAR(50),
        blocker_reason TEXT,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMPTZ,
        archived_at TIMESTAMPTZ,
        CONSTRAINT fk_workspace_tasks_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_tasks_scope_id
            UNIQUE (tenant_id, project_id, workspace_id, task_id)
    )
    """,
    """
    CREATE TABLE avernet.workspace_task_attempts (
        attempt_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        task_id VARCHAR(128) NOT NULL,
        root_goal_task_id VARCHAR(128) NOT NULL,
        attempt_number INTEGER NOT NULL,
        status VARCHAR(40) NOT NULL DEFAULT 'pending',
        conversation_id VARCHAR(128),
        worker_agent_id VARCHAR(128),
        leader_agent_id VARCHAR(128),
        candidate_summary TEXT,
        candidate_artifacts_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        candidate_verifications_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        leader_feedback TEXT,
        adjudication_reason TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMPTZ,
        CONSTRAINT fk_workspace_task_attempts_task
            FOREIGN KEY (tenant_id, project_id, workspace_id, task_id)
            REFERENCES avernet.workspace_tasks (tenant_id, project_id, workspace_id, task_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_task_attempts_root
            FOREIGN KEY (tenant_id, project_id, workspace_id, root_goal_task_id)
            REFERENCES avernet.workspace_tasks (tenant_id, project_id, workspace_id, task_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_task_attempts_number UNIQUE (task_id, attempt_number),
        CONSTRAINT ck_workspace_task_attempts_number CHECK (attempt_number > 0)
    )
    """,
    """
    CREATE TABLE avernet.workspace_task_receipts (
        receipt_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        task_id VARCHAR(128),
        actor_id VARCHAR(256) NOT NULL,
        action VARCHAR(64) NOT NULL,
        idempotency_key VARCHAR(256) NOT NULL,
        payload_hash CHAR(64) NOT NULL,
        expected_revision BIGINT,
        committed_revision BIGINT,
        result_json JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        committed_at TIMESTAMPTZ,
        CONSTRAINT fk_workspace_task_receipts_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_task_receipts_intent
            UNIQUE (workspace_id, actor_id, idempotency_key),
        CONSTRAINT ck_workspace_task_receipts_hash
            CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_workspace_task_receipts_revision
            CHECK (expected_revision IS NULL OR expected_revision >= 0),
        CONSTRAINT ck_workspace_task_receipts_commit
            CHECK (committed_revision IS NULL OR committed_revision >= 0)
    )
    """,
    """
    CREATE TABLE avernet.workspace_blackboard_posts (
        post_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        author_actor_id VARCHAR(256) NOT NULL,
        title VARCHAR(255) NOT NULL,
        content TEXT NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'open',
        is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_blackboard_posts_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_blackboard_posts_scope_id
            UNIQUE (tenant_id, project_id, workspace_id, post_id)
    )
    """,
    """
    CREATE TABLE avernet.workspace_blackboard_replies (
        reply_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        post_id VARCHAR(128) NOT NULL,
        author_actor_id VARCHAR(256) NOT NULL,
        content TEXT NOT NULL,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_blackboard_replies_post
            FOREIGN KEY (tenant_id, project_id, workspace_id, post_id)
            REFERENCES avernet.workspace_blackboard_posts
                (tenant_id, project_id, workspace_id, post_id)
            ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE avernet.workspace_files (
        file_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        parent_path VARCHAR(1024) NOT NULL DEFAULT '/',
        name VARCHAR(255) NOT NULL,
        is_directory BOOLEAN NOT NULL DEFAULT FALSE,
        file_size BIGINT NOT NULL DEFAULT 0,
        content_type VARCHAR(128) NOT NULL DEFAULT '',
        storage_backend VARCHAR(32) NOT NULL,
        object_handle TEXT NOT NULL,
        uploader_type VARCHAR(16) NOT NULL,
        uploader_id VARCHAR(128) NOT NULL,
        uploader_actor_id VARCHAR(256) NOT NULL,
        uploader_name VARCHAR(128) NOT NULL,
        checksum_sha256 CHAR(64),
        detected_mime_type VARCHAR(255),
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_files_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_files_path UNIQUE (workspace_id, parent_path, name),
        CONSTRAINT ck_workspace_files_size CHECK (file_size >= 0),
        CONSTRAINT ck_workspace_files_checksum
            CHECK (checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$')
    )
    """,
    """
    CREATE TABLE avernet.workspace_topology_nodes (
        node_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        node_type VARCHAR(20) NOT NULL,
        ref_id VARCHAR(128),
        title VARCHAR(255) NOT NULL DEFAULT '',
        position_x DOUBLE PRECISION NOT NULL DEFAULT 0,
        position_y DOUBLE PRECISION NOT NULL DEFAULT 0,
        hex_q INTEGER,
        hex_r INTEGER,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        data_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_topology_nodes_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_topology_nodes_scope_id
            UNIQUE (tenant_id, project_id, workspace_id, node_id)
    )
    """,
    """
    CREATE TABLE avernet.workspace_topology_edges (
        edge_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        source_node_id VARCHAR(128) NOT NULL,
        target_node_id VARCHAR(128) NOT NULL,
        edge_type VARCHAR(30) NOT NULL DEFAULT 'dependency',
        label VARCHAR(255),
        source_hex_q INTEGER,
        source_hex_r INTEGER,
        target_hex_q INTEGER,
        target_hex_r INTEGER,
        direction VARCHAR(30) NOT NULL DEFAULT 'directed',
        auto_created BOOLEAN NOT NULL DEFAULT FALSE,
        data_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_topology_edges_source
            FOREIGN KEY (tenant_id, project_id, workspace_id, source_node_id)
            REFERENCES avernet.workspace_topology_nodes
                (tenant_id, project_id, workspace_id, node_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_topology_edges_target
            FOREIGN KEY (tenant_id, project_id, workspace_id, target_node_id)
            REFERENCES avernet.workspace_topology_nodes
                (tenant_id, project_id, workspace_id, node_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_topology_edges_pair
            UNIQUE (workspace_id, source_node_id, target_node_id, edge_type),
        CONSTRAINT ck_workspace_topology_edges_distinct
            CHECK (source_node_id <> target_node_id)
    )
    """,
    """
    CREATE TABLE avernet.workspace_objectives (
        objective_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        title VARCHAR(255) NOT NULL,
        description TEXT,
        objective_type VARCHAR(20) NOT NULL DEFAULT 'objective',
        parent_objective_id VARCHAR(128),
        status VARCHAR(20) NOT NULL DEFAULT 'draft',
        priority INTEGER NOT NULL DEFAULT 0,
        owner_actor_id VARCHAR(256),
        created_by_actor_id VARCHAR(256) NOT NULL,
        progress DOUBLE PRECISION NOT NULL DEFAULT 0,
        success_criteria_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        progress_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMPTZ,
        CONSTRAINT fk_workspace_objectives_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_objectives_parent
            FOREIGN KEY (tenant_id, project_id, workspace_id, parent_objective_id)
            REFERENCES avernet.workspace_objectives
                (tenant_id, project_id, workspace_id, objective_id)
            ON DELETE SET NULL (parent_objective_id),
        CONSTRAINT uq_workspace_objectives_scope_id
            UNIQUE (tenant_id, project_id, workspace_id, objective_id),
        CONSTRAINT ck_workspace_objectives_progress
            CHECK (progress >= 0 AND progress <= 1)
    )
    """,
    """
    CREATE TABLE avernet.workspace_genes (
        gene_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        category VARCHAR(20) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'draft',
        version INTEGER NOT NULL DEFAULT 1,
        source_version VARCHAR(50) NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        config_text TEXT,
        content_json JSONB NOT NULL,
        content_hash CHAR(64) NOT NULL,
        source_objective_id VARCHAR(128),
        created_by_actor_id VARCHAR(256),
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_workspace_genes_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT fk_workspace_genes_objective
            FOREIGN KEY (tenant_id, project_id, workspace_id, source_objective_id)
            REFERENCES avernet.workspace_objectives
                (tenant_id, project_id, workspace_id, objective_id)
            ON DELETE SET NULL (source_objective_id),
        CONSTRAINT uq_workspace_genes_version UNIQUE (workspace_id, gene_id, version),
        CONSTRAINT ck_workspace_genes_version CHECK (version > 0),
        CONSTRAINT ck_workspace_genes_hash CHECK (content_hash ~ '^[0-9a-f]{64}$')
    )
    """,
)

_INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX ix_avn_ws_profiles_scope ON avernet.workspace_profiles (tenant_id, project_id)",
    "CREATE INDEX ix_avn_ws_members_scope_role ON avernet.workspace_members (tenant_id, project_id, workspace_id, role)",
    "CREATE INDEX ix_avn_ws_agents_active ON avernet.workspace_agent_bindings (workspace_id, is_active)",
    "CREATE INDEX ix_avn_ws_tasks_status ON avernet.workspace_tasks (workspace_id, status)",
    "CREATE INDEX ix_avn_ws_tasks_created ON avernet.workspace_tasks (workspace_id, created_at)",
    "CREATE INDEX ix_avn_ws_attempts_task_status ON avernet.workspace_task_attempts (task_id, status)",
    "CREATE INDEX ix_avn_ws_attempts_conversation ON avernet.workspace_task_attempts (conversation_id)",
    "CREATE INDEX ix_avn_ws_posts_created ON avernet.workspace_blackboard_posts (workspace_id, created_at)",
    "CREATE INDEX ix_avn_ws_posts_pinned ON avernet.workspace_blackboard_posts (workspace_id, is_pinned, status)",
    "CREATE INDEX ix_avn_ws_replies_post ON avernet.workspace_blackboard_replies (post_id, created_at)",
    "CREATE INDEX ix_avn_ws_files_workspace ON avernet.workspace_files (workspace_id)",
    "CREATE INDEX ix_avn_ws_topology_nodes_ref ON avernet.workspace_topology_nodes (workspace_id, node_type, ref_id)",
    "CREATE INDEX ix_avn_ws_topology_edges_source ON avernet.workspace_topology_edges (workspace_id, source_node_id)",
    "CREATE INDEX ix_avn_ws_topology_edges_target ON avernet.workspace_topology_edges (workspace_id, target_node_id)",
    "CREATE INDEX ix_avn_ws_objectives_status ON avernet.workspace_objectives (workspace_id, status, priority)",
    "CREATE INDEX ix_avn_ws_genes_status ON avernet.workspace_genes (workspace_id, status, updated_at)",
)

_UPDATED_TABLES: tuple[str, ...] = (
    "workspace_profiles",
    "workspace_members",
    "workspace_agent_policies",
    "workspace_agent_bindings",
    "workspace_tasks",
    "workspace_task_attempts",
    "workspace_blackboard_posts",
    "workspace_blackboard_replies",
    "workspace_topology_nodes",
    "workspace_topology_edges",
    "workspace_objectives",
    "workspace_genes",
)

_TABLES: tuple[str, ...] = (
    "workspace_genes",
    "workspace_objectives",
    "workspace_topology_edges",
    "workspace_topology_nodes",
    "workspace_files",
    "workspace_blackboard_replies",
    "workspace_blackboard_posts",
    "workspace_task_receipts",
    "workspace_task_attempts",
    "workspace_tasks",
    "workspace_agent_bindings",
    "workspace_agent_policies",
    "workspace_members",
    "workspace_profiles",
)


def _execute_all(statements: Iterable[str]) -> None:
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade() -> None:
    _execute_all(_TABLE_DDL)
    _execute_all(_INDEX_DDL)
    op.execute(
        sa.text(
            """
            CREATE FUNCTION avernet.touch_updated_at() RETURNS TRIGGER
            LANGUAGE plpgsql AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    for table_name in _UPDATED_TABLES:
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_{table_name}_touch_updated_at
                BEFORE UPDATE ON avernet.{table_name}
                FOR EACH ROW EXECUTE FUNCTION avernet.touch_updated_at()
                """
            )
        )


def downgrade() -> None:
    for table_name in _TABLES:
        op.execute(sa.text(f"DROP TABLE IF EXISTS avernet.{table_name} CASCADE"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS avernet.touch_updated_at()"))
