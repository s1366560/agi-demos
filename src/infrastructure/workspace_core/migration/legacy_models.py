"""Frozen ORM schema for offline Workspace import, validation, and reverse export."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

from src.infrastructure.adapters.secondary.persistence.models import Base

LEGACY_WORKSPACE_TABLES = frozenset(
    {
        "blackboard_files",
        "blackboard_posts",
        "blackboard_replies",
        "cyber_genes",
        "cyber_objectives",
        "topology_edges",
        "topology_nodes",
        "workspace_agent_policies",
        "workspace_agents",
        "workspace_blackboard_outbox",
        "workspace_collaboration_authorities",
        "workspace_collaboration_mutation_receipts",
        "workspace_deployments",
        "workspace_members",
        "workspace_messages",
        "workspace_pipeline_contracts",
        "workspace_pipeline_runs",
        "workspace_pipeline_stage_runs",
        "workspace_plan_blackboard_entries",
        "workspace_plan_events",
        "workspace_plan_nodes",
        "workspace_plan_outbox",
        "workspace_plans",
        "workspace_task_session_attempts",
        "workspace_tasks",
        "workspaces",
    }
)
_SUPPORTING_PLATFORM_TABLES = (
    "users",
    "tenants",
    "projects",
    "user_projects",
    "agent_definitions",
    "conversations",
    "task_session_creation_receipts",
)

legacy_workspace_metadata = MetaData()
for _table_name in _SUPPORTING_PLATFORM_TABLES:
    Base.metadata.tables[_table_name].to_metadata(legacy_workspace_metadata)


class LegacyWorkspaceBase(DeclarativeBase):
    """Declarative registry isolated from the production platform metadata."""

    metadata = legacy_workspace_metadata


class WorkspaceModel(LegacyWorkspaceBase):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    office_status: Mapped[str] = mapped_column(String(20), default="inactive", nullable=False)
    hex_layout_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    default_blocking_categories_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_workspaces_project_name"),
        Index("ix_workspaces_tenant_project", "tenant_id", "project_id"),
    )


class WorkspaceCollaborationAuthorityModel(LegacyWorkspaceBase):
    """Monotonic authority revision shared by all Workspace Collaboration surfaces."""

    __tablename__ = "workspace_collaboration_authorities"
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    __table_args__ = (
        CheckConstraint("revision >= 0", name="ck_workspace_collaboration_authority_revision"),
        Index("ix_workspace_collaboration_authorities_scope", "tenant_id", "project_id"),
    )


class WorkspaceCollaborationMutationReceiptModel(LegacyWorkspaceBase):
    """Durable request receipt for one user-scoped Workspace surface intent."""

    __tablename__ = "workspace_collaboration_mutation_receipts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    contract_version: Mapped[str] = mapped_column(String(20), nullable=False)
    surface: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    committed_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        CheckConstraint(
            "expected_revision >= 0", name="ck_workspace_collaboration_receipt_expected_revision"
        ),
        CheckConstraint(
            "committed_revision IS NULL OR committed_revision >= expected_revision",
            name="ck_workspace_collaboration_receipt_committed_revision",
        ),
        Index(
            "uq_workspace_collaboration_receipt_intent",
            "workspace_id",
            "actor_user_id",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "ix_workspace_collaboration_receipts_scope_revision",
            "tenant_id",
            "project_id",
            "workspace_id",
            "committed_revision",
        ),
    )


class WorkspaceMemberModel(LegacyWorkspaceBase):
    __tablename__ = "workspace_members"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="viewer", nullable=False)
    invited_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
        Index("ix_workspace_members_workspace_role", "workspace_id", "role"),
    )


class WorkspaceAgentPolicyModel(LegacyWorkspaceBase):
    """Versioned Workspace policy shared by Work and Code agent runs."""

    __tablename__ = "workspace_agent_policies"
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    roles_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    fallbacks_json: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list, nullable=False)
    reasoning_effort: Mapped[str] = mapped_column(
        String(16), default="medium", server_default="medium", nullable=False
    )
    permission_mode: Mapped[str] = mapped_column(
        String(24), default="ask", server_default="ask", nullable=False
    )
    updated_by: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    __table_args__ = (Index("ix_workspace_agent_policies_scope", "tenant_id", "project_id"),)


class WorkspaceAgentModel(LegacyWorkspaceBase):
    __tablename__ = "workspace_agents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String, ForeignKey("agent_definitions.id"), nullable=False, index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    hex_q: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hex_r: Mapped[int | None] = mapped_column(Integer, nullable=True)
    theme_color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="idle", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (
        UniqueConstraint("workspace_id", "agent_id", name="uq_workspace_agents_workspace_agent"),
        Index("ix_workspace_agents_workspace_active", "workspace_id", "is_active"),
    )


class BlackboardPostModel(LegacyWorkspaceBase):
    __tablename__ = "blackboard_posts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (
        Index("ix_blackboard_posts_workspace_created", "workspace_id", "created_at"),
        Index("ix_blackboard_posts_workspace_pinned_status", "workspace_id", "is_pinned", "status"),
    )


class BlackboardReplyModel(LegacyWorkspaceBase):
    __tablename__ = "blackboard_replies"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    post_id: Mapped[str] = mapped_column(
        String, ForeignKey("blackboard_posts.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (Index("ix_blackboard_replies_post_created", "post_id", "created_at"),)


class BlackboardFileModel(LegacyWorkspaceBase):
    __tablename__ = "blackboard_files"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    parent_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="/")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_directory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    uploader_type: Mapped[str] = mapped_column(String(10), nullable=False)
    uploader_id: Mapped[str] = mapped_column(String, nullable=False)
    uploader_name: Mapped[str] = mapped_column(String(128), nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mime_type_detected: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        Index(
            "uq_blackboard_files_ws_path_name", "workspace_id", "parent_path", "name", unique=True
        ),
        Index("ix_blackboard_files_workspace", "workspace_id"),
    )


class WorkspaceTaskModel(LegacyWorkspaceBase):
    __tablename__ = "workspace_tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    assignee_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    assignee_agent_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("agent_definitions.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="todo", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_effort: Mapped[str | None] = mapped_column(String(50), nullable=True)
    blocker_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        Index("ix_workspace_tasks_workspace_status", "workspace_id", "status"),
        Index("ix_workspace_tasks_workspace_created", "workspace_id", "created_at"),
    )


class WorkspaceTaskSessionAttemptModel(LegacyWorkspaceBase):
    __tablename__ = "workspace_task_session_attempts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_task_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    root_goal_task_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    conversation_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=True, index=True
    )
    worker_agent_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("agent_definitions.id"), nullable=True
    )
    leader_agent_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("agent_definitions.id"), nullable=True
    )
    candidate_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_artifacts_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    candidate_verifications_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    leader_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    adjudication_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint(
            "workspace_task_id",
            "attempt_number",
            name="uq_workspace_task_session_attempts_task_attempt",
        ),
        Index("ix_workspace_task_session_attempts_task_status", "workspace_task_id", "status"),
        Index("ix_workspace_task_session_attempts_root_created", "root_goal_task_id", "created_at"),
    )


class TopologyNodeModel(LegacyWorkspaceBase):
    __tablename__ = "topology_nodes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    node_type: Mapped[str] = mapped_column(String(20), nullable=False)
    ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    position_x: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    position_y: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    hex_q: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hex_r: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    tags_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (
        Index("ix_topology_nodes_workspace_type", "workspace_id", "node_type"),
        Index("ix_topology_nodes_workspace_ref", "workspace_id", "ref_id"),
    )


class TopologyEdgeModel(LegacyWorkspaceBase):
    __tablename__ = "topology_edges"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    source_node_id: Mapped[str] = mapped_column(
        String, ForeignKey("topology_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id: Mapped[str] = mapped_column(
        String, ForeignKey("topology_nodes.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_hex_q: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_hex_r: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_hex_q: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_hex_r: Mapped[int | None] = mapped_column(Integer, nullable=True)
    direction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    auto_created: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (
        Index("ix_topology_edges_workspace", "workspace_id"),
        Index("ix_topology_edges_source_target", "source_node_id", "target_node_id"),
    )


class CyberObjectiveModel(LegacyWorkspaceBase):
    __tablename__ = "cyber_objectives"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    obj_type: Mapped[str] = mapped_column(String(20), default="objective", nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("cyber_objectives.id", ondelete="SET NULL"), nullable=True
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (
        Index("ix_cyber_objectives_workspace", "workspace_id"),
        Index("ix_cyber_objectives_workspace_type", "workspace_id", "obj_type"),
        Index("ix_cyber_objectives_parent", "parent_id"),
    )


class CyberGeneModel(LegacyWorkspaceBase):
    __tablename__ = "cyber_genes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(20), default="skill", nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str] = mapped_column(String(50), default="1.0.0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (
        Index("ix_cyber_genes_workspace", "workspace_id"),
        Index("ix_cyber_genes_workspace_category", "workspace_id", "category"),
    )


class WorkspaceMessageModel(LegacyWorkspaceBase):
    __tablename__ = "workspace_messages"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    sender_id: Mapped[str] = mapped_column(String, nullable=False)
    sender_type: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    mentions_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    parent_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        Index("ix_workspace_messages_workspace_created", "workspace_id", "created_at"),
        Index("ix_workspace_messages_parent", "parent_message_id"),
    )


class PlanModel(LegacyWorkspaceBase):
    """Typed multi-agent plan (DAG). See ``src/domain/model/workspace_plan/plan.py``.

    Added in migration ``n1a2b3c4d5e6`` to persist ``Plan`` aggregates produced
    by the V2 workspace orchestrator. Keeps the in-memory repo as fallback;
    wired via settings flag / DI container.
    """

    __tablename__ = "workspace_plans"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    goal_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (Index("ix_workspace_plans_workspace", "workspace_id"),)


class PlanNodeModel(LegacyWorkspaceBase):
    """A node in a :class:`PlanModel` DAG.

    Complex nested value objects (``depends_on``, ``acceptance_criteria``,
    ``inputs_schema``, ``outputs_schema``, ``recommended_capabilities``,
    ``progress``, ``estimated_effort``) are stored as JSON blobs. The schema
    is owned by the domain and deserialized by :class:`SqlPlanRepository`.
    """

    __tablename__ = "workspace_plan_nodes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_plans.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="task")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    depends_on: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    inputs_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    outputs_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    acceptance_criteria: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    feature_checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    handoff_package: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    recommended_capabilities: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    preferred_agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    estimated_effort: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    intent: Mapped[str] = mapped_column(String(20), nullable=False, default="todo")
    execution: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    assignee_agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_attempt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    workspace_task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        Index("ix_workspace_plan_nodes_plan", "plan_id"),
        Index("ix_workspace_plan_nodes_parent", "parent_id"),
        Index("ix_workspace_plan_nodes_workspace_task", "workspace_task_id"),
    )


class WorkspacePlanBlackboardEntryModel(LegacyWorkspaceBase):
    """Append-only typed artifact entry for workspace plan coordination."""

    __tablename__ = "workspace_plan_blackboard_entries"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_plans.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(500), nullable=False)
    value_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    published_by: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint(
            "plan_id", "key", "version", name="uq_workspace_plan_blackboard_plan_key_version"
        ),
        Index("ix_workspace_plan_blackboard_plan", "plan_id"),
        Index("ix_workspace_plan_blackboard_plan_key", "plan_id", "key"),
    )


class WorkspacePlanEventModel(LegacyWorkspaceBase):
    """Append-only event log for durable workspace plan progression."""

    __tablename__ = "workspace_plan_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_plans.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="system")
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        Index("ix_workspace_plan_events_plan_created", "plan_id", "created_at"),
        Index("ix_workspace_plan_events_workspace_created", "workspace_id", "created_at"),
        Index("ix_workspace_plan_events_node", "plan_id", "node_id", "created_at"),
        Index("ix_workspace_plan_events_attempt", "attempt_id"),
    )


class WorkspacePlanOutboxModel(LegacyWorkspaceBase):
    """Durable work queue record for autonomous workspace plan progression."""

    __tablename__ = "workspace_plan_outbox"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("workspace_plans.id", ondelete="CASCADE"), nullable=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (
        Index("ix_workspace_plan_outbox_plan", "plan_id"),
        Index("ix_workspace_plan_outbox_workspace_status", "workspace_id", "status"),
        Index("ix_workspace_plan_outbox_status_next_attempt", "status", "next_attempt_at"),
        Index("ix_workspace_plan_outbox_lease", "lease_owner", "lease_expires_at"),
    )


class WorkspaceBlackboardOutboxModel(LegacyWorkspaceBase):
    """Transactional outbox row for blackboard SSE events.

    Persisted in the same DB transaction as the originating mutation
    (post/reply/file create/update/delete). A background dispatcher
    drains pending rows and publishes them to the Redis workspace event
    bus, then marks the row dispatched. Guarantees at-least-once
    delivery even when Redis is unavailable at request time.
    """

    __tablename__ = "workspace_blackboard_outbox"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (
        Index("ix_blackboard_outbox_workspace_status", "workspace_id", "status"),
        Index("ix_blackboard_outbox_status_next_attempt", "status", "next_attempt_at"),
        Index("ix_blackboard_outbox_created_at", "created_at"),
    )


class WorkspacePipelineContractModel(LegacyWorkspaceBase):
    """Harness-native CI/CD contract for a workspace plan."""

    __tablename__ = "workspace_pipeline_contracts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("workspace_plans.id", ondelete="CASCADE"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="sandbox_native")
    code_root: Mapped[str | None] = mapped_column(String, nullable=True)
    commands_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    env_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    trigger_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=600)
    auto_deploy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    preview_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    health_url: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "plan_id", name="uq_workspace_pipeline_contract_workspace_plan"
        ),
        Index("ix_workspace_pipeline_contracts_workspace", "workspace_id"),
        Index("ix_workspace_pipeline_contracts_plan", "plan_id"),
    )


class WorkspacePipelineRunModel(LegacyWorkspaceBase):
    """One harness-native CI/CD run for a plan node or attempt."""

    __tablename__ = "workspace_pipeline_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    contract_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_pipeline_contracts.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("workspace_plans.id", ondelete="CASCADE"), nullable=True
    )
    node_id: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    commit_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="sandbox_native")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (
        Index("ix_workspace_pipeline_runs_workspace_created", "workspace_id", "created_at"),
        Index("ix_workspace_pipeline_runs_plan_node", "plan_id", "node_id"),
        Index("ix_workspace_pipeline_runs_attempt", "attempt_id"),
        Index("ix_workspace_pipeline_runs_status", "status"),
    )


class WorkspacePipelineStageRunModel(LegacyWorkspaceBase):
    """Stage-level result inside a workspace pipeline run."""

    __tablename__ = "workspace_pipeline_stage_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_pipeline_runs.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    command: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    artifact_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (
        Index("ix_workspace_pipeline_stage_runs_run", "run_id"),
        Index("ix_workspace_pipeline_stage_runs_workspace_status", "workspace_id", "status"),
    )


class WorkspaceDeploymentModel(LegacyWorkspaceBase):
    """Preview runtime managed by the workspace harness."""

    __tablename__ = "workspace_deployments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("workspace_plans.id", ondelete="CASCADE"), nullable=True
    )
    node_id: Mapped[str | None] = mapped_column(String, nullable=True)
    pipeline_run_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("workspace_pipeline_runs.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="sandbox_native")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    command: Mapped[str | None] = mapped_column(Text, nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    process_group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    service_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_url: Mapped[str | None] = mapped_column(String, nullable=True)
    ws_preview_url: Mapped[str | None] = mapped_column(String, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    preview_url: Mapped[str | None] = mapped_column(String, nullable=True)
    health_url: Mapped[str | None] = mapped_column(String, nullable=True)
    restart_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_healthy_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    log_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    __table_args__ = (
        Index("ix_workspace_deployments_workspace_created", "workspace_id", "created_at"),
        Index("ix_workspace_deployments_plan_node", "plan_id", "node_id"),
        Index("ix_workspace_deployments_plan_node_service", "plan_id", "node_id", "service_id"),
        Index("ix_workspace_deployments_pipeline_run", "pipeline_run_id"),
        Index("ix_workspace_deployments_status", "status"),
    )
