"""Legacy executions that must drain before Rust scheduler ownership can begin."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.adapters.secondary.persistence.models import Base


class LegacyCronAdmissionModel(Base):
    """No expiry: unknown delivery remains a cutover blocker until actual completion."""

    __tablename__ = "agistack_legacy_cron_admissions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    scope_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("agistack_cron_scheduler_owners.scope_id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    job_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    message_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    owner_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_phase: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_nonce: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    admitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "execution_phase IN ('ready', 'running', 'waiting', 'terminal')",
            name="ck_legacy_cron_admission_phase",
        ),
        CheckConstraint(
            "(execution_phase IN ('ready', 'waiting') AND execution_nonce IS NULL) OR "
            "(execution_phase IN ('running', 'terminal') AND execution_nonce IS NOT NULL)",
            name="ck_legacy_cron_admission_nonce",
        ),
        CheckConstraint(
            "(status = 'active' AND execution_phase <> 'terminal') OR "
            "(status IN ('success', 'failed') AND execution_phase = 'terminal')",
            name="ck_legacy_cron_admission_phase_status",
        ),
        CheckConstraint("owner_epoch >= 0", name="ck_legacy_cron_admission_epoch"),
        CheckConstraint(
            "status IN ('active', 'success', 'failed')", name="ck_legacy_cron_admission_status"
        ),
        CheckConstraint(
            "(status = 'active' AND terminal_at IS NULL) OR "
            "(status IN ('success', 'failed') AND terminal_at IS NOT NULL)",
            name="ck_legacy_cron_admission_terminal",
        ),
        Index("ix_legacy_cron_admission_scope_status", "scope_id", "status"),
    )
