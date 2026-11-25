from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from plugins.business.knowledge.backend.project_search import search

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "mode", ["advanced", "faceted", "community", "temporal", "graph-traversal"]
)
async def test_search_uses_the_signed_project_and_forwards_original_parameters(mode):
    app = FastAPI()
    received = []

    @app.post("/api/v1/search-enhanced/{operation}")
    async def endpoint(operation: str, request: Request):
        received.append((operation, await request.json()))
        return {"results": [], "total": 0}

    ctx = SimpleNamespace(
        scope=SimpleNamespace(tenant_id="t", project_id="p"),
        request=SimpleNamespace(app=app, headers={}),
    )
    payload = {"mode": mode, "parameters": {"query": "sprint"}}
    assert await search(ctx, payload, None) == {"results": [], "total": 0}
    assert received == [(mode, {"query": "sprint", "tenant_id": "t", "project_id": "p"})]
    with pytest.raises(HTTPException) as denied:
        await search(ctx, {**payload, "parameters": {"project_id": "other"}}, None)
    assert denied.value.status_code == 403
    with pytest.raises(ValidationError):
        await search(ctx, {**payload, "mode": "../other"}, None)
    assert len(received) == 1
