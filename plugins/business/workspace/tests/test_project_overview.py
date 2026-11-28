from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request

from plugins.business.workspace.backend.project_overview import read_overview

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("installed", "changed"), [(False, False), (True, False), (True, True)])
async def test_overview_uses_actor_project_and_only_enabled_knowledge(installed, changed):
    app = FastAPI()
    commands = []

    @app.get("/api/v1/projects/p")
    def project(tenant_id: str):
        assert tenant_id == "t"
        return {"id": "p", "tenant_id": "t", "name": "Project"}

    @app.get("/api/v1/projects/p/stats")
    def stats():
        return dict.fromkeys(
            ("memory_count", "storage_used", "storage_limit", "active_nodes", "collaborators"), 7
        )

    @app.get("/api/v1/platform-plugins/v2/optional-business/")
    def marketplace(tenant_id: str, project_id: str):
        assert (tenant_id, project_id) == ("t", "p")
        return {
            "items": [
                {
                    "plugin_id": "memstack-knowledge",
                    "status": "enabled" if installed else "disabled",
                    "actual_digest": "pinned",
                }
            ]
        }

    @app.post("/api/v1/platform-plugins/v2/optional-business/memstack-knowledge/commands")
    async def memory(req: Request):
        assert "authorization" not in {key.lower() for key in req.headers}
        commands.append(await req.json())
        if changed:
            raise HTTPException(409, "Release changed")
        return {"memories": [{"id": "m", "project_id": "p", "title": "Recent"}], "total": 1}

    ctx = SimpleNamespace(
        request=SimpleNamespace(app=app, headers={"Authorization": "Bearer fixture"}),
        user=SimpleNamespace(id="user"),
        scope=SimpleNamespace(tenant_id="t", project_id="p"),
    )
    with pytest.raises(HTTPException, match="does not accept parameters"):
        await read_overview(ctx, {"project_id": "foreign"}, None)
    response = await read_overview(ctx, {}, None)
    assert response["project"]["name"] == "Project" and response["stats"]["memory_count"] == 7
    if installed:
        assert commands == [
            {
                "tenant_id": "t",
                "project_id": "p",
                "expected_digest": "pinned",
                "command_id": "list-memories",
                "payload": {"page": 1, "page_size": 5},
            }
        ]
        if changed:
            assert response["recent"] is None
        else:
            assert response["recent"]["memories"][0]["id"] == "m"
    else:
        assert response["recent"] is None and not commands
