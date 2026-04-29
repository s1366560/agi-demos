"""SQLAlchemy models for skill evolution persistence.

These models use the same ``Base`` declarative base as the rest of the
application so they participate in Alembic migrations and metadata
operations.  The plugin loader imports this module at startup to ensure
tables are registered.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.infrastructure.adapters.secondary.persistence.models import Base


class SkillEvolutionSession(Base):
    """Captured agent session data for a single skill execution.

    Each row corresponds to one turn where a skill was active.
    Raw tool-call traces and LLM-generated summaries are stored
    as JSON columns.
    """

    __tablename__ = "skill_evolution_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    skill_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    user_query: Mapped[str] = mapped_column(Text, nullable=False)
    trajectory: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    judge_scores: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    execution_time_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"SkillEvolutionSession(id={self.id!r}, skill_name={self.skill_name!r}, "
            f"conversation_id={self.conversation_id!r}, processed={self.processed})"
        )


class SkillEvolutionJob(Base):
    """A single evolution job — the decision and candidate output for one skill.

    Created by the evolution engine after analysing a batch of sessions.
    When ``status`` is ``applied``, ``skill_version_id`` points to the
    SkillVersion that was created by the merge step.
    """

    __tablename__ = "skill_evolution_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    skill_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    candidate_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), default="pending_review", nullable=False, index=True
    )
    skill_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"SkillEvolutionJob(id={self.id!r}, skill_name={self.skill_name!r}, "
            f"action={self.action!r}, status={self.status!r})"
        )
