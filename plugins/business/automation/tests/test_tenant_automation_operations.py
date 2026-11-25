from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from plugins.business.automation.backend import tenant_automation_operations as ops
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError


@pytest.mark.unit
@pytest.mark.parametrize("change", [ops.update_hook, ops.delete_hook])
async def test_webhook_admin_cannot_change_another_selected_tenant(monkeypatch, change):
    service = SimpleNamespace(
        get_webhook=AsyncMock(return_value=SimpleNamespace(tenant_id="other")),
        update_webhook=AsyncMock(),
        delete_webhook=AsyncMock(),
    )
    ctx = SimpleNamespace(
        user=object(), request=object(), db=AsyncMock(), scope=SimpleNamespace(tenant_id="t")
    )

    @asynccontextmanager
    async def authority(**params):
        assert params["tenant_id"] == "t"
        yield SimpleNamespace(services=SimpleNamespace(webhooks=service))

    access = AsyncMock()
    monkeypatch.setattr(ops, "require_tenant_access", access)
    monkeypatch.setattr(ops, "tenant_webhook_application_authority_context_v2", authority)
    payload = {"id": "x"}
    if change == ops.update_hook:
        payload["data"] = {
            "name": "example",
            "events": [],
            "url": "https://example.org",
            "is_active": False,
        }
    with pytest.raises(ValidationError):
        await change(ctx, {**payload, "tenant_id": "other"}, None)
    with pytest.raises(OptionalBusinessError):
        await change(ctx, payload, None)
    access.assert_awaited_once_with(ctx.db, ctx.user, "t", require_admin=True)
    service.update_webhook.assert_not_called()
    service.delete_webhook.assert_not_called()
    ctx.db.commit.assert_not_called()
