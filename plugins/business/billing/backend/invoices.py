"""Invoice records owned by the billing package."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.adapters.secondary.persistence.models import Base


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_billing_invoice_tenant_created", "tenant_id", "created_at", "id"),
        {"info": {"package_migrations": "billing"}},
    )

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
