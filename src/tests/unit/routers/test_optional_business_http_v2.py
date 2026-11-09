"""Production route table plus scope checks for optional-business HTTP."""

from __future__ import annotations

import base64

import pytest
import wasmtime
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from memstack_plugin_sdk.contract import parse_contribution

from src.infrastructure.adapters.primary.web.dependencies import create_api_key
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2.builtin_platform_plugins_http_routes import (
    platform_plugins_route_definitions_v2,
)
from src.infrastructure.plugins.v2.http_routes import install_route_definitions_v2
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    SignedOptionalBusinessRuntimeV2,
)
from src.tests.unit.infrastructure.plugins.v2.test_signed_optional_business_v2 import (
    PING_OUTPUT,
    PING_SCHEMA,
    SAMPLE,
)

pytestmark = pytest.mark.unit


def _wasm() -> str:
    return base64.b64encode(wasmtime.wat2wasm((SAMPLE / "tool.wat").read_text())).decode()


def _body() -> dict[str, object]:
    ui = (SAMPLE / "ui.json").read_text()
    return {
        "tenant_id": "t",
        "project_id": "p",
        "plugin_id": "sample.notes",
        "version": "1.0.0",
        "digest": "sha256:1.0.0",
        "wasm_base64": _wasm(),
        "contribution": {
            "schema": "memstack.plugin.contributions/1",
            "tools": [
                {
                    "name": "note.ping",
                    "abi": "invoke",
                    "input_schema": PING_SCHEMA,
                    "output_schema": PING_OUTPUT,
                    "permissions": ["tools.execute"],
                }
            ],
            "commands": [
                {
                    "id": "ping",
                    "tool": "note.ping",
                    "payload": {"op": "ping"},
                    "permissions": ["tools.execute"],
                }
            ],
            "ui": [
                {
                    "slot": "tool_result_renderer",
                    "path": "ui.json",
                    "digest": "sha256:" + "ab" * 32,
                    "targets": ["web"],
                    "permissions": ["ui.slot"],
                }
            ],
        },
        "ui_files": {"ui.json": base64.b64encode(ui.encode()).decode()},
        "approved_permissions": ["tools.execute", "ui.slot"],
    }


@pytest.fixture
async def http(db_session):
    app = FastAPI()
    install_route_definitions_v2(
        app,
        tuple(
            route
            for route in platform_plugins_route_definitions_v2()
            if "/optional-business/" in route.path
        ),
    )
    app.state.optional_business_runtime_v2 = SignedOptionalBusinessRuntimeV2()
    users = [
        User(id=role, email=f"{role}@example.test", hashed_password="unused", is_active=True)
        for role in ("owner", "viewer")
    ]
    db_session.add_all(users)
    await db_session.flush()
    db_session.add(Tenant(id="t", name="Tenant", slug="optional", owner_id="owner"))
    await db_session.flush()
    db_session.add(Project(id="p", tenant_id="t", name="Project", owner_id="owner"))
    await db_session.flush()
    keys = {}
    for user in users:
        keys[user.id], _ = await create_api_key(db_session, user.id, "test", [])
        db_session.add(UserTenant(id=f"ut-{user.id}", user_id=user.id, tenant_id="t", role="member"))
        db_session.add(
            UserProject(
                id=f"up-{user.id}",
                user_id=user.id,
                project_id="p",
                role="owner" if user.id == "owner" else "viewer",
            )
        )
    await db_session.commit()

    async def database():
        return db_session

    app.dependency_overrides[get_db] = database

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, keys


async def test_routes_are_on_the_production_table() -> None:
    names = {route.name for route in platform_plugins_route_definitions_v2()}
    assert "install_optional_business_v2" in names
    assert "rollback_optional_business_v2" in names
    assert "purge_optional_business_v2" in names


