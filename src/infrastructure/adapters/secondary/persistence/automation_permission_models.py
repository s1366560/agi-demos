"""Exact invocation permission receipts; no dispatch authority is enabled here."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.adapters.secondary.persistence.models import Base


class AutomationPermissionIntentModel(Base):
    """Host-bound immutable intent; agents cannot supply host attestation fields."""

    __tablename__ = "agistack_automation_permission_intents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    job_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String, nullable=False)
    actor_api_key_id: Mapped[str | None] = mapped_column(String, nullable=True)
    runtime_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    invocation_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    tool_version: Mapped[str] = mapped_column(String, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("runtime_revision > 0", name="ck_automation_permission_revision"),
        CheckConstraint("expires_at > created_at", name="ck_automation_permission_expiry"),
    )


class AutomationPermissionReceiptModel(Base):
    """The answer and its audit identity are committed together."""

    __tablename__ = "agistack_automation_permission_receipts"

    intent_id: Mapped[str] = mapped_column(
        String, ForeignKey("agistack_automation_permission_intents.id"), primary_key=True
    )
    responder_user_id: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    answer: Mapped[str] = mapped_column(String(20), nullable=False)
    authority_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("responder_user_id", "idempotency_key", name="uq_permission_answer_key"),
        CheckConstraint("answer IN ('allow_once', 'deny')", name="ck_permission_answer"),
        CheckConstraint("authority_revision > 0", name="ck_permission_answer_revision"),
    )


class AutomationPermissionConsumptionModel(Base):
    """One-use ledger structure, initially unavailable for dispatch."""

    __tablename__ = "agistack_automation_permission_consumptions"

    intent_id: Mapped[str] = mapped_column(
        String, ForeignKey("agistack_automation_permission_receipts.intent_id"), primary_key=True
    )
    invocation_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    max_uses: Mapped[int] = mapped_column(BigInteger, nullable=False)
    use_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("max_uses = 1 AND use_count BETWEEN 0 AND 1", name="ck_permission_one_use"),
        CheckConstraint(
            "status IN ('awaiting_dispatch_binding', 'reserved', 'dispatched', "
            "'completed', 'outcome_unknown', 'revoked')",
            name="ck_permission_consumption_status",
        ),
    )
