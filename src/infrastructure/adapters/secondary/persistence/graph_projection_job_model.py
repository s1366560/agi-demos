"""Durable input and authority for a package-computed knowledge graph projection."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.adapters.secondary.persistence.models import Base


class GraphProjectionJob(Base):
    __tablename__ = "graph_projection_jobs"
    __table_args__ = (Index("ix_graph_projection_retry", "phase", "retry_at"),)

    task_id: Mapped[str] = mapped_column(
        String, ForeignKey("task_logs.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(String)
    project_id: Mapped[str] = mapped_column(String)
    memory_id: Mapped[str] = mapped_column(String, ForeignKey("memories.id", ondelete="CASCADE"))
    source_revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String)
    author_id: Mapped[str] = mapped_column(String)
    pin: Mapped[dict[str, Any]] = mapped_column(JSON)
    tool: Mapped[str] = mapped_column(String)
    phase: Mapped[str] = mapped_column(String)
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
