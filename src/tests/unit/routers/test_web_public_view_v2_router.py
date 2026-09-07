"""Real user/workload authentication stays separate around the public Web view."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.domain.model.plugins.generated_v2 import (
    ApplyStatusV2,
    ScopeKindV2,
    ScopeV2,
    SnapshotApplyReceiptV2,
)
from src.infrastructure.adapters.primary.web.dependencies import create_api_key
from src.infrastructure.adapters.primary.web.routers import platform_plugins
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.platform_plugin_data_plane_credential_repository_v2 import (
    PlatformPluginDataPlaneCredentialRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.builtin_platform_plugins_http_routes import (
    platform_plugins_route_definitions_v2,
)
from src.infrastructure.plugins.v2.protocol import (
    canonical_json_v2,
    control_envelope_v2,
    parse_profile_snapshot_v2,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginPublicationV2

pytestmark = pytest.mark.unit
_ROOT = Path(__file__).resolve().parents[4]
_PATH = "/api/v1/platform-plugins/v2/web-view"


@pytest.fixture
async def authenticated_views(db_session):
    app = FastAPI()
    app.include_router(platform_plugins.router)

    async def database():
        return db_session

    app.dependency_overrides[get_db] = database
    keys = []
    for index in range(2):
        user = User(
            id=f"web-view-user-{index}",
            email=f"web-view-{index}@example.test",
            hashed_password="unused",
            is_active=True,
            is_superuser=False,
        )
        db_session.add(user)
        await db_session.flush()
        key, _ = await create_api_key(db_session, user.id, "view-test", [])
        keys.append(key)
    workload = await PlatformPluginDataPlaneCredentialRepositoryV2(db_session).issue(
        data_plane_id="web-v2", actor_id="fixture"
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, keys, workload.secret


async def requested(
    db,
    *,
    invalid_config=False,
    nonroot=False,
    scope=ScopeV2(kind=ScopeKindV2.ROOT),
    version=1,
    nonce="private-workload-nonce",
):
    payload = json.loads((_ROOT / "shared/profiles/memstack-default-bootstrap.v2.json").read_text())
    host = next(
        entry
        for entry in payload["entries"]
        if entry["module_ref"] == "builtin://memstack/web/renderer-host"
    )
    if invalid_config:
        host["config"]["private-extra"] = "private-secret-canary"
    if nonroot:
        web_refs = {
            module["module_ref"]
            for manifest in payload["manifests"]
            for module in manifest["modules"]
            if "web" in module["targets"]
        }
        for entry in payload["entries"]:
            if entry["module_ref"] in web_refs:
                entry["scope"] = {"kind": "tenant", "tenant_id": "private-tenant-canary"}
    private = next(
        entry
        for entry in payload["entries"]
        if entry["module_ref"] == "builtin://memstack/desktop/renderer-host"
    )
    private["config"]["private-extra"] = "private-secret-canary"
    payload.pop("digest")
    payload["digest"] = hashlib.sha256(canonical_json_v2(payload)).hexdigest()
    snapshot = parse_profile_snapshot_v2(payload)
    envelope = control_envelope_v2(snapshot, version=version, nonce=nonce)
    # A requested publication is readable before any workload has accepted it.
    receipt = SnapshotApplyReceiptV2(
        status=ApplyStatusV2.NACK,
        requested_version=version,
        requested_digest=snapshot.digest,
        applied_version=None,
        applied_digest=None,
        error_code="fixture_not_applied",
        error_message="No local application attempted",
    )
    await PlatformPluginRepositoryV2(db, scope=scope).record_publication(
        PlatformPluginPublicationV2(snapshot=snapshot, envelope=envelope, receipt=receipt)
    )
    await db.commit()


async def test_real_user_can_get_only_public_view_while_workload_endpoint_stays_private(
    authenticated_views, db_session
):
    client, keys, workload = authenticated_views
    await requested(db_session)
    assert (await client.get(_PATH)).status_code == 401
    assert (
        await client.get(_PATH, headers={"Authorization": f"Bearer {workload}"})
    ).status_code == 401
    user_headers = {"Authorization": f"Bearer {keys[0]}"}
    response = await client.get(_PATH, headers=user_headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    public = response.json()
    assert set(public) == {"schema_version", "target", "view_id", "snapshot"}
    assert len(public["snapshot"]["entries"]) == 6
    parse_profile_snapshot_v2(public["snapshot"])
    assert "private-secret-canary" not in response.text
    assert "private-workload-nonce" not in response.text
    other = await client.get(_PATH, headers={"Authorization": f"Bearer {keys[1]}"})
    assert other.status_code == 200
    assert public["view_id"] != other.json()["view_id"]
    assert public["snapshot"] == other.json()["snapshot"]
    distribution = await client.get(
        "/api/v1/platform-plugins/v2/distribution", headers=user_headers
    )
    assert distribution.status_code == 401
    submission = await client.post(
        "/api/v1/platform-plugins/v2/data-plane-state", headers=user_headers, json={}
    )
    assert submission.status_code == 401


async def test_no_requested_publication_returns_404(authenticated_views):
    client, keys, _ = authenticated_views
    assert (
        await client.get(_PATH, headers={"Authorization": f"Bearer {keys[0]}"})
    ).status_code == 404


async def test_invalid_public_configuration_returns_fixed_safe_error(
    authenticated_views, db_session
):
    client, keys, _ = authenticated_views
    await requested(db_session, invalid_config=True)
    response = await client.get(_PATH, headers={"Authorization": f"Bearer {keys[0]}"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "web_public_view_unavailable"
    assert "private-secret-canary" not in response.text
    assert "private-extra" not in response.text


def test_real_builtin_route_contribution_registers_public_view():
    route = next(route for route in platform_plugins_route_definitions_v2() if route.path == _PATH)
    assert route.methods == ("GET",)
    assert route.endpoint.__name__ == "get_web_public_view_v2"
    assert route.replaces_builtin_row_id == "platform-plugins"


async def test_nonroot_view_requires_future_scope_authorization(authenticated_views, db_session):
    client, keys, _ = authenticated_views
    await requested(db_session, nonroot=True)
    response = await client.get(_PATH, headers={"Authorization": f"Bearer {keys[0]}"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "web_public_view_unavailable"
    assert "private-tenant-canary" not in response.text


@pytest.mark.parametrize("has_root", [False, True])
async def test_root_http_views_ignore_newer_scoped_publications(
    authenticated_views, db_session, has_root
):
    client, keys, workload = authenticated_views
    user_headers = {"Authorization": f"Bearer {keys[0]}"}
    workload_headers = {"Authorization": f"Bearer {workload}"}
    distribution_path = "/api/v1/platform-plugins/v2/distribution"
    if has_root:
        await requested(db_session)
    prior_view = await client.get(_PATH, headers=user_headers)
    prior_distribution = await client.get(distribution_path, headers=workload_headers)
    expected = 200 if has_root else 404
    assert prior_view.status_code == prior_distribution.status_code == expected
    await requested(
        db_session,
        scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="isolated-tenant"),
        version=999,
        nonce="scoped-private-nonce",
        invalid_config=True,
    )
    view = await client.get(_PATH, headers=user_headers)
    distribution = await client.get(distribution_path, headers=workload_headers)
    assert view.status_code == distribution.status_code == expected
    assert view.json() == prior_view.json()
    assert distribution.json() == prior_distribution.json()
    assert "scoped-private-nonce" not in distribution.text
