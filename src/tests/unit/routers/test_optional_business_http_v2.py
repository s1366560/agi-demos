"""Production route table plus scope checks for optional-business HTTP."""

from __future__ import annotations

import base64
import hashlib
import json
from io import BytesIO
from zipfile import ZipFile

import pytest
import wasmtime
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from memstack_plugin_sdk.pack import build

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
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                    "permissions": ["tools.execute"],
                }
            ],
            "ui": [
                {
                    "slot": "tool_result_renderer",
                    "path": "ui.json",
                    "digest": "sha256:" + hashlib.sha256(ui.encode()).hexdigest(),
                    "targets": ["web"],
                    "permissions": ["ui.slot"],
                }
            ],
        },
        "ui_files": {"ui.json": base64.b64encode(ui.encode()).decode()},
        "approved_permissions": ["tools.execute", "ui.slot"],
    }


@pytest.fixture
def publisher(tmp_path):
    signer = Ed25519PrivateKey.generate()
    public = (
        signer.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )

    def release(
        version="1.0.0",
        *,
        broken=False,
        result="ping",
        storage_limit=None,
        storage_schema_version=1,
        input_schema=None,
        skill_instructions=None,
        subagents=None,
        compatibility=None,
        pages=None,
        application_command=None,
        plugin_id="sample.notes",
    ):
        source = _body()
        doc = source["contribution"]
        bindings = (
            {"chat": application_command}
            if isinstance(application_command, str)
            else application_command
        )
        for command, capability in (bindings or {}).items():
            doc["commands"].append(
                {
                    "id": command,
                    "host_operation": capability,
                    "payload": {},
                    "accepts_input": True,
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                    "permissions": [capability],
                }
            )
            source["approved_permissions"].append(capability)
        if pages:
            doc["pages"] = pages
        doc["tools"][0]["description"] = f"Return the signed {result} response."
        doc["tools"][0]["output_schema"] = {
            **PING_OUTPUT,
            "properties": {"ok": {"const": True}, "op": {"const": result}},
        }
        if skill_instructions:
            doc["skills"] = [
                {
                    "id": "inspect.notes",
                    "instructions": skill_instructions,
                    "permissions": ["skills.register"],
                }
            ]
            source["approved_permissions"].append("skills.register")
        if input_schema:
            doc["tools"][0]["input_schema"] = input_schema
        if subagents:
            doc["subagents"] = subagents
            source["approved_permissions"].append("subagents.register")
        if storage_limit is not None:
            permissions = ["storage.read", "storage.write"]
            doc["storage"] = {"schema_version": storage_schema_version, "permissions": permissions}
            source["approved_permissions"].extend(permissions)
        (tmp_path / "ui.json").write_bytes((SAMPLE / "ui.json").read_bytes())
        (tmp_path / "contributions.json").write_text(json.dumps(doc))
        wat = "(module)" if broken else (SAMPLE / "tool.wat").read_text().replace("ping", result)
        (tmp_path / "guest.wasm").write_bytes(wasmtime.wat2wasm(wat))
        config = tmp_path / "package.json"
        config.write_text(
            json.dumps(
                {
                    "plugin_id": plugin_id,
                    "version": version,
                    **({"compatibility": compatibility} if compatibility is not None else {}),
                    "target": "python",
                    "provenance": "repo://qa/independent-publisher",
                    "tool_name": "ping",
                    "wasm": "guest.wasm",
                    "quotas": {"max_storage_bytes": storage_limit} if storage_limit else {},
                    "contribution": "contributions.json",
                }
            )
        )
        raw = build(config, signer)
        with ZipFile(BytesIO(raw)) as archive:
            digest = json.loads(archive.read("bundle.json"))["digest"]
        return {
            "tenant_id": "t",
            "project_id": "p",
            "approved_permissions": source["approved_permissions"],
            "archive_base64": base64.b64encode(raw).decode(),
        }, digest

    return public, release


