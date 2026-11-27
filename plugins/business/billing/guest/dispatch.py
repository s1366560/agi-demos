"""Map admitted command names onto host capabilities."""

from __future__ import annotations

from plugins.business.guest_runtime.binding import bind_operation

OPERATIONS = {
    name: bind_operation(name)
    for name in (
        "app.billing.account.read",
        "app.billing.plan.write",
    )
}

TOOLS = {
    "billing.tenant-account": "app.billing.account.read",
    "billing.change-plan": "app.billing.plan.write",
    "billing.billing-details": "app.billing.account.read",
}
