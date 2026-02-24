"""
LLM Provider SQLAlchemy ORM Models

This module contains SQLAlchemy ORM models for LLM provider configuration.
These models map to the database tables created in the Alembic migration.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.adapters.secondary.persistence.models import Base


class LLMProvider(Base):
    """
    LLM Provider configuration ORM model.

    Stores LLM provider configurations with encrypted API keys and model settings.
    """

    __tablename__ = "llm_providers"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )

    # Provider identification
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Credentials (encrypted at rest)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    # API configuration
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Model configuration
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    llm_small_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reranker_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Provider-specific configuration (JSONB for flexibility)
    config: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False
    )

    # Status flags
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    tenant_mappings: Mapped[list["TenantProviderMapping"]] = relationship(
        "TenantProviderMapping", back_populates="provider", cascade="all, delete-orphan"
    )
    health_checks: Mapped[list["ProviderHealth"]] = relationship(
        "ProviderHealth", back_populates="provider", cascade="all, delete-orphan"
    )
    usage_logs: Mapped[list["LLMUsageLog"]] = relationship(
        "LLMUsageLog", back_populates="provider", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="llm_providers_name_not_empty"),
        CheckConstraint(
            "provider_type IN ('openai', 'dashscope', 'gemini', 'anthropic', 'groq', 'azure_openai', 'cohere', 'mistral', 'bedrock', 'vertex', 'deepseek', 'minimax', 'zai', 'kimi', 'ollama', 'lmstudio')",
            name="llm_providers_valid_type",
        ),
        Index("idx_llm_providers_type", "provider_type"),
        Index("idx_llm_providers_active", "is_active", postgresql_where=is_active),  # type: ignore
        Index("idx_llm_providers_default", "is_default", postgresql_where=is_default),  # type: ignore
    )

    def __repr__(self) -> str:
        return f"<LLMProvider(id={self.id}, name='{self.name}', type='{self.provider_type}')>"


class TenantProviderMapping(Base):
    """
    Tenant to Provider mapping ORM model.

    Maps tenants (groups) to specific LLM providers with priority for fallback.
    """

    __tablename__ = "tenant_provider_mappings"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )

    # Mapping
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(20), default="llm", nullable=False)
    provider_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_providers.id", ondelete="CASCADE"), nullable=False
    )

    # Priority for fallback (lower = higher priority)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )

    # Relationships
    provider: Mapped["LLMProvider"] = relationship("LLMProvider", back_populates="tenant_mappings")

    __table_args__ = (
        CheckConstraint(
            "length(trim(tenant_id)) > 0", name="tenant_provider_mappings_tenant_not_empty"
        ),
        CheckConstraint(
            "operation_type IN ('llm', 'embedding', 'rerank')",
            name="tenant_provider_mappings_valid_operation",
        ),
        UniqueConstraint(
            "tenant_id",
            "provider_id",
            "operation_type",
            name="tenant_provider_mappings_unique_tenant_provider_op",
        ),
        Index("idx_tenant_mappings_tenant", "tenant_id"),
        Index("idx_tenant_mappings_operation", "operation_type"),
        Index("idx_tenant_mappings_provider", "provider_id"),
        Index("idx_tenant_mappings_priority", "priority"),
    )

    def __repr__(self) -> str:
        return f"<TenantProviderMapping(tenant_id='{self.tenant_id}', provider_id={self.provider_id}, priority={self.priority})>"


class ProviderHealth(Base):
    """
    Provider health status ORM model.

    Tracks health status of providers over time with time-series data.
    """

    __tablename__ = "provider_health"

    # Composite key: provider_id + timestamp
    provider_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_providers.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    last_check: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, default=func.now(), nullable=False
    )

    # Health status
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    provider: Mapped["LLMProvider"] = relationship("LLMProvider", back_populates="health_checks")

    __table_args__ = (
        CheckConstraint(
            "status IN ('healthy', 'degraded', 'unhealthy')", name="provider_health_valid_status"
        ),
        Index("idx_provider_health_status", "provider_id", "last_check"),  # Use DESC in queries
        Index("idx_provider_health_unhealthy", "status", postgresql_where="status != 'healthy'"),
        Index("idx_provider_health_retention", "last_check"),
    )

    def __repr__(self) -> str:
        return f"<ProviderHealth(provider_id={self.provider_id}, status='{self.status}', last_check={self.last_check})>"


class LLMUsageLog(Base):
    """
    LLM usage tracking ORM model.

    Tracks token usage, costs, and operation metrics per provider and tenant.
    """

    __tablename__ = "llm_usage_logs"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )

    # Context
    provider_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True
    )
    tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Operation details
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Token usage
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Cost tracking (optional, not all providers return this)
    cost_usd: Mapped[float | None] = mapped_column(nullable=True)  # Using Numeric in DB

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )

    # Relationships
    provider: Mapped[Optional["LLMProvider"]] = relationship(
        "LLMProvider", back_populates="usage_logs"
    )

    @property
    def total_tokens(self) -> int:
        """Calculate total tokens"""
        return self.prompt_tokens + self.completion_tokens

    __table_args__ = (
        CheckConstraint(
            "operation_type IN ('llm', 'embedding', 'rerank')",
            name="llm_usage_logs_valid_operation",
        ),
        CheckConstraint(
            "prompt_tokens >= 0 AND completion_tokens >= 0",
            name="llm_usage_logs_non_negative_tokens",
        ),
        Index("idx_llm_usage_provider", "provider_id", "created_at"),  # Use DESC in queries
        Index(
            "idx_llm_usage_tenant",
            "tenant_id",
            "created_at",
            postgresql_where="tenant_id IS NOT NULL",
        ),
        Index("idx_llm_usage_operation", "operation_type", "created_at"),
        Index("idx_llm_usage_date", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<LLMUsageLog(id={self.id}, operation='{self.operation_type}', tokens={self.total_tokens})>"