@pytest.fixture(params=["full", "package-kernel"])
async def http(db_session, publisher, request):
    if request.param == "package-kernel":
        from src.host.transport.package_kernel import create_app

        app = create_app()
    else:
        from src.infrastructure.adapters.primary.web.routers import plugin_marketplace

        app = FastAPI()
        app.include_router(plugin_marketplace.router)
        install_route_definitions_v2(
            app,
            tuple(
                route
                for route in platform_plugins_route_definitions_v2()
                if "/optional-business/" in route.path
            ),
        )
    app.state.plugin_marketplace_trusted_public_keys_v2 = (publisher[0],)
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
        db_session.add(
            UserTenant(id=f"ut-{user.id}", user_id=user.id, tenant_id="t", role="member")
        )
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


async def test_member_cannot_write_and_owner_can_install_enable_and_invoke(http, publisher) -> None:
    client, keys = http
    body, _ = publisher[1]()
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


async def test_failed_update_keeps_the_running_generation_and_rollback_restores_it(
    http, publisher
) -> None:
    client, keys = http
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    scope = {"tenant_id": "t", "project_id": "p"}
    first, first_digest = publisher[1]()
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
    broken, _ = publisher[1]("2.0.0", broken=True)
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
    nxt, next_digest = publisher[1]("1.1.0", result="pong")
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
    assert current.json()["actual_digest"] == next_digest
    command_path = "/api/v1/platform-plugins/v2/optional-business/sample.notes/commands"
    assert (
        await client.post(command_path, json={**scope, "command_id": "ping"}, headers=headers)
    ).json()["op"] == "pong"
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
    assert after.json()["actual_digest"] == first_digest
    assert (
        await client.post(command_path, json={**scope, "command_id": "ping"}, headers=headers)
    ).json()["op"] == "ping"
    removed = await client.post(
        "/api/v1/platform-plugins/v2/optional-business/sample.notes/uninstall",
        json=scope,
        headers=headers,
    )
    assert removed.status_code == 200
    assert removed.json()["retention"] == "retained"


