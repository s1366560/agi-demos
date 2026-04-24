import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.persistence.channel_models import (
        ChannelConfigModel,
    )


from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None

from src.domain.model.enums import DataStatus, ProcessingStatus


class Base(DeclarativeBase):
    pass


class IdGeneratorMixin:
    """Mixin providing a class method to generate unique IDs for database entities."""

    @classmethod
    def generate_id(cls) -> str:
        """Generate a unique UUID string for entity identification."""
        return str(uuid.uuid4())


AGENT_EXECUTION_EVENT_CORRELATION_ID_LENGTH = 100


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    api_keys: Mapped[list["APIKey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    tenants: Mapped[list["UserTenant"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    projects: Mapped[list["UserProject"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    memories: Mapped[list["Memory"]] = relationship(
        back_populates="author", cascade="all, delete-orphan"
    )
    owned_tenants: Mapped[list["Tenant"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    owned_projects: Mapped[list["Project"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Role(IdGeneratorMixin, Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    users: Mapped[list["UserRole"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class Permission(IdGeneratorMixin, Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True, index=True)  # e.g. "user:create"
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    roles: Mapped[list["RolePermission"]] = relationship(
        back_populates="permission", cascade="all, delete-orphan"
    )


class RolePermission(IdGeneratorMixin, Base):
    __tablename__ = "role_permissions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    role_id: Mapped[str] = mapped_column(String, ForeignKey("roles.id"), nullable=False)
    permission_id: Mapped[str] = mapped_column(String, ForeignKey("permissions.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    role: Mapped["Role"] = relationship(back_populates="permissions")
    permission: Mapped["Permission"] = relationship(back_populates="roles")


class UserRole(IdGeneratorMixin, Base):
    __tablename__ = "user_roles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    role_id: Mapped[str] = mapped_column(String, ForeignKey("roles.id"), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String, ForeignKey("tenants.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="roles")
    role: Mapped["Role"] = relationship(back_populates="users")


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    key_hash: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="api_keys")


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(
        String, unique=True, nullable=False
    )  # URL-friendly identifier
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)

    # Configuration limits
    plan: Mapped[str] = mapped_column(String, default="free")
    max_projects: Mapped[int] = mapped_column(Integer, default=10)
    max_users: Mapped[int] = mapped_column(Integer, default=5)
    max_storage: Mapped[int] = mapped_column(BigInteger, default=1073741824)  # 1GB in bytes

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    owner: Mapped["User"] = relationship(back_populates="owned_tenants")
    users: Mapped[list["UserTenant"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    memory_rules: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    graph_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sandbox_type: Mapped[str] = mapped_column(
        String(20), default="cloud", nullable=False
    )  # cloud, local
    sandbox_config: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )  # Local sandbox config when sandbox_type is "local"
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_conversation_mode: Mapped[str] = mapped_column(
        String(32),
        default="single_agent",
        server_default="single_agent",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="projects")
    owner: Mapped["User"] = relationship(back_populates="owned_projects")
    users: Mapped[list["UserProject"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    memories: Mapped[list["Memory"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    entity_types: Mapped[list["EntityType"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    edge_types: Mapped[list["EdgeType"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    edge_maps: Mapped[list["EdgeTypeMap"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    channel_configs: Mapped[list["ChannelConfigModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    @property
    def member_ids(self) -> list[str]:
        return [up.user_id for up in self.users]


class UserTenant(Base):
    __tablename__ = "user_tenants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, default="member")  # owner, admin, member, guest
    permissions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="tenants")
    tenant: Mapped["Tenant"] = relationship(back_populates="users")


class UserProject(Base):
    __tablename__ = "user_projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, default="member")  # owner, admin, member, viewer
    permissions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="projects")
    project: Mapped["Project"] = relationship(back_populates="users")


class WorkspaceModel(Base):
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

    tenant: Mapped["Tenant"] = relationship(foreign_keys=[tenant_id])
    project: Mapped["Project"] = relationship(foreign_keys=[project_id])
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])
    members: Mapped[list["WorkspaceMemberModel"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    agents: Mapped[list["WorkspaceAgentModel"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    blackboard_posts: Mapped[list["BlackboardPostModel"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    blackboard_files: Mapped[list["BlackboardFileModel"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["WorkspaceTaskModel"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    topology_nodes: Mapped[list["TopologyNodeModel"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    topology_edges: Mapped[list["TopologyEdgeModel"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    objectives: Mapped[list["CyberObjectiveModel"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    genes: Mapped[list["CyberGeneModel"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    messages: Mapped[list["WorkspaceMessageModel"]] = relationship(
        foreign_keys="[WorkspaceMessageModel.workspace_id]", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_workspaces_project_name"),
        Index("ix_workspaces_tenant_project", "tenant_id", "project_id"),
    )


class WorkspaceMemberModel(Base):
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

    workspace: Mapped["WorkspaceModel"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    inviter: Mapped[Optional["User"]] = relationship(foreign_keys=[invited_by])

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
        Index("ix_workspace_members_workspace_role", "workspace_id", "role"),
    )


class WorkspaceAgentModel(Base):
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

    workspace: Mapped["WorkspaceModel"] = relationship(back_populates="agents")
    agent: Mapped["AgentDefinitionModel"] = relationship(foreign_keys=[agent_id])

    __table_args__ = (
        UniqueConstraint("workspace_id", "agent_id", name="uq_workspace_agents_workspace_agent"),
        Index("ix_workspace_agents_workspace_active", "workspace_id", "is_active"),
    )


class BlackboardPostModel(Base):
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

    workspace: Mapped["WorkspaceModel"] = relationship(back_populates="blackboard_posts")
    author: Mapped["User"] = relationship(foreign_keys=[author_id])
    replies: Mapped[list["BlackboardReplyModel"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_blackboard_posts_workspace_created", "workspace_id", "created_at"),
        Index("ix_blackboard_posts_workspace_pinned_status", "workspace_id", "is_pinned", "status"),
    )


class BlackboardReplyModel(Base):
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

    post: Mapped["BlackboardPostModel"] = relationship(back_populates="replies")
    workspace: Mapped["WorkspaceModel"] = relationship(foreign_keys=[workspace_id])
    author: Mapped["User"] = relationship(foreign_keys=[author_id])

    __table_args__ = (Index("ix_blackboard_replies_post_created", "post_id", "created_at"),)


class BlackboardFileModel(Base):
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspace: Mapped["WorkspaceModel"] = relationship(back_populates="blackboard_files")

    __table_args__ = (
        Index(
            "uq_blackboard_files_ws_path_name",
            "workspace_id",
            "parent_path",
            "name",
            unique=True,
        ),
        Index("ix_blackboard_files_workspace", "workspace_id"),
    )


class WorkspaceTaskModel(Base):
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

    workspace: Mapped["WorkspaceModel"] = relationship(back_populates="tasks")
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])
    assignee_user: Mapped[Optional["User"]] = relationship(foreign_keys=[assignee_user_id])
    assignee_agent: Mapped[Optional["AgentDefinitionModel"]] = relationship(
        foreign_keys=[assignee_agent_id]
    )

    __table_args__ = (
        Index("ix_workspace_tasks_workspace_status", "workspace_id", "status"),
        Index("ix_workspace_tasks_workspace_created", "workspace_id", "created_at"),
    )


class WorkspaceTaskSessionAttemptModel(Base):
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

    workspace_task: Mapped["WorkspaceTaskModel"] = relationship(foreign_keys=[workspace_task_id])
    root_goal_task: Mapped["WorkspaceTaskModel"] = relationship(foreign_keys=[root_goal_task_id])
    workspace: Mapped["WorkspaceModel"] = relationship(foreign_keys=[workspace_id])
    conversation: Mapped[Optional["Conversation"]] = relationship(foreign_keys=[conversation_id])
    worker_agent: Mapped[Optional["AgentDefinitionModel"]] = relationship(
        foreign_keys=[worker_agent_id]
    )
    leader_agent: Mapped[Optional["AgentDefinitionModel"]] = relationship(
        foreign_keys=[leader_agent_id]
    )

    __table_args__ = (
        UniqueConstraint(
            "workspace_task_id",
            "attempt_number",
            name="uq_workspace_task_session_attempts_task_attempt",
        ),
        Index(
            "ix_workspace_task_session_attempts_task_status",
            "workspace_task_id",
            "status",
        ),
        Index(
            "ix_workspace_task_session_attempts_root_created",
            "root_goal_task_id",
            "created_at",
        ),
    )


class TopologyNodeModel(Base):
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

    workspace: Mapped["WorkspaceModel"] = relationship(back_populates="topology_nodes")

    __table_args__ = (
        Index("ix_topology_nodes_workspace_type", "workspace_id", "node_type"),
        Index("ix_topology_nodes_workspace_ref", "workspace_id", "ref_id"),
    )


class TopologyEdgeModel(Base):
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

    workspace: Mapped["WorkspaceModel"] = relationship(back_populates="topology_edges")
    source_node: Mapped["TopologyNodeModel"] = relationship(foreign_keys=[source_node_id])
    target_node: Mapped["TopologyNodeModel"] = relationship(foreign_keys=[target_node_id])

    __table_args__ = (
        Index("ix_topology_edges_workspace", "workspace_id"),
        Index("ix_topology_edges_source_target", "source_node_id", "target_node_id"),
    )


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), default="text")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    entities: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    relationships: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    author_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    collaborators: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default=DataStatus.ENABLED)
    processing_status: Mapped[str] = mapped_column(String, default=ProcessingStatus.PENDING)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    task_id: Mapped[str | None] = mapped_column(String, nullable=True)  # Task ID for SSE streaming
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="memories")
    author: Mapped["User"] = relationship(back_populates="memories")


class EntityType(Base):
    __tablename__ = "entity_types"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_entity_type_project_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default=DataStatus.ENABLED)
    source: Mapped[str] = mapped_column(String, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="entity_types")


class EdgeType(Base):
    __tablename__ = "edge_types"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_edge_type_project_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default=DataStatus.ENABLED)
    source: Mapped[str] = mapped_column(String, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="edge_types")


class EdgeTypeMap(Base):
    __tablename__ = "edge_type_maps"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "source_type", "target_type", "edge_type", name="uq_edge_map_unique"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    target_type: Mapped[str] = mapped_column(String, nullable=False)
    edge_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default=DataStatus.ENABLED)
    source: Mapped[str] = mapped_column(String, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="edge_maps")


class TaskLog(Base):
    __tablename__ = "task_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    group_id: Mapped[str] = mapped_column(String, index=True)
    task_type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(
        String, index=True
    )  # PENDING, PROCESSING, COMPLETED, FAILED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # Stores arguments
    progress: Mapped[int] = mapped_column(Integer, default=0)  # Task progress percentage (0-100)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # Task result data
    message: Mapped[str | None] = mapped_column(String, nullable=True)  # Task status message

    # Association & Hierarchy
    entity_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_task_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryShare(Base):
    __tablename__ = "memory_shares"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    memory_id: Mapped[str] = mapped_column(String, ForeignKey("memories.id"), nullable=False)
    share_token: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    shared_with_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    shared_with_project_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("projects.id"), nullable=True
    )
    permissions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    shared_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    memory: Mapped["Memory"] = relationship(foreign_keys=[memory_id])
    shared_with_user: Mapped[Optional["User"]] = relationship(foreign_keys=[shared_with_user_id])
    shared_with_project: Mapped[Optional["Project"]] = relationship(
        foreign_keys=[shared_with_project_id]
    )
    sharer: Mapped["User"] = relationship(foreign_keys=[shared_by])


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    action_url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(foreign_keys=[user_id])


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invoice_url: Mapped[str | None] = mapped_column(String, nullable=True)

    tenant: Mapped["Tenant"] = relationship(foreign_keys=[tenant_id])


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String, ForeignKey("tenants.id"), nullable=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[Optional["Tenant"]] = relationship(foreign_keys=[tenant_id])
    user: Mapped["User"] = relationship(foreign_keys=[user_id])


# ============================================================================
# Agent Models
# ============================================================================


class Conversation(Base):
    """Multi-turn conversation between user and AI agent."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    agent_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Multi-level thinking support (work plan stored in work_plans table)
    workflow_pattern_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Plan Mode support
    current_mode: Mapped[str] = mapped_column(String(20), default="build", nullable=False)
    current_plan_id: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_conversation_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=True, index=True
    )
    branch_point_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Fork/merge support (Phase 3)
    fork_source_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=True
    )
    fork_context_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    merge_strategy: Mapped[str] = mapped_column(String(20), default="result_only", nullable=False)

    # Multi-agent collaboration (P2-3 phase-2, Track B · Agent First).
    # ``participant_agents`` was dark-launched by migration b1a2c3d4e5f6.
    # The remaining 3 columns were added by migration b2c3d4e5f6a7; the
    # ``goal_contract`` JSON column was dropped by migration g1a0b1c2d3e4
    # (goal ownership moved to Workspace/WorkspaceTask).
    participant_agents: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    conversation_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    coordinator_agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    focused_agent_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Workspace linkage (Track G2, migration ``g2d1e2f3a4b5``).
    # Nullable FK — legacy rows have no workspace; autonomous-mode rows
    # MUST have ``workspace_id`` set (enforced by the domain invariant).
    workspace_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    linked_workspace_task_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("workspace_tasks.id", ondelete="SET NULL"), nullable=True
    )

    project: Mapped["Project"] = relationship(foreign_keys=[project_id])
    tenant: Mapped["Tenant"] = relationship(foreign_keys=[tenant_id])
    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_conversations_project_updated", "project_id", "updated_at"),
        Index("ix_conversations_user_project", "user_id", "project_id", "updated_at"),
        Index("ix_conversations_tenant_status", "tenant_id", "status"),
    )


class Message(Base):
    """A single message in a conversation."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user, assistant, system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(String(20), default="text", nullable=False)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=True)
    tool_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Multi-level thinking support
    work_plan_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    task_step_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thought_level: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Threading support
    reply_to_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("messages.id"), nullable=True, index=True
    )

    # Message versioning
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    original_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Multi-agent collaboration (P2-3 phase-2, Track B · Agent First).
    # ``sender_agent_id`` identifies which agent produced an assistant
    # message (NULL = user or legacy single-agent assistant); ``mentions``
    # is the structured @mention list from the frontend picker.
    sender_agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    mentions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    executions: Mapped[list["AgentExecution"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )
    replies: Mapped[list["Message"]] = relationship(
        back_populates="parent_message",
        foreign_keys="Message.reply_to_id",
    )
    parent_message: Mapped[Optional["Message"]] = relationship(
        back_populates="replies",
        remote_side=[id],
        foreign_keys="Message.reply_to_id",
    )

    __table_args__ = (Index("ix_messages_conv_created", "conversation_id", "created_at"),)


class AgentExecution(Base):
    """A single agent execution cycle (Think-Act-Observe)."""

    __tablename__ = "agent_executions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False
    )
    message_id: Mapped[str] = mapped_column(String, ForeignKey("messages.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    thought: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str | None] = mapped_column(String(100), nullable=True)
    observation: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=True)
    tool_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Multi-level thinking support
    work_level_thought: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_level_thought: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_steps: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    current_step_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    workflow_pattern_id: Mapped[str | None] = mapped_column(String, nullable=True)

    conversation: Mapped["Conversation"] = relationship(foreign_keys=[conversation_id])
    message: Mapped["Message"] = relationship(back_populates="executions")


class ToolExecutionRecord(Base):
    """
    Record of a single tool execution during agent processing.

    This table stores the complete history of tool executions for each message,
    enabling proper timeline reconstruction when loading historical conversations.
    """

    __tablename__ = "tool_execution_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False, index=True
    )
    message_id: Mapped[str] = mapped_column(
        String, ForeignKey("messages.id"), nullable=False, index=True
    )
    call_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=True)
    tool_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # running, success, failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)  # Order within message
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    conversation: Mapped["Conversation"] = relationship(foreign_keys=[conversation_id])
    message: Mapped["Message"] = relationship(foreign_keys=[message_id])


class AgentExecutionEvent(Base):
    """
    SSE event during agent execution for replay support.

    This table stores all Server-Sent Events (SSE) emitted during agent execution,
    enabling event replay for reconnection and conversation switching scenarios.

    The combination of (conversation_id, event_time_us, event_counter) provides an
    ordered timeline of all events that can be replayed to reconstruct the execution state.
    """

    __tablename__ = "agent_execution_events"
    __table_args__ = (
        # Unique constraint to prevent duplicate events within a conversation
        UniqueConstraint(
            "conversation_id",
            "event_time_us",
            "event_counter",
            name="uq_agent_events_conv_time",
        ),
        # Index for ordered replay within a conversation
        Index("ix_agent_events_conv_time", "conversation_id", "event_time_us", "event_counter"),
        # Index for message-scoped replay
        Index("ix_agent_events_msg_time", "message_id", "event_time_us", "event_counter"),
        # Index for correlation_id queries
        Index("ix_agent_events_corr_id", "correlation_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False, index=True
    )
    # message_id is used for event grouping, no FK constraint for unified event timeline
    message_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    event_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    event_time_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # correlation_id links all events from a single user request
    correlation_id: Mapped[str | None] = mapped_column(
        String(AGENT_EXECUTION_EVENT_CORRELATION_ID_LENGTH),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(foreign_keys=[conversation_id])
    # message relationship removed - unified event timeline doesn't require FK to messages


class TextDeltaBuffer(Base):
    """
    Short-term buffer for text_delta events (for debugging and late replay).

    This table stores text_delta events for a limited time (5 minutes) to:
    - Allow late-connecting clients to catch up on recent text output
    - Enable debugging of TEXT_DELTA delivery issues
    - Provide audit trail for streaming text generation

    Events are automatically cleaned up by a scheduled job after expires_at.

    Note: For long-term storage, use Redis Stream (agent:events:{conversation_id}).
    """

    __tablename__ = "text_delta_buffer"
    __table_args__ = (
        # Index for efficient cleanup of expired events
        Index("ix_text_delta_buffer_expires", "expires_at"),
        # Index for replay by message
        Index("ix_text_delta_buffer_msg_seq", "message_id", "sequence_number"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Store delta content directly for fast access
    delta_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Full event data as JSON for completeness
    event_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Auto-expire after 5 minutes
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExecutionCheckpoint(Base):
    """
    Execution checkpoint for agent recovery and resumption.

    This table stores execution state snapshots at key points during agent
    execution, enabling recovery from failures and disconnections.

    Checkpoints include:
    - LLM complete: After LLM generates thought/action
    - Tool start: Before tool execution
    - Tool complete: After tool execution
    - Step complete: After a ReAct step completes

    The execution_state contains all necessary context to resume execution.
    """

    __tablename__ = "execution_checkpoints"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False, index=True
    )
    # message_id for grouping, no FK constraint for unified event timeline
    message_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    checkpoint_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    execution_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    step_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(foreign_keys=[conversation_id])
    # message relationship removed - unified event timeline doesn't require FK to messages


class AgentSessionSnapshot(Base):
    """Persisted Agent session snapshot for HITL recovery."""

    __tablename__ = "agent_session_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    agent_mode: Mapped[str] = mapped_column(String, nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    snapshot_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    snapshot_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowPattern(Base):
    """
    Workflow pattern for learning from successful agent executions.

    Tenant-level scoping (FR-019): Patterns are shared across all projects
    within a tenant but isolated between tenants.
    """

    __tablename__ = "workflow_patterns"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    pattern_signature: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    steps_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    # Legacy field for backward compatibility
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    tool_compositions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    success_rate: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    # Legacy fields for backward compatibility
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class ToolComposition(Base):
    """Tool composition for tracking effective tool combinations."""

    __tablename__ = "tool_compositions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    execution_template: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0


class TenantAgentConfig(Base):
    """
    Tenant-level agent configuration (T093).

    Stores agent configuration at the tenant level, allowing
    tenant administrators to customize agent behavior.

    Access Control (FR-021, FR-022):
    - All authenticated users can read config
    - Only tenant admins can modify config
    """

    __tablename__ = "tenant_agent_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    llm_temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    pattern_learning_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    multi_level_thinking_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    max_work_plan_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    tool_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    enabled_tools: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    disabled_tools: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    runtime_hooks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class Skill(Base):
    """
    Skill entity for the Agent Skill System.

    Represents a declarative skill that encapsulates domain knowledge
    and tool compositions for specific task patterns.

    Skills are the L2 layer in the four-layer capability architecture:
    Tool (L1) -> Skill (L2) -> SubAgent (L3) -> Agent (L4)

    Three-level scoping for multi-tenant isolation:
    - system: Built-in skills shared by all tenants (read-only)
    - tenant: Tenant-level skills shared within a tenant
    - project: Project-specific skills
    """

    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("projects.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default="keyword")
    trigger_patterns: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    tools: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    prompt_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    # New fields for three-level scoping
    scope: Mapped[str] = mapped_column(String(20), default="tenant", nullable=False, index=True)
    # scope: 'system' | 'tenant' | 'project'
    is_system_skill: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # True if this is a database copy of a system skill (for usage tracking)
    full_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Full SKILL.md content for Web UI editing
    # Version tracking
    current_version: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    version_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # P2-4: curated / private skill library
    parent_curated_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("curated_skills.id", ondelete="SET NULL"), nullable=True
    )
    semver: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Relationships
    project: Mapped[Optional["Project"]] = relationship(foreign_keys=[project_id])
    versions: Mapped[list["SkillVersion"]] = relationship(
        back_populates="skill", cascade="all, delete-orphan", order_by="SkillVersion.version_number"
    )

    # Indexes for efficient queries
    __table_args__ = (Index("ix_skills_tenant_scope", "tenant_id", "scope"),)

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 1.0


class TenantSkillConfig(Base):
    """
    Tenant-level configuration for system skills.

    Allows tenants to disable or override system skills without
    affecting other tenants.
    """

    __tablename__ = "tenant_skill_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    system_skill_name: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    # action: 'disable' | 'override'
    override_skill_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("skills.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    override_skill: Mapped[Optional["Skill"]] = relationship(foreign_keys=[override_skill_id])

    # Unique constraint: one config per tenant per system skill
    __table_args__ = (
        UniqueConstraint("tenant_id", "system_skill_name", name="uq_tenant_skill_config"),
    )


class SkillVersion(Base):
    """
    Versioned snapshot of a skill.

    Stores complete SKILL.md content and all resource files at a specific
    point in time. Each skill_sync call creates a new version entry.
    """

    __tablename__ = "skill_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    skill_id: Mapped[str] = mapped_column(
        String, ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    skill_md_content: Mapped[str] = mapped_column(Text, nullable=False)
    resource_files: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(20), nullable=False, default="agent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    skill: Mapped["Skill"] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint("skill_id", "version_number", name="uq_skill_version_number"),
        Index("ix_skill_versions_skill_id", "skill_id"),
    )


class CuratedSkill(Base):
    """
    Curated skill registry entry (P2-4).

    Represents an admin-approved skill available to every tenant via the
    "精选库" tab. Forking creates a new row in ``skills`` scoped to the
    caller's tenant with ``parent_curated_id`` set.
    """

    __tablename__ = "curated_skills"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    semver: Mapped[str] = mapped_column(String(32), nullable=False)
    revision_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source_skill_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("skills.id", ondelete="SET NULL"), nullable=True
    )
    source_tenant_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    approved_by: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active", nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SkillSubmission(Base):
    """
    Tenant-submitted skill candidate awaiting admin review (P2-4).

    Snapshots the submitter's skill payload; source_skill_id is intentionally
    a loose reference (not a FK) so submissions survive the original skill's
    deletion.
    """

    __tablename__ = "skill_submissions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    submitter_tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    submitter_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source_skill_id: Mapped[str | None] = mapped_column(String, nullable=True)
    skill_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    proposed_semver: Mapped[str] = mapped_column(String(32), nullable=False)
    submission_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False, index=True
    )
    reviewer_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SubAgent(Base):
    """
    SubAgent entity for the Agent SubAgent System.

    Represents a specialized sub-agent that can handle specific types
    of tasks with isolated tool access and custom system prompts.

    SubAgents are the L3 layer in the four-layer capability architecture:
    Tool (L1) -> Skill (L2) -> SubAgent (L3) -> Agent (L4)

    Tenant-level scoping: SubAgents are shared across all projects within
    a tenant but isolated between tenants.
    """

    __tablename__ = "subagents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("projects.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_examples: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=True)
    trigger_keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=True)
    model: Mapped[str] = mapped_column(String(50), default="inherit", nullable=False)
    color: Mapped[str] = mapped_column(String(20), default="blue", nullable=False)
    allowed_tools: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_mcp_servers: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    max_iterations: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    total_invocations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_execution_time_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    success_rate: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    spawn_policy_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    tool_policy_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    identity_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    project: Mapped[Optional["Project"]] = relationship(foreign_keys=[project_id])


class SubAgentTemplate(Base):
    """
    SubAgent Template for the Template Marketplace.

    Stores reusable SubAgent configurations that can be installed
    (instantiated as SubAgents) by tenants. Supports versioning,
    categorization, and search.
    """

    __tablename__ = "subagent_templates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="general")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=True)
    trigger_examples: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=True)
    model: Mapped[str] = mapped_column(String(50), default="inherit", nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    max_iterations: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    allowed_tools: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["*"], nullable=False)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    install_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rating: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "version", name="uq_template_tenant_name_version"),
    )


class MCPServer(Base):
    """
    MCP Server configuration for the MCP Ecosystem Integration.

    Represents an external MCP server that provides tools and capabilities
    to the agent system via the Model Context Protocol.

    Project-level scoping: each MCP server belongs to a specific project
    and runs inside that project's sandbox container.
    """

    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id"), nullable=False, index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("projects.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    server_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # stdio, sse, http, websocket
    transport_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    runtime_status: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    discovered_tools: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship(foreign_keys=[tenant_id])
    project: Mapped["Project"] = relationship(foreign_keys=[project_id])

    __table_args__ = (
        Index("ix_mcp_servers_project_enabled", "project_id", "enabled"),
        Index("ix_mcp_servers_tenant_enabled", "tenant_id", "enabled"),
    )


class ProjectSandbox(Base):
    """
    Project-Sandbox lifecycle association.

    Manages the persistent mapping between a Project and its dedicated
    Sandbox instance. Each project has exactly one sandbox that:
    - Is created on first use (lazy initialization)
    - Remains running until project deletion or manual termination
    - Can be auto-restarted if unhealthy

    Supports both cloud sandboxes (Docker containers) and local sandboxes
    (user's machine via WebSocket tunnel).

    This enables efficient sandbox reuse and lifecycle management.
    """

    __tablename__ = "project_sandboxes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id"), nullable=False, index=True
    )
    sandbox_id: Mapped[str] = mapped_column(String, nullable=False, index=True, unique=True)
    sandbox_type: Mapped[str] = mapped_column(
        String(20), default="cloud", nullable=False
    )  # cloud, local
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )  # pending, creating, running, unhealthy, stopped, terminated, error, connecting, disconnected
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    health_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    local_config: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )  # Local sandbox connection config

    # Relationships
    project: Mapped["Project"] = relationship(
        foreign_keys=[project_id],
        backref="sandbox_association",
    )
    tenant: Mapped["Tenant"] = relationship(
        foreign_keys=[tenant_id],
    )

    # Indexes for common queries
    __table_args__ = (
        Index("ix_project_sandboxes_status_accessed", "status", "last_accessed_at"),
        Index("ix_project_sandboxes_tenant_status", "tenant_id", "status"),
    )


class ToolEnvironmentVariableRecord(IdGeneratorMixin, Base):
    """
    Tool Environment Variable storage for agent tools.

    Stores encrypted environment variables needed by agent tools,
    scoped by tenant and optionally by project for multi-tenant isolation.

    Key design considerations:
    1. Tenant-level isolation: Variables are always scoped to a tenant
    2. Tool namespacing: Different tools can have same-named variables
    3. Project override: Project-level variables override tenant-level
    4. Encrypted storage: Values are AES-256-GCM encrypted at rest
    """

    __tablename__ = "tool_environment_variables"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    variable_name: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scope: Mapped[str] = mapped_column(
        String(20), default="tenant", nullable=False
    )  # tenant | project
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship(foreign_keys=[tenant_id])
    project: Mapped[Optional["Project"]] = relationship(foreign_keys=[project_id])

    # Unique constraint: tenant + project + tool + variable name
    # Note: project_id can be NULL for tenant-level variables
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "tool_name",
            "variable_name",
            name="uq_tool_env_var_tenant_project_tool_name",
        ),
        Index("ix_tool_env_var_tenant_tool", "tenant_id", "tool_name"),
        Index("ix_tool_env_var_project_tool", "project_id", "tool_name"),
    )


class HITLRequest(IdGeneratorMixin, Base):
    """
    Human-in-the-Loop Request storage for agent interactions.

    Stores pending HITL requests (clarification, decision, env_var) to enable:
    1. Recovery after page refresh - users can see pending requests
    2. Cross-process communication - API can find requests from Worker
    3. Audit trail - track all HITL interactions

    Request lifecycle:
    - pending: Waiting for user response
    - answered: User provided response
    - timeout: Request expired without response
    - cancelled: Request was cancelled
    """

    __tablename__ = "hitl_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # clarification | decision | env_var
    conversation_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Request content (JSON)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # List of options
    context: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )  # Additional context
    request_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )  # Tool-specific metadata

    # Response
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )  # pending | answered | timeout | cancelled
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship(foreign_keys=[tenant_id])
    project: Mapped["Project"] = relationship(foreign_keys=[project_id])
    user: Mapped[Optional["User"]] = relationship(foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_hitl_requests_conversation_status", "conversation_id", "status"),
        Index("ix_hitl_requests_tenant_project_status", "tenant_id", "project_id", "status"),
        Index("ix_hitl_requests_expires_at", "expires_at"),
    )


class MessageExecutionStatus(Base):
    """
    Tracks the execution status of an assistant message generation.

    This is different from AgentExecution which tracks individual Think-Act-Observe cycles.
    MessageExecutionStatus tracks the overall message generation process, enabling:
    - Detection of in-progress executions after page refresh
    - Event recovery from the correct position
    - Proper state restoration in the frontend

    One MessageExecutionStatus per assistant message.
    """

    __tablename__ = "message_execution_status"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # Same as message_id
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[str] = mapped_column(
        String, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    # Execution status: pending | running | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)

    # Event tracking for recovery
    last_event_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Error information
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    conversation: Mapped["Conversation"] = relationship(foreign_keys=[conversation_id])
    message: Mapped["Message"] = relationship(foreign_keys=[message_id])
    tenant: Mapped["Tenant"] = relationship(foreign_keys=[tenant_id])
    project: Mapped["Project"] = relationship(foreign_keys=[project_id])

    __table_args__ = (
        Index("ix_msg_exec_status_conv_status", "conversation_id", "status"),
        Index("ix_msg_exec_status_tenant_project", "tenant_id", "project_id", "status"),
    )


# ===== PROMPT TEMPLATE MODEL =====


class PromptTemplateModel(IdGeneratorMixin, Base):
    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id"), nullable=False, index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("projects.id"), nullable=True, index=True
    )
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general", index=True)
    variables: Mapped[dict[str, Any]] = mapped_column(JSON, default=list, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    __table_args__ = (UniqueConstraint("tenant_id", "title", name="uq_tenant_template_title"),)


# ===== AGENT TASK MODEL =====


class AgentTaskModel(IdGeneratorMixin, Base):
    """Persistent task items managed by agent TodoRead/TodoWrite tools."""

    __tablename__ = "agent_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )
    priority: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="medium",
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )

    __table_args__ = (Index("ix_agent_tasks_conv_status", "conversation_id", "status"),)


class MCPAppModel(Base):
    """
    MCP App persistence model.

    Stores MCP Apps - interactive HTML interfaces declared by MCP tools
    via the _meta.ui.resourceUri extension.
    """

    __tablename__ = "mcp_apps"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id"), nullable=False, index=True
    )
    server_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    server_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    ui_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    resource_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resource_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resource_resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user_added")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="discovered")
    lifecycle_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship(foreign_keys=[tenant_id])
    project: Mapped["Project"] = relationship(foreign_keys=[project_id])
    server: Mapped[Optional["MCPServer"]] = relationship(foreign_keys=[server_id])

    __table_args__ = (
        UniqueConstraint(
            "project_id", "server_name", "tool_name", name="uq_mcp_app_project_server_tool"
        ),
        Index("ix_mcp_apps_project_status", "project_id", "status"),
        Index("ix_mcp_apps_tenant_status", "tenant_id", "status"),
    )


class MCPLifecycleEvent(Base):
    """Lifecycle/audit event log for MCP server and app operations."""

    __tablename__ = "mcp_lifecycle_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    server_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("mcp_servers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    app_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("mcp_apps.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_mcp_lifecycle_events_project_created", "project_id", "created_at"),
        Index("ix_mcp_lifecycle_events_server_created", "server_id", "created_at"),
        Index("ix_mcp_lifecycle_events_app_created", "app_id", "created_at"),
    )


class MemoryChunk(Base):
    """Chunked memory content for hybrid search (pgvector + FTS).

    Stores text chunks from memories, conversations, and episodes
    with vector embeddings and tsvector for full-text search.
    """

    __tablename__ = "memory_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # memory, conversation, episode
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[Any] | None] = mapped_column(
        Vector() if Vector else JSON, nullable=True
    )  # Dimensionless vector — accepts any embedding dimension
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    category: Mapped[str] = mapped_column(
        String(20), default="other"
    )  # preference, fact, decision, entity, other
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship(foreign_keys=[project_id])

    __table_args__ = (
        Index("ix_chunks_project_source", "project_id", "source_type"),
        Index("ix_chunks_content_hash", "content_hash"),
    )


class AuditLog(IdGeneratorMixin, Base):
    """Audit log for tracking sensitive operations."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, server_default=func.now()
    )
    actor: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, index=True)
    resource_type: Mapped[str] = mapped_column(String, index=True)
    resource_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (Index("ix_audit_logs_tenant_action", "tenant_id", "action"),)


class CronJobModel(Base):
    __tablename__ = "cron_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    delete_after_run: Mapped[bool] = mapped_column(Boolean, default=False)

    schedule_type: Mapped[str] = mapped_column(String(50), nullable=False)
    schedule_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    delivery_type: Mapped[str] = mapped_column(String(50), nullable=False, default="none")
    delivery_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    conversation_mode: Mapped[str] = mapped_column(String(50), default="reuse")
    conversation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    timezone: Mapped[str] = mapped_column(String(100), default="UTC")
    stagger_seconds: Mapped[int] = mapped_column(Integer, default=0)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)

    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    runs: Mapped[list["CronJobRunModel"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_cron_jobs_project_enabled", "project_id", "enabled"),)


class CronJobRunModel(Base):
    __tablename__ = "cron_job_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String, ForeignKey("cron_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    trigger_type: Mapped[str] = mapped_column(String(50), default="scheduled")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    conversation_id: Mapped[str | None] = mapped_column(String, nullable=True)

    job: Mapped["CronJobModel"] = relationship(back_populates="runs")

    __table_args__ = (
        Index("ix_cron_job_runs_job_status", "job_id", "status"),
        Index("ix_cron_job_runs_project_started", "project_id", "started_at"),
    )


class AgentDefinitionModel(Base):
    __tablename__ = "agent_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("projects.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_examples: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=True)
    trigger_keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=True)
    model: Mapped[str] = mapped_column(String(50), default="inherit", nullable=False)
    persona_files: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=True)
    allowed_tools: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_mcp_servers: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    max_iterations: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    workspace_dir: Mapped[str | None] = mapped_column(String, nullable=True)
    workspace_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    can_spawn: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_spawn_depth: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    agent_to_agent_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    agent_to_agent_allowlist: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    discoverable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="custom", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    fallback_models: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=True)
    total_invocations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_execution_time_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    success_rate: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    session_policy: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    delegate_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    project: Mapped[Optional["Project"]] = relationship(foreign_keys=[project_id])


class AgentBindingModel(Base):
    __tablename__ = "agent_bindings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agent_definitions.id"),
        nullable=False,
        index=True,
    )
    channel_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    channel_id: Mapped[str | None] = mapped_column(String, nullable=True)
    account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    peer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    agent: Mapped["AgentDefinitionModel"] = relationship(foreign_keys=[agent_id])

    __table_args__ = (
        Index(
            "ix_agent_bindings_routing",
            "tenant_id",
            "channel_type",
            "channel_id",
        ),
    )


class MessageBindingModel(Base):
    __tablename__ = "message_bindings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    filter_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_message_bindings_scope", "scope", "scope_id"),)


# ---------------------------------------------------------------------------
# Multi-Agent Graph Orchestration Models
# ---------------------------------------------------------------------------


class AgentGraphModel(Base, IdGeneratorMixin):
    """Persisted DAG definition for multi-agent orchestration."""

    __tablename__ = "agent_graphs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pattern: Mapped[str] = mapped_column(String(30), nullable=False)
    nodes_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    edges_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    shared_context_keys: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    max_total_steps: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Optional["Project"]] = relationship(foreign_keys=[project_id])
    runs: Mapped[list["GraphRunModel"]] = relationship(
        back_populates="graph", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "project_id", "name", name="uq_agent_graphs_tenant_project_name"
        ),
        Index("ix_agent_graphs_project_active", "project_id", "is_active"),
    )


class GraphRunModel(Base, IdGeneratorMixin):
    """Persisted execution instance of an AgentGraph."""

    __tablename__ = "graph_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    graph_id: Mapped[str] = mapped_column(
        String, ForeignKey("agent_graphs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    shared_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    current_node_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    total_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_total_steps: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    graph: Mapped["AgentGraphModel"] = relationship(back_populates="runs")
    node_executions: Mapped[list["NodeExecutionModel"]] = relationship(
        back_populates="graph_run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_graph_runs_conversation_status", "conversation_id", "status"),
        Index("ix_graph_runs_graph_status", "graph_id", "status"),
    )


class NodeExecutionModel(Base, IdGeneratorMixin):
    """Persisted execution record for a single node within a graph run."""

    __tablename__ = "node_executions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    graph_run_id: Mapped[str] = mapped_column(
        String, ForeignKey("graph_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(String, nullable=False)
    agent_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    input_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    graph_run: Mapped["GraphRunModel"] = relationship(back_populates="node_executions")

    __table_args__ = (
        Index("ix_node_executions_run_node", "graph_run_id", "node_id"),
        Index("ix_node_executions_status", "graph_run_id", "status"),
    )


class CyberObjectiveModel(Base):
    __tablename__ = "cyber_objectives"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    obj_type: Mapped[str] = mapped_column(String(20), default="objective", nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("cyber_objectives.id", ondelete="SET NULL"),
        nullable=True,
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    workspace: Mapped["WorkspaceModel"] = relationship(back_populates="objectives")
    parent: Mapped["CyberObjectiveModel | None"] = relationship(
        remote_side="CyberObjectiveModel.id", foreign_keys=[parent_id]
    )
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])

    __table_args__ = (
        Index("ix_cyber_objectives_workspace", "workspace_id"),
        Index(
            "ix_cyber_objectives_workspace_type",
            "workspace_id",
            "obj_type",
        ),
        Index("ix_cyber_objectives_parent", "parent_id"),
    )


class CyberGeneModel(Base):
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

    workspace: Mapped["WorkspaceModel"] = relationship(back_populates="genes")
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])

    __table_args__ = (
        Index("ix_cyber_genes_workspace", "workspace_id"),
        Index("ix_cyber_genes_workspace_category", "workspace_id", "category"),
    )


class WorkspaceMessageModel(Base):
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

    workspace: Mapped["WorkspaceModel"] = relationship(foreign_keys=[workspace_id])

    __table_args__ = (
        Index("ix_workspace_messages_workspace_created", "workspace_id", "created_at"),
        Index("ix_workspace_messages_parent", "parent_message_id"),
    )


# Runtime import to register ChannelConfigModel on Base.metadata so that
# SQLAlchemy can resolve the string reference in Project.channel_configs.
# This must come after Base and all models above are defined to avoid
# circular imports (channel_models.py imports Base from this module).
from src.infrastructure.adapters.secondary.persistence.channel_models import (  # noqa: E402
    ChannelConfigModel as ChannelConfigModel,
)


class TenantEventLogModel(Base):
    __tablename__ = "tenant_event_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), index=True
    )

    __table_args__ = (Index("ix_tenant_event_logs_tenant_created", "tenant_id", "created_at"),)


class ClusterModel(Base):
    """Compute cluster registered to a tenant."""

    __tablename__ = "clusters"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    compute_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="docker")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="disconnected")
    health_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_health_check: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    proxy_endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str] = mapped_column(String, default="", nullable=False)
    provider_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped["Tenant"] = relationship(foreign_keys=[tenant_id])

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_clusters_tenant_name"),
        Index("ix_clusters_tenant_status", "tenant_id", "status"),
    )


class WebhookModel(Base):
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret: Mapped[str | None] = mapped_column(String(512), nullable=True)
    events: Mapped[list[str]] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_webhooks_tenant_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


# ---------------------------------------------------------------------------
# Instance / Deploy / Gene / Genome models
# ---------------------------------------------------------------------------


class InstanceModel(Base):
    """AI agent instance belonging to a tenant."""

    __tablename__ = "instances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cluster_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    namespace: Mapped[str | None] = mapped_column(String(100), nullable=True)
    image_version: Mapped[str] = mapped_column(String(100), default="latest")
    replicas: Mapped[int] = mapped_column(Integer, default=1)
    cpu_request: Mapped[str] = mapped_column(String(20), default="100m")
    cpu_limit: Mapped[str] = mapped_column(String(20), default="500m")
    mem_request: Mapped[str] = mapped_column(String(20), default="256Mi")
    mem_limit: Mapped[str] = mapped_column(String(20), default="512Mi")
    service_type: Mapped[str] = mapped_column(String(20), default="ClusterIP")
    ingress_domain: Mapped[str | None] = mapped_column(String(200), nullable=True)
    proxy_token: Mapped[str | None] = mapped_column(String(200), nullable=True)
    env_vars: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    quota_cpu: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quota_memory: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quota_max_pods: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_class: Mapped[str | None] = mapped_column(String(50), nullable=True)
    storage_size: Mapped[str | None] = mapped_column(String(20), nullable=True)
    advanced_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    llm_providers: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    pending_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    available_replicas: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="creating")
    health_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    current_revision: Mapped[int] = mapped_column(Integer, default=0)
    compute_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    runtime: Mapped[str] = mapped_column(String(50), default="default")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    hex_position_q: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hex_position_r: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    agent_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    theme_color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_instances_tenant_slug"),
        Index("ix_instances_tenant_status", "tenant_id", "status"),
    )


class InstanceMemberModel(Base):
    """Membership link between a user and an instance."""

    __tablename__ = "instance_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    instance_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instances.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("instance_id", "user_id", name="uq_instance_members_instance_user"),
    )


class DeployRecordModel(Base):
    """Deployment record for an instance revision."""

    __tablename__ = "deploy_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    instance_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instances.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    image_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    replicas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InstanceTemplateModel(Base):
    """Predefined instance configuration template."""

    __tablename__ = "instance_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(200), nullable=True)
    image_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    default_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    install_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TemplateItemModel(Base):
    """Item within an instance template (e.g. a gene to install)."""

    __tablename__ = "template_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instance_templates.id", ondelete="CASCADE"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(20), default="gene")
    item_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GeneMarketModel(Base):
    """Gene listing in the marketplace."""

    __tablename__ = "gene_market"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="official")
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(200), nullable=True)
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    dependencies: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    synergies: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    parent_gene_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by_instance_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    install_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_rating: Mapped[float] = mapped_column(Float, default=0.0)
    effectiveness_score: Mapped[float] = mapped_column(Float, default=0.0)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    visibility: Mapped[str] = mapped_column(String(20), default="public")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GenomeModel(Base):
    """Curated gene bundle (genome)."""

    __tablename__ = "genomes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(200), nullable=True)
    gene_slugs: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    config_override: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    install_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_rating: Mapped[float] = mapped_column(Float, default=0.0)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    visibility: Mapped[str] = mapped_column(String(20), default="public")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InstanceGeneModel(Base):
    """Gene installed on a specific instance."""

    __tablename__ = "instance_genes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    instance_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instances.id", ondelete="CASCADE"), nullable=False
    )
    gene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("gene_market.id", ondelete="CASCADE"), nullable=False
    )
    genome_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="installing")
    installed_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    learning_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    agent_self_eval: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    variant_published: Mapped[bool] = mapped_column(Boolean, default=False)
    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("instance_id", "gene_id", name="uq_instance_genes_instance_gene"),
    )


class GeneEffectLogModel(Base):
    """Metric log for gene effectiveness tracking."""

    __tablename__ = "gene_effect_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(36), nullable=False)
    gene_id: Mapped[str] = mapped_column(String(36), nullable=False)
    metric_type: Mapped[str] = mapped_column(String(30), default="custom")
    value: Mapped[float] = mapped_column(Float, default=0.0)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GeneReviewModel(Base):
    """User review of a gene."""

    __tablename__ = "gene_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    gene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("gene_market.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GeneRatingModel(Base):
    """Numeric rating for a gene."""

    __tablename__ = "gene_ratings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    gene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("gene_market.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, default=0)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("gene_id", "user_id", name="uq_gene_ratings_gene_user"),)


class GenomeRatingModel(Base):
    """Numeric rating for a genome."""

    __tablename__ = "genome_ratings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    genome_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("genomes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, default=0)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("genome_id", "user_id", name="uq_genome_ratings_genome_user"),
    )


class EvolutionEventModel(Base):
    """Evolution event log for an instance."""

    __tablename__ = "evolution_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    instance_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instances.id", ondelete="CASCADE"), nullable=False
    )
    gene_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    genome_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(30), default="learned")
    gene_name: Mapped[str] = mapped_column(String(100), default="")
    gene_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrgGenePolicyModel(Base):
    """Organization-level gene policy configuration."""

    __tablename__ = "org_gene_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    policy_key: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_org_gene_policies_tenant", "tenant_id"),)


class RegistryConfigModel(Base):
    """Container registry configuration per tenant."""

    __tablename__ = "registry_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    registry_type: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    password_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_registry_configs_tenant", "tenant_id"),)


class DecisionRecordModel(Base):
    """Decision record for agent trust and governance."""

    __tablename__ = "decision_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_instance_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(50), nullable=False)
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    outcome: Mapped[str] = mapped_column(String(30), default="pending")
    reviewer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    review_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_decision_records_tenant_ws", "tenant_id", "workspace_id"),)


class TrustPolicyModel(Base):
    """Trust policy granting agent permissions."""

    __tablename__ = "trust_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_instance_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    granted_by: Mapped[str] = mapped_column(String(36), nullable=False)
    grant_type: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_trust_policies_tenant_ws", "tenant_id", "workspace_id"),)


class InvitationModel(Base):
    """Tenant member invitation."""

    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="member")
    token: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    invited_by: Mapped[str] = mapped_column(String(36), nullable=False)
    accepted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_invitations_tenant", "tenant_id"),
        Index("ix_invitations_token", "token"),
    )


class SmtpConfigModel(Base):
    """SMTP email configuration per tenant."""

    __tablename__ = "smtp_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    smtp_host: Mapped[str] = mapped_column(String(255), nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    smtp_username: Mapped[str] = mapped_column(String(255), nullable=False)
    smtp_password_encrypted: Mapped[str] = mapped_column(String(500), nullable=False)
    from_email: Mapped[str] = mapped_column(String(255), nullable=False)
    from_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    use_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_smtp_configs_tenant", "tenant_id"),)


class EventLogModel(Base):
    """Observability event log entry."""

    __tablename__ = "observability_event_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_node_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_node_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_event_logs_tenant_ws", "tenant_id", "workspace_id"),)


class MessageQueueItemModel(Base):
    """Observability message queue item."""

    __tablename__ = "observability_message_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_node_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_node_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_mq_items_tenant_ws", "tenant_id", "workspace_id"),)


class ObservabilityDeadLetterModel(Base):
    """Observability dead letter queue entry."""

    __tablename__ = "observability_dead_letters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    original_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_node_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_node_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retried_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_dead_letters_tenant_ws", "tenant_id", "workspace_id"),)


class CircuitStateModel(Base):
    """Observability circuit breaker state."""

    __tablename__ = "observability_circuit_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(36), nullable=False)
    state: Mapped[str] = mapped_column(String(30), default="closed")
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_circuit_states_tenant_ws", "tenant_id", "workspace_id"),)


class NodeCardModel(Base):
    """Observability node card metadata."""

    __tablename__ = "observability_node_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_node_cards_tenant_ws", "tenant_id", "workspace_id"),)


class InstanceChannelConfigModel(Base):
    """Instance-scoped channel configuration."""

    __tablename__ = "instance_channel_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    instance_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    last_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlanModel(Base):
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

    nodes: Mapped[list["PlanNodeModel"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_workspace_plans_workspace", "workspace_id"),)


class PlanNodeModel(Base):
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

    plan: Mapped["PlanModel"] = relationship(back_populates="nodes")

    __table_args__ = (
        Index("ix_workspace_plan_nodes_plan", "plan_id"),
        Index("ix_workspace_plan_nodes_parent", "parent_id"),
        Index("ix_workspace_plan_nodes_workspace_task", "workspace_task_id"),
    )


class WorkspacePlanBlackboardEntryModel(Base):
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
            "plan_id",
            "key",
            "version",
            name="uq_workspace_plan_blackboard_plan_key_version",
        ),
        Index("ix_workspace_plan_blackboard_plan", "plan_id"),
        Index("ix_workspace_plan_blackboard_plan_key", "plan_id", "key"),
    )


class WorkspacePlanEventModel(Base):
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


class WorkspacePlanOutboxModel(Base):
    """Durable work queue record for autonomous workspace plan progression."""

    __tablename__ = "workspace_plan_outbox"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspace_plans.id", ondelete="CASCADE"), nullable=False
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


class PendingReviewModel(Base):
    """HITL ``blocking_human_only`` pending review (Track B P2-3 phase-2)."""

    __tablename__ = "pending_reviews"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    scope_agent_id: Mapped[str] = mapped_column(String, nullable=False)
    effective_category: Mapped[str] = mapped_column(String(32), nullable=False)
    declared_category: Mapped[str] = mapped_column(String(32), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    urgency: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    proposed_fallback: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    structurally_upgraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_pending_reviews_conversation_status", "conversation_id", "status"),
        Index("ix_pending_reviews_agent", "scope_agent_id"),
    )


class DecisionLogModel(Base):
    """Audit row for a judgmental tool-call (Track B P2-3 phase-2).

    Every Agent-First decision (multi-agent action tools + supervisor
    ``verdict``) must persist a row here; this is the forensic trail
    backing the top-level Agent First rule.
    """

    __tablename__ = "decision_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(String, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index(
            "ix_decision_logs_conversation_created",
            "conversation_id",
            "created_at",
        ),
        Index("ix_decision_logs_agent", "agent_id"),
        Index("ix_decision_logs_tool", "tool_name"),
    )
