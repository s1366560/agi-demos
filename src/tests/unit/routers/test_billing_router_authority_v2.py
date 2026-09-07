"""Unit coverage for Billing handlers' V2 authority transaction boundary."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.billing_application_authority_v2 import (
    BillingApplicationAuthorityV2,
)
from src.infrastructure.adapters.primary.web.routers import billing as billing_router
from src.infrastructure.plugins.v2.billing_services import BillingInvalidPlanV2

pytestmark = pytest.mark.unit


class _BillingService:
    async def get_billing_info(self, *, user_id: str, tenant_id: str) -> dict[str, Any]:
        return {"tenant": {"id": tenant_id, "user_id": user_id}, "usage": {}, "invoices": []}

    async def list_invoices(self, *, user_id: str, tenant_id: str) -> dict[str, Any]:
        return {"invoices": [{"tenant_id": tenant_id, "user_id": user_id}]}

    async def upgrade_plan(
        self,
        *,
        user_id: str,
        tenant_id: str,
        plan_data: dict[str, Any],
    ) -> dict[str, Any]:
        return {"id": tenant_id, "plan": plan_data["plan"], "user_id": user_id}


def _authority(service: object, *, db: object) -> BillingApplicationAuthorityV2:
    return cast(
        BillingApplicationAuthorityV2,
        SimpleNamespace(
            operation=object(),
            db=db,
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            services=SimpleNamespace(billing=service),
        ),
    )


async def test_billing_read_handlers_do_not_commit_authority_session() -> None:
    db = SimpleNamespace(commit=AsyncMock())
    authority = _authority(_BillingService(), db=db)

    billing = await billing_router.get_billing_info("tenant-1", authority)
    invoices = await billing_router.list_invoices("tenant-1", authority)

    assert billing["tenant"]["user_id"] == "user-1"
    assert invoices["invoices"][0]["tenant_id"] == "tenant-1"
    db.commit.assert_not_awaited()


async def test_billing_upgrade_commits_authority_session_once() -> None:
    db = SimpleNamespace(commit=AsyncMock())
    authority = _authority(_BillingService(), db=db)

    response = await billing_router.upgrade_plan(
        "tenant-1",
        {"plan": "enterprise"},
        authority,
    )

    assert response["tenant"]["plan"] == "enterprise"
    db.commit.assert_awaited_once_with()


async def test_billing_upgrade_failure_does_not_commit_authority_session() -> None:
    class InvalidBillingService(_BillingService):
        async def upgrade_plan(
            self,
            *,
            user_id: str,
            tenant_id: str,
            plan_data: dict[str, Any],
        ) -> dict[str, Any]:
            raise BillingInvalidPlanV2

    db = SimpleNamespace(commit=AsyncMock())
    authority = _authority(InvalidBillingService(), db=db)

    with pytest.raises(HTTPException) as error:
        await billing_router.upgrade_plan(
            "tenant-1",
            {"plan": "gold"},
            authority,
        )

    assert error.value.status_code == 400
    db.commit.assert_not_awaited()
