"""Map admitted command names onto guest shapers."""

from __future__ import annotations

from plugins.business.billing.guest.commands import OPERATIONS

__all__ = ["OPERATIONS", "TOOLS"]

TOOLS = {
    "billing.tenant-account": "app.billing.account.read",
    "billing.change-plan": "app.billing.plan.write",
    "billing.billing-details": "app.billing.account.read",
}
