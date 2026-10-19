"""HTTP management uses persisted scope membership and the real SQL revision fence."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.infrastructure.adapters.primary.web.dependencies import create_api_key
from src.infrastructure.adapters.primary.web.routers import platform_plugins
from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
    ScopedProfileRuntimeV2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.tests.unit.application.services.test_plugin_instance_service_v2 import (
    manager,  # noqa: F401
)

pytestmark = pytest.mark.unit
PATH = "/api/v1/platform-plugins/v2/instances"


@pytest.fixture
async def instances_http(db_session, manager):  # noqa: F811
    service, key, _ = manager
    app = FastAPI()
    app.include_router(platform_plugins.router)
    runtime = MagicMock(spec=ScopedProfileRuntimeV2)
    runtime.instances.return_value = service
    app.state.scoped_profile_runtime_v2 = runtime

    async def database():
        return db_session

    app.dependency_overrides[get_db] = database
    users = [
        User(
            id=role, email=f"instance-{role}@example.test", hashed_password="unused", is_active=True
        )
        for role in ("owner", "viewer", "outsider")
    ]
    db_session.add_all(users)
    await db_session.flush()
    db_session.add(Tenant(id="t", name="Tenant", slug="instances", owner_id="owner"))
    await db_session.flush()
    db_session.add(Project(id="p", tenant_id="t", name="Project", owner_id="owner"))
    await db_session.flush()
    keys = {}
    for user in users:
        keys[user.id], _ = await create_api_key(db_session, user.id, "test", [])
        if user.id != "outsider":
            db_session.add(
                UserTenant(id=f"tenant-{user.id}", user_id=user.id, tenant_id="t", role="member")
            )
            db_session.add(
                UserProject(id=f"project-{user.id}", user_id=user.id, project_id="p", role=user.id)
            )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, keys, key, runtime


async def test_authorized_save_stale_conflict_and_readonly_member(instances_http):
    client, keys, entry_id, runtime = instances_http
    params = {"tenant_id": "t", "project_id": "p"}
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    listed = await client.get(PATH, params=params, headers=headers)
    assert listed.status_code == 200
    assert listed.headers["Cache-Control"] == "private, no-store"
    assert any(row["editable"] for row in listed.json()["instances"])
    payload = {
        **params,
        "expected_revision": 1,
        "changes": [{"entry_id": entry_id, "enabled": False}],
    }
    saved = await client.post(f"{PATH}/apply", json=payload, headers=headers)
    assert saved.status_code == 200 and saved.json()["revision"] == 2
    stale = await client.post(f"{PATH}/apply", json=payload, headers=headers)
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "instance_revision_conflict"
    viewer = {"Authorization": f"Bearer {keys['viewer']}"}
    result = await client.get(PATH, params=params, headers=viewer)
    assert result.status_code == 200
    assert all(not row["editable"] for row in result.json()["instances"])
    denied = await client.post(f"{PATH}/apply", json=payload, headers=viewer)
    assert denied.status_code == 403
    assert runtime.instances.call_args.args[0].project_id == "p"


async def test_unauthorized_scope_never_resolves_instance_service(instances_http):
    client, keys, _, runtime = instances_http
    response = await client.get(
        PATH,
        params={"tenant_id": "t", "project_id": "p"},
        headers={"Authorization": f"Bearer {keys['outsider']}"},
    )
    assert response.status_code == 403
    runtime.instances.assert_not_called()
