from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from plugins.business.automation.backend import playbook_operation as ops
from src.infrastructure.adapters.primary.web.routers.reflection import VerdictsResponse, VerdictView

pytestmark = pytest.mark.unit


async def test_project_verdicts_hide_proposed_payload_and_bind_project_scope(monkeypatch):
    ctx = SimpleNamespace(
        request=object(),
        user=object(),
        db=object(),
        scope=SimpleNamespace(tenant_id="t", project_id="p"),
    )
    auth = object()

    @asynccontextmanager
    async def authority(request, user, db, scope):
        assert (request, user, db, scope.tenant_id, scope.project_id) == (
            ctx.request,
            ctx.user,
            ctx.db,
            "t",
            "p",
        )
        yield auth

    item = VerdictView(
        id="v",
        project_id="p",
        action="noop",
        playbook_id=None,
        rationale="reviewed",
        proposed_payload={"private": True},
        created_at="now",
    )
    read = AsyncMock(return_value=VerdictsResponse(items=[item]))
    monkeypatch.setattr(ops, "reflection_authority", authority)
    monkeypatch.setattr(ops, "list_reflection_verdicts", read)
    with pytest.raises(HTTPException):
        await ops.read_verdicts(ctx, {"project_id": "foreign"}, None)
    read.assert_not_called()
    assert await ops.read_verdicts(ctx, {}, None) == {
        "items": [item.model_dump(exclude={"proposed_payload"})]
    }
    read.assert_awaited_once_with("p", 200, ctx.user, auth)
