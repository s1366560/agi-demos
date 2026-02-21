import uuid
from datetime import datetime
from typing import List, Optional

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
)
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


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    full_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    api_keys: Mapped[List["APIKey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    tenants: Mapped[List["UserTenant"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    projects: Mapped[List["UserProject"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    memories: Mapped[List["Memory"]] = relationship(
        back_populates="author", cascade="all, delete-orphan"
    )
    owned_tenants: Mapped[List["Tenant"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    owned_projects: Mapped[List["Project"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    roles: Mapped[List["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Role(IdGeneratorMixin, Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    permissions: Mapped[List["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    users: Mapped[List["UserRole"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class Permission(IdGeneratorMixin, Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True, index=True)  # e.g. "user:create"
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    roles: Mapped[List["RolePermission"]] = relationship(
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
    tenant_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("tenants.id"), nullable=True
    )
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
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="api_keys")


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(
        String, unique=True, nullable=False
    )  # URL-friendly identifier
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)

    # Configuration limits
    plan: Mapped[str] = mapped_column(String, default="free")
    max_projects: Mapped[int] = mapped_column(Integer, default=10)
    max_users: Mapped[int] = mapped_column(Integer, default=5)
    max_storage: Mapped[int] = mapped_column(BigInteger, default=1073741824)  # 1GB in bytes

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    owner: Mapped["User"] = relationship(back_populates="owned_tenants")
    users: Mapped[List["UserTenant"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    projects: Mapped[List["Project"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    memory_rules: Mapped[dict] = mapped_column(JSON, default=dict)
    graph_config: Mapped[dict] = mapped_column(JSON, default=dict)
    sandbox_type: Mapped[str] = mapped_column(
        String(20), default="cloud", nullable=False
    )  # cloud, local
    sandbox_config: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )  # Local sandbox config when sandbox_type is "local"
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="projects")
    owner: Mapped["User"] = relationship(back_populates="owned_projects")
    users: Mapped[List["UserProject"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    memories: Mapped[List["Memory"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    entity_types: Mapped[List["EntityType"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    edge_types: Mapped[List["EdgeType"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    edge_maps: Mapped[List["EdgeTypeMap"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    channel_configs: Mapped[List["ChannelConfigModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    @property
    def member_ids(self) -> List[str]:
        return [up.user_id for up in self.users]


class UserTenant(Base):
    __tablename__ = "user_tenants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, default="member")  # owner, admin, member, guest
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="tenants")
    tenant: Mapped["Tenant"] = relationship(back_populates="users")


class UserProject(Base):
    __tablename__ = "user_projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, default="member")  # owner, admin, member, viewer
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="projects")
    project: Mapped["Project"] = relationship(back_populates="users")


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), default="text")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    entities: Mapped[list[dict]] = mapped_column(JSON, default=list)
    relationships: Mapped[list[dict]] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    author_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    collaborators: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default=DataStatus.ENABLED)
    processing_status: Mapped[str] = mapped_column(String, default=ProcessingStatus.PENDING)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    task_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )  # Task ID for SSE streaming
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
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    schema: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default=DataStatus.ENABLED)
    source: Mapped[str] = mapped_column(String, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="entity_types")


class EdgeType(Base):
    __tablename__ = "edge_types"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_edge_type_project_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    schema: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default=DataStatus.ENABLED)
    source: Mapped[str] = mapped_column(String, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
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
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    worker_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # Stores arguments
    progress: Mapped[int] = mapped_column(Integer, default=0)  # Task progress percentage (0-100)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # Task result data
    message: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Task status message

    # Association & Hierarchy
    entity_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    entity_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    parent_task_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryShare(Base):
    __tablename__ = "memory_shares"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    memory_id: Mapped[str] = mapped_column(String, ForeignKey("memories.id"), nullable=False)
    share_token: Mapped[Optional[str]] = mapped_column(
        String, unique=True, index=True, nullable=True
    )
    shared_with_user_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    shared_with_project_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("projects.id"), nullable=True
    )
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    shared_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
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
    data: Mapped[dict] = mapped_column(JSON, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    action_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

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
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    invoice_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    tenant: Mapped["Tenant"] = relationship(foreign_keys=[tenant_id])


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("tenants.id"), nullable=True
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

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
    agent_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Multi-level thinking support (work plan stored in work_plans table)
    workflow_pattern_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Plan Mode support
    current_mode: Mapped[str] = mapped_column(String(20), default="build", nullable=False)
    current_plan_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    parent_conversation_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=True, index=True
    )
    branch_point_message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship(foreign_keys=[project_id])
    tenant: Mapped["Tenant"] = relationship(foreign_keys=[tenant_id])
    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    messages: Mapped[List["Message"]] = relationship(
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
    tool_calls: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=True)
    tool_results: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Multi-level thinking support
    work_plan_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    task_step_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    thought_level: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Threading support
    reply_to_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("messages.id"), nullable=True, index=True
    )

    # Message versioning
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    original_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    executions: Mapped[List["AgentExecution"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )
    replies: Mapped[List["Message"]] = relationship(
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
    thought: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    observation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tool_input: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)
    tool_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Multi-level thinking support
    work_level_thought: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    task_level_thought: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    plan_steps: Mapped[Optional[list[dict]]] = mapped_column(JSON, nullable=True)
    current_step_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    workflow_pattern_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

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
    tool_input: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)
    tool_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # running, success, failed
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    step_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)  # Order within message
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

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
    message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    event_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    event_time_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # correlation_id links all events from a single user request
    correlation_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
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
    delta_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Full event data as JSON for completeness
    event_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
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
    message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    checkpoint_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    execution_state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    step_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
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
    snapshot_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowPattern(Base):
    """
    Workflow pattern for learning from successful agent executions.

    Tenant-level scoping (FR-019): Patterns are shared across all projects
    within a tenant but isolated between tenants.
    """

    __tablename__ = "workflow_patterns"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    pattern_signature: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    steps_json: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    # Legacy field for backward compatibility
    steps: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    tool_compositions: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    success_rate: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    # Legacy fields for backward compatibility
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_execution_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class ToolComposition(Base):
    """Tool composition for tracking effective tool combinations."""

    __tablename__ = "tool_compositions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tools: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    execution_template: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
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
    max_work_plan_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    tool_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    enabled_tools: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    disabled_tools: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
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
    project_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("projects.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default="keyword")
    trigger_patterns: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    tools: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    prompt_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    # New fields for three-level scoping
    scope: Mapped[str] = mapped_column(String(20), default="tenant", nullable=False, index=True)
    # scope: 'system' | 'tenant' | 'project'
    is_system_skill: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # True if this is a database copy of a system skill (for usage tracking)
    full_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Full SKILL.md content for Web UI editing
    # Version tracking
    current_version: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    version_label: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relationships
    project: Mapped[Optional["Project"]] = relationship(foreign_keys=[project_id])
    versions: Mapped[List["SkillVersion"]] = relationship(
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
    override_skill_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("skills.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
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
    version_label: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    skill_md_content: Mapped[str] = mapped_column(Text, nullable=False)
    resource_files: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    change_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(20), nullable=False, default="agent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    skill: Mapped["Skill"] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint("skill_id", "version_number", name="uq_skill_version_number"),
        Index("ix_skill_versions_skill_id", "skill_id"),
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
    project_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("projects.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
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
    display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="general")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trigger_keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=True)
    trigger_examples: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=True)
    model: Mapped[str] = mapped_column(String(50), default="inherit", nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    max_iterations: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    allowed_tools: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["*"], nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    install_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rating: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
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
    project_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("projects.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    server_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # stdio, sse, http, websocket
    transport_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    runtime_status: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    runtime_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    discovered_tools: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    sync_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship(foreign_keys=[tenant_id])
    project: Mapped["Project"] = relationship(foreign_keys=[project_id])


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
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    health_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    local_config: Mapped[dict] = mapped_column(
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
    project_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    variable_name: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scope: Mapped[str] = mapped_column(
        String(20), default="tenant", nullable=False
    )  # tenant | project
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
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
    message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Request content (JSON)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # List of options
    context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # Additional context
    request_metadata: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True
    )  # Tool-specific metadata

    # Response
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )  # pending | answered | timeout | cancelled
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

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
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

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
    project_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("projects.id"), nullable=True, index=True
    )
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general", index=True)
    variables: Mapped[dict] = mapped_column(JSON, default=list, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
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
    updated_at: Mapped[Optional[datetime]] = mapped_column(
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
    server_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    server_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    ui_metadata: Mapped[dict] = mapped_column(JSON, nullable=False)
    resource_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resource_uri: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    resource_mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    resource_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resource_resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user_added")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="discovered")
    lifecycle_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
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
    server_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("mcp_servers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    app_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("mcp_apps.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
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
    embedding: Mapped[Optional[list]] = mapped_column(
        Vector(1024) if Vector else JSON, nullable=True
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
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
    actor: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, index=True)
    resource_type: Mapped[str] = mapped_column(String, index=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (Index("ix_audit_logs_tenant_action", "tenant_id", "action"),)