async def test_member_cannot_write_and_owner_can_install_enable_and_invoke(http) -> None:
    client, keys = http
    body = _body()
    # The sample UI digest in this request is intentionally wrong; install records it.
    # Enable still runs the tool. UI mount is covered by the runtime test.
    parse_contribution(body["contribution"])  # type: ignore[arg-type]
    denied = await client.post(
        "/api/v1/platform-plugins/v2/optional-business/install",
        json=body,
        headers={"Authorization": f"Bearer {keys['viewer']}"},
    )
    assert denied.status_code == 403
    installed = await client.post(
        "/api/v1/platform-plugins/v2/optional-business/install",
        json=body,
        headers={"Authorization": f"Bearer {keys['owner']}"},
    )
    assert installed.status_code == 200
    assert installed.json()["status"] == "recorded"
    scope = {"tenant_id": "t", "project_id": "p"}
    enabled = await client.post(
        "/api/v1/platform-plugins/v2/optional-business/sample.notes/enable",
        json=scope,
        headers={"Authorization": f"Bearer {keys['owner']}"},
    )
    assert enabled.status_code == 200
    invoked = await client.post(
        "/api/v1/platform-plugins/v2/optional-business/sample.notes/invoke",
        json={**scope, "tool_name": "note.ping", "payload": {"op": "ping"}},
        headers={"Authorization": f"Bearer {keys['owner']}"},
    )
    assert invoked.status_code == 200
    assert invoked.json()["op"] == "ping"
    commanded = await client.post(
        "/api/v1/platform-plugins/v2/optional-business/sample.notes/commands",
        json={**scope, "command_id": "ping"},
        headers={"Authorization": f"Bearer {keys['owner']}"},
    )
    assert commanded.status_code == 200
    rolled = await client.post(
        "/api/v1/platform-plugins/v2/optional-business/sample.notes/rollback",
        json=scope,
        headers={"Authorization": f"Bearer {keys['owner']}"},
    )
    assert rolled.status_code == 409


async def test_failed_update_keeps_the_running_generation_and_rollback_restores_it(http) -> None:
    client, keys = http
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    scope = {"tenant_id": "t", "project_id": "p"}
    first = _body()
    installed = await client.post(
        "/api/v1/platform-plugins/v2/optional-business/install",
        json=first,
        headers=headers,
    )
    assert installed.status_code == 200
    enabled = await client.post(
        "/api/v1/platform-plugins/v2/optional-business/sample.notes/enable",
        json=scope,
        headers=headers,
    )
    assert enabled.status_code == 200
    broken = _body()
    broken["version"] = "2.0.0"
    broken["digest"] = "sha256:2.0.0"
    broken["wasm_base64"] = base64.b64encode(b"not-wasm").decode()
    assert (
        await client.post(
            "/api/v1/platform-plugins/v2/optional-business/install",
            json=broken,
            headers=headers,
        )
    ).status_code == 200
    failed = await client.post(
        "/api/v1/platform-plugins/v2/optional-business/sample.notes/enable",
        json=scope,
        headers=headers,
    )
    assert failed.status_code == 409
    still = await client.post(
        "/api/v1/platform-plugins/v2/optional-business/sample.notes/invoke",
        json={**scope, "tool_name": "note.ping", "payload": {"op": "ping"}},
        headers=headers,
    )
    assert still.status_code == 200
    assert still.json()["op"] == "ping"
    nxt = _body()
    nxt["version"] = "1.1.0"
    nxt["digest"] = "sha256:1.1.0"
    assert (
        await client.post(
            "/api/v1/platform-plugins/v2/optional-business/install",
            json=nxt,
            headers=headers,
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/platform-plugins/v2/optional-business/sample.notes/enable",
            json=scope,
            headers=headers,
        )
    ).status_code == 200
    current = await client.get(
        "/api/v1/platform-plugins/v2/optional-business/sample.notes",
        params=scope,
        headers=headers,
    )
    assert current.json()["actual_digest"] == "sha256:1.1.0"
    restored = await client.post(
        "/api/v1/platform-plugins/v2/optional-business/sample.notes/rollback",
        json=scope,
        headers=headers,
    )
    assert restored.status_code == 200
    after = await client.get(
        "/api/v1/platform-plugins/v2/optional-business/sample.notes",
        params=scope,
        headers=headers,
    )
    assert after.json()["actual_digest"] == "sha256:1.0.0"
    removed = await client.post(
        "/api/v1/platform-plugins/v2/optional-business/sample.notes/uninstall",
        json=scope,
        headers=headers,
    )
    assert removed.status_code == 200
    assert removed.json()["retention"] == "retained"