async def test_project_import_and_marketplace_share_one_signed_release(
    http, publisher, db_session, tmp_path
):
    from sqlalchemy import func, select

    from src.infrastructure.adapters.secondary.persistence.project_plugin_installation import (
        ProjectPluginInstallation,
        ProjectPluginRelease,
    )
    from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
    from src.tests.unit.application.services.test_plugin_marketplace_install_service import (
        _request,
    )

    client, keys = http
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    body, digest = publisher[1]()
    scope = {"tenant_id": "t", "project_id": "p"}
    base = "/api/v1/platform-plugins/v2/optional-business"
    preview = await client.post(
        base + "/inspect", json={**scope, "archive_base64": body["archive_base64"]}, headers=headers
    )
    assert preview.json()["digest"] == digest
    assert (
        await client.post(
            base + "/install", json={**body, "approved_permissions": []}, headers=headers
        )
    ).status_code == 400
    assert (await client.post(base + "/install", json=body, headers=headers)).status_code == 200
    raw = base64.b64decode(body["archive_base64"])
    signed = parse_bundle_archive_v2(
        raw,
        source="test",
        trusted_public_keys=(publisher[0],),
        approved_permissions=frozenset(body["approved_permissions"]),
        require_signature=True,
    )
    request = _request(signed.manifest, raw, publisher[0]).model_copy(
        update={**scope, "approved_permissions": frozenset(body["approved_permissions"])}
    )
    with ZipFile(BytesIO(raw)) as package:
        request.manifest = json.loads(package.read("bundle.json"))
    app = client._transport.app
    from src.tests.unit.routers.project_registry_fixture import serve_archive

    with serve_archive(raw, tmp_path) as artifact:
        request.artifact = artifact
        path = "/api/v1/plugin-marketplace/packages/sample.notes/install"
        denied_role = await client.post(
            path,
            json=request.model_dump(mode="json"),
            headers={"Authorization": f"Bearer {keys['viewer']}"},
        )
        assert denied_role.status_code == 403
        denied_registry = await client.post(
            path, json=request.model_dump(mode="json"), headers=headers
        )
        assert denied_registry.json()["status"] == "quarantined"
        app.state.plugin_marketplace_allowed_registries_v2 = frozenset({artifact.registry})
        res = await client.post(path, json=request.model_dump(mode="json"), headers=headers)
    assert res.status_code == 202, res.text
    assert res.json()["status"] == "approved", res.json()
    detail = await client.get("/api/v1/plugin-marketplace/packages/sample.notes", headers=headers)
    assert detail.json()["versions"][0]["artifact_digest"] == hashlib.sha256(raw).hexdigest()
    altered, _ = publisher[1](result="pong")
    conflict = await client.post(
        base + "/inspect",
        json={**scope, "archive_base64": altered["archive_base64"]},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert "marketplace version" in conflict.json()["detail"]

    assert await db_session.scalar(select(func.count()).select_from(ProjectPluginRelease)) == 1
    assert await db_session.scalar(select(func.count()).select_from(ProjectPluginInstallation)) == 1
    view = (await client.get(base + "/sample.notes", params=scope, headers=headers)).json()
    assert view["running_version"] == view["installed_version"] == "1.0.0"
    assert view["commands"] == ["ping"]
    assert (
        await client.post(
            base + "/sample.notes/commands",
            json={**scope, "command_id": "ping", "expected_digest": "sha256:" + "0" * 64},
            headers=headers,
        )
    ).status_code == 409
    assert (
        await client.get(
            base + "/sample.notes/ui", params={**scope, "target": "web"}, headers=headers
        )
    ).json()["bytes_base64"]
    app.state.plugin_marketplace_trusted_public_keys_v2 = ()
    unavailable = (await client.get(base + "/sample.notes", params=scope, headers=headers)).json()
    assert unavailable["runtime_phase"] == "unavailable"
    assert unavailable["running_version"] is unavailable["actual_digest"] is None
    assert (
        await client.post(
            base + "/sample.notes/commands", json={**scope, "command_id": "ping"}, headers=headers
        )
    ).status_code >= 400


async def test_installation_scope_and_signature_checked_on_every_request(
    http, publisher, db_session
):
    client, keys = http
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    base = "/api/v1/platform-plugins/v2/optional-business"
    scope = {"tenant_id": "t", "project_id": "p"}
    body, _ = publisher[1]()
    assert (await client.post(base + "/install", json=body, headers=headers)).status_code == 200
    assert (
        await client.post(base + "/sample.notes/enable", json=scope, headers=headers)
    ).status_code == 200
    db_session.add(Project(id="other", tenant_id="t", name="other", owner_id="owner"))
    await db_session.flush()
    db_session.add(UserProject(id="other-owner", user_id="owner", project_id="other", role="owner"))
    await db_session.commit()
    other = {**scope, "project_id": "other"}
    assert not (await client.get(base + "/sample.notes", params=other, headers=headers)).json()[
        "package_recorded"
    ]
    assert (
        await client.post(
            base + "/sample.notes/commands", json={**other, "command_id": "ping"}, headers=headers
        )
    ).status_code == 403


async def test_signed_storage_limit_applies_to_namespace_and_allows_replacing_a_key(
    http, publisher
):
    client, keys = http
    scope = {"tenant_id": "t", "project_id": "p"}
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    base = "/api/v1/platform-plugins/v2/optional-business"
    body, _ = publisher[1](storage_limit=16)
    assert (await client.post(base + "/install", json=body, headers=headers)).status_code == 200
    assert (
        await client.post(base + "/sample.notes/enable", json=scope, headers=headers)
    ).status_code == 200
    path = base + "/sample.notes/storage/"
    for name, value, expected in [("a", "hello", 200), ("b", "other", 413), ("a", "123", 200)]:
        result = await client.put(
            path + name, json={**scope, "document": {"s": value}}, headers=headers
        )
        assert result.status_code == expected
    assert (await client.get(path + "a", params=scope, headers=headers)).json()["document"] == {
        "s": "123"
    }
    assert (await client.get(path + "b", params=scope, headers=headers)).json()["document"] is None


async def test_external_schema_reference_rejected_before_installation(http, publisher):
    client, keys = http
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    body, _ = publisher[1](input_schema={"properties": {"x": {"$ref": "https://schema.invalid/x"}}})
    base = "/api/v1/platform-plugins/v2/optional-business"
    result = await client.post(base + "/install", json=body, headers=headers)
    assert result.status_code == 400
    assert "schema references must be local" in result.json()["detail"]


async def test_official_billing_settings_page_and_action_use_same_signed_release(http):
    from plugins.business.billing.build import build_release

    client, keys = http
    signer = Ed25519PrivateKey.generate()
    client._transport.app.state.plugin_marketplace_trusted_public_keys_v2 = (
        signer.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
    )
    scope = {"tenant_id": "t", "project_id": "p"}
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    raw = build_release({"pro": 456}, version="3.1.0", signer=signer)
    archive = {**scope, "archive_base64": base64.b64encode(raw).decode()}
    base = "/api/v1/platform-plugins/v2/optional-business"
    preview = (await client.post(base + "/inspect", headers=headers, json=archive)).json()
    assert (
        await client.post(
            base + "/install",
            json={**archive, "approved_permissions": preview["permissions"]},
            headers=headers,
        )
    ).status_code == 200
    base += "/memstack-billing"
    assert (await client.post(base + "/enable", json=scope, headers=headers)).status_code == 200
    projection = (await client.get(base, params=scope, headers=headers)).json()
    assert projection["has_web_ui"] and projection["has_desktop_ui"]
    assert projection["commands"] == ["quote-pro", "tenant-account", "change-plan", "billing-details"]
    pinned = {**scope, "expected_digest": preview["digest"]}
    for target in ["web", "desktop-renderer"]:
        view = (
            await client.get(base + "/ui", params={**pinned, "target": target}, headers=headers)
        ).json()
        assert view["slot"] == "settings_page"
        assert view["actions"][0]["id"] == "quote-pro"
    assert (
        await client.post(
            base + "/commands", json={**pinned, "command_id": "quote-pro"}, headers=headers
        )
    ).json() == {"plan": "pro", "storage_limit": 456}
    forged = await client.post(
        base + "/commands",
        json={**pinned, "command_id": "quote-pro", "payload": {"plan": "free"}},
        headers=headers,
    )
    assert forged.status_code == 403


async def test_only_a_replica_able_to_run_the_active_release_is_ready(http, publisher, db_session):
    from src.host.transport.package_kernel import create_app

    client, keys = http
    scope = {"tenant_id": "t", "project_id": "p"}
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    base = "/api/v1/platform-plugins/v2/optional-business"
    other = create_app()

    async def database():
        return db_session

    other.dependency_overrides[get_db] = database
    async with AsyncClient(transport=ASGITransport(app=other), base_url="http://other") as peer:
        assert (await peer.get("/health/ready")).status_code == 200
        release, _ = publisher[1]()
        assert (await client.post(f"{base}/install", headers=headers, json=release)).is_success
        qualified = await client.post(f"{base}/sample.notes/enable", headers=headers, json=scope)
        assert qualified.is_success
        assert (await peer.get("/health/ready")).status_code == 503
        other.state.plugin_marketplace_trusted_public_keys_v2 = (publisher[0],)
        assert (await peer.get("/health/ready")).status_code == 200
        other.state.plugin_marketplace_trusted_public_keys_v2 = ()
        assert (await peer.get("/health/ready")).status_code == 503
        assert (
            await client.post(f"{base}/sample.notes/disable", headers=headers, json=scope)
        ).is_success
        assert (await peer.get("/health/ready")).status_code == 200


async def test_installation_discovery_and_execution_distinguish_project_roles(
    http, publisher, db_session
):
    from sqlalchemy import update

    from src.infrastructure.adapters.primary.web.routers import plugin_marketplace_v3

    client, keys = http
    client._transport.app.include_router(plugin_marketplace_v3.router)
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    regular = {"Authorization": f"Bearer {keys['viewer']}"}
    scope = {"tenant_id": "t", "project_id": "p"}
    base = "/api/v1/platform-plugins/v2/optional-business"
    body, digest = publisher[1]()
    assert (await client.post(base + "/install", json=body, headers=headers)).status_code == 200
    assert (
        await client.post(base + "/sample.notes/enable", json=scope, headers=headers)
    ).status_code == 200
    for path in [base + "/", "/api/v1/plugin-marketplace/v3/installations"]:
        result = await client.get(path, params=scope, headers=regular)
        assert [row["plugin_id"] for row in result.json()["items"]] == ["sample.notes"]
    action = {**scope, "command_id": "ping", "expected_digest": digest}
    assert (
        await client.post(base + "/sample.notes/commands", json=action, headers=regular)
    ).status_code == 403
    await db_session.execute(
        update(UserProject).where(UserProject.user_id == "viewer").values(role="member")
    )
    await db_session.commit()
    assert (
        await client.post(base + "/sample.notes/commands", json=action, headers=regular)
    ).json()["op"] == "ping"
    assert (
        await client.post(base + "/sample.notes/disable", json=scope, headers=regular)
    ).status_code == 403


@pytest.mark.parametrize(
    ("scan", "revoked", "reason"), [("failed", False, "security scan"), ("passed", True, "revoked")]
)
async def test_local_import_and_already_enabled_release_observe_governance(
    http, publisher, db_session, scan, revoked, reason
):
    from src.host.operations.project_package_readiness import _targets
    from src.infrastructure.adapters.secondary.persistence.models import PlatformPluginPackageModel

    client, tokens = http
    body, _ = publisher[1]()
    headers = {"Authorization": f"Bearer {tokens['owner']}"}
    base = "/api/v1/platform-plugins/v2/optional-business"
    scope = {"tenant_id": "t", "project_id": "p"}
    digest = hashlib.sha256(base64.b64decode(body["archive_base64"])).hexdigest()
    governed = PlatformPluginPackageModel(
        plugin_id="sample.notes",
        version="1.0.0",
        publisher="test",
        artifact_digest=digest,
        artifact_registry="registry.example.test",
        artifact_repository="sample/notes",
        oci_manifest_digest=digest,
        security_scan_status="unknown",
        revoked=False,
    )
    db_session.add(governed)
    await db_session.commit()
    assert (await client.post(f"{base}/install", json=body, headers=headers)).status_code == 200
    assert (
        await client.post(f"{base}/sample.notes/enable", json=scope, headers=headers)
    ).status_code == 200
    assert {target.plugin for target in await _targets(db_session)} == {"sample.notes"}
    governed.security_scan_status = scan
    governed.revoked = revoked
    await db_session.commit()
    assert await _targets(db_session) == frozenset()
    for endpoint, data in [
        ("inspect", {**scope, "archive_base64": body["archive_base64"]}),
        ("install", body),
        ("sample.notes/invoke", {**scope, "tool_name": "note.ping", "payload": {"op": "ping"}}),
    ]:
        response = await client.post(f"{base}/{endpoint}", json=data, headers=headers)
        assert response.status_code == 403
        assert reason in response.json()["detail"]


async def test_cloud_rejects_incompatible_signed_release_before_replacing_current_package(
    http, publisher
):
    client, tokens = http
    headers = {"Authorization": f"Bearer {tokens['owner']}"}
    base = "/api/v1/platform-plugins/v2/optional-business"
    scope = {"tenant_id": "t", "project_id": "p"}
    install, _ = publisher[1](compatibility={"min_inclusive": "2.0.0", "max_exclusive": "2.0.1"})
    assert (await client.post(f"{base}/install", json=install, headers=headers)).status_code == 200
    assert (
        await client.post(f"{base}/sample.notes/enable", json=scope, headers=headers)
    ).status_code == 200
    for minimum, maximum in [("2.0.1", "3.0.0"), ("1.0.0", "2.0.0")]:
        newer, _ = publisher[1](
            "2.0.0", compatibility={"min_inclusive": minimum, "max_exclusive": maximum}
        )
        denied = await client.post(f"{base}/install", json=newer, headers=headers)
        assert denied.status_code == 400, denied.text
        assert "host ABI" in denied.json()["detail"]
    active = await client.post(
        f"{base}/sample.notes/invoke",
        headers=headers,
        json={**scope, "tool_name": "note.ping", "payload": {"op": "ping"}},
    )
    assert active.json()["op"] == "ping"


async def test_old_admin_view_cannot_activate_or_remove_a_newly_staged_release(http, publisher):
    client, tokens = http
    headers = {"Authorization": f"Bearer {tokens['owner']}"}
    root = "/api/v1/platform-plugins/v2/optional-business"
    item = root + "/sample.notes"
    scope = {"tenant_id": "t", "project_id": "p"}
    first, _ = publisher[1]()
    second, _ = publisher[1]("2.0.0", result="pong")
    assert (await client.post(root + "/install", json=first, headers=headers)).is_success
    old = (await client.get(item, params=scope, headers=headers)).json()["desired_revision"]
    assert (await client.post(root + "/install", json=second, headers=headers)).is_success
    for action in ("enable", "uninstall"):
        response = await client.post(
            f"{item}/{action}", json={**scope, "expected_revision": old}, headers=headers
        )
        assert response.status_code == 409, response.text
    current = (await client.get(item, params=scope, headers=headers)).json()
    assert current["installed_version"] == "2.0.0" and current["running_version"] is None
    response = await client.post(
        item + "/enable",
        json={**scope, "expected_revision": current["desired_revision"]},
        headers=headers,
    )
    assert response.is_success, response.text


def test_cloud_admits_a_genuine_legacy_signed_release_without_host_abi(publisher):
    from dataclasses import replace

    from src.infrastructure.plugins.v2.layer_composer import bundle_manifest_digest_v2
    from src.infrastructure.plugins.v2.project_plugin_package import admit_package
    from src.infrastructure.plugins.v2.protocol import parse_bundle_manifest_v2

    body, _ = publisher[1]()
    legacy = BytesIO()
    key = Ed25519PrivateKey.generate()
    with (
        ZipFile(BytesIO(base64.b64decode(body["archive_base64"]))) as original,
        ZipFile(legacy, "w") as rebuilt,
    ):
        descriptor = json.loads(original.read("bundle.json"))
        parsed = parse_bundle_manifest_v2(descriptor)
        artifacts = tuple(a for a in parsed.artifacts if a.path != "compatibility.json")
        descriptor["artifacts"] = [
            a for a in descriptor["artifacts"] if a["path"] != "compatibility.json"
        ]
        digest = bundle_manifest_digest_v2(replace(parsed, artifacts=artifacts))
        descriptor["digest"] = digest
        descriptor["signature"] = base64.b64encode(key.sign(digest.encode())).decode()
        rebuilt.writestr("bundle.json", json.dumps(descriptor))
        for asset in artifacts:
            rebuilt.writestr(asset.path, original.read(asset.path))
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    accepted = admit_package(
        legacy.getvalue(), (public,), frozenset(body["approved_permissions"]), None
    )
    assert accepted.digest == digest
