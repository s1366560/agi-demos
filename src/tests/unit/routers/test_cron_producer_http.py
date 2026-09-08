"""Only a platform superuser can resolve local producer controls."""

from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from src.infrastructure.adapters.primary.web import cron_producer_authority_v2 as authority
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.cron_producer import router

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/v1/admin/cron-producer", "GET"),
        ("/api/v1/admin/cron-producer/close", "POST"),
    ],
)
@pytest.mark.parametrize("authenticated", [False, True])
async def test_authentication_and_superuser_check_precede_runtime_access(
    monkeypatch, path, method, authenticated
):
    app = FastAPI()
    app.include_router(router)
    resolve = Mock(side_effect=AssertionError("unauthorized request resolved scheduler service"))
    monkeypatch.setattr(authority, "current_generation_v2", resolve)
    if authenticated:

        async def ordinary_user():
            return SimpleNamespace(id="ordinary", is_superuser=False)

        app.dependency_overrides[get_current_user] = ordinary_user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(
            method,
            path,
            json={
                "deployment_id": "deployment-1",
                "source_generation": "python-old",
                "producer_id": "python-api-1",
                "expected_revision": 1,
                "schedule_ids": ["job"],
            },
        )
    assert response.status_code == (403 if authenticated else 401)
    resolve.assert_not_called()


@pytest.mark.parametrize(
    "patch",
    [
        {"expected_revision": True},
        {"schedule_ids": ["job", "job"]},
        {"schedule_ids": [""]},
        {"verified": True},
        {"force": True},
    ],
)
async def test_invalid_close_envelope_cannot_call_adapter(patch):
    from unittest.mock import AsyncMock

    app = FastAPI()
    app.include_router(router)
    control = SimpleNamespace(close_prepared=AsyncMock())

    async def authorized():
        return SimpleNamespace(control=control)

    app.dependency_overrides[authority.cron_producer_authority_dependency_v2] = authorized
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/admin/cron-producer/close",
            json={
                "deployment_id": "deployment-1",
                "source_generation": "python-old",
                "producer_id": "python-api-1",
                "expected_revision": 1,
                "schedule_ids": ["job"],
            }
            | patch,
        )
    assert response.status_code == 422
    control.close_prepared.assert_not_awaited()
