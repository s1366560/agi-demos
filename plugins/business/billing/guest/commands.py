"""Billing command shaping. Quota checks stay on the host; the account view is assembled here."""

from __future__ import annotations

from typing import Any

from plugins.business.guest_runtime.binding import current


async def read_account(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.billing.backend.account_operations import _AccountView

    view = _AccountView.model_validate(payload)
    parts = await current().data("billing.account.parts", {"full_history": view.full_history})
    if not view.full_history:
        return dict(parts["account"])
    return {**parts["account"], **parts["invoices"], "membership_role": parts["role"]}


async def change_plan(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.billing.backend.account_operations import _Plan

    plan = _Plan.model_validate(payload)
    changed = await current().data("billing.plan.apply", plan.model_dump())
    return {key: value for key, value in changed.items() if key != "credentials_encrypted"}


OPERATIONS = {
    "app.billing.account.read": read_account,
    "app.billing.plan.write": change_plan,
}
