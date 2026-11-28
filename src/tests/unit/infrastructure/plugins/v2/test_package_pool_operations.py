from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from pydantic import ValidationError

from plugins.business.environments.backend import pool_operations as operations

pytestmark = pytest.mark.unit


@pytest.fixture
def context():
    app = FastAPI()

    @app.api_route("/api/v1/admin/pool/{resource:path}", methods=["GET", "POST", "DELETE"])
    async def pool(resource: str, request: Request):
        return {"path": resource, "query": dict(request.query_params), "method": request.method}

    return SimpleNamespace(
        scope=SimpleNamespace(tenant_id="current"),
        request=SimpleNamespace(app=app, headers={}),
        user=SimpleNamespace(id="user"),
    )


async def test_pool_controls_preserve_method_and_tenant(context):
    result = await operations.control(
        context, {"instance_key": "valid:key", "action": "terminate"}, None
    )
    assert result == {
        "path": "instances/valid:key",
        "method": "DELETE",
        "query": {"scope": "tenant", "tenant_id": "current", "graceful": "true"},
    }


async def test_pool_rejects_supplied_authority(context):
    with pytest.raises(ValidationError):
        await operations.read(context, {"resource": "status", "tenant_id": "other"}, None)


@pytest.mark.parametrize("key", ["../status", "%2Fmetrics", "a?scope=global", "a#fragment"])
async def test_pool_rejects_non_segment_instance_keys(context, key):
    with pytest.raises(ValidationError):
        await operations.control(context, {"instance_key": key, "action": "pause"}, None)
