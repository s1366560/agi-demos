"""Canonical invoice fields shared by the tenant service and independent invoice worker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, kw_only=True)
class BillingInvoiceRecordV2:
    """Persistence-neutral invoice fields used by billing responses."""

    id: str
    amount: int
    currency: str
    status: str
    period_start: datetime
    period_end: datetime
    created_at: datetime
    paid_at: datetime | None
    invoice_url: str | None


def invoice_payload(invoice: BillingInvoiceRecordV2) -> dict[str, Any]:
    return {
        "id": invoice.id,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "status": invoice.status,
        "period_start": invoice.period_start.isoformat(),
        "period_end": invoice.period_end.isoformat(),
        "created_at": invoice.created_at.isoformat(),
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
        "invoice_url": invoice.invoice_url,
    }
