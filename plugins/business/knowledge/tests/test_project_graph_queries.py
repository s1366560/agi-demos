from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from plugins.business.knowledge.backend.graph_queries import read_graph, read_subgraph

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("subgraph", [False, True])
async def test_uses_the_installed_project_and_existing_graph_authorization(subgraph):
    app = FastAPI()
    seen = []

    @app.api_route("/api/v1/graph/memory/graph{suffix:path}", methods=["GET", "POST"])
    async def graph(request: Request, suffix: str):
        params = await request.json() if subgraph else dict(request.query_params)
        seen.append((request.method, suffix, params))
        return {"elements": {"nodes": [], "edges": []}}

    ctx = SimpleNamespace(
        scope=SimpleNamespace(tenant_id="tenant", project_id="project"),
        request=SimpleNamespace(app=app, headers={}),
        user=SimpleNamespace(id="user"),
    )
    operation = read_subgraph if subgraph else read_graph
    arguments = {"node_uuids": ["episode"], "limit": 1} if subgraph else {"limit": 500}
    assert await operation(ctx, arguments, None) == {"elements": {"nodes": [], "edges": []}}
    method, suffix, sent = seen.pop()
    assert (method, suffix) == (("POST", "/subgraph") if subgraph else ("GET", ""))
    assert (sent["tenant_id"], sent["project_id"]) == ("tenant", "project")
    assert int(sent["limit"]) == arguments["limit"]
    with pytest.raises(ValidationError):
        await operation(ctx, {**arguments, "project_id": "other"}, None)
    ctx.scope.project_id = None
    with pytest.raises(HTTPException) as denied:
        await operation(ctx, arguments, None)
    assert denied.value.status_code == 403
    assert seen == []
