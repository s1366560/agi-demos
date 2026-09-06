"""Actual user authentication, SQL scope authorization and immutable source writes."""

from dataclasses import replace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from src.domain.model.plugins.generated_v2 import ProfileLayerKindV2
from src.infrastructure.adapters.primary.web.dependencies import create_api_key
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_model_v2 import (
    PlatformPluginV2ProfileSourceModel,
)
from src.infrastructure.plugins.v2.builtin_platform_plugins_http_routes import (
    platform_plugins_route_definitions_v2,
)
from src.infrastructure.plugins.v2.layer_composer import profile_source_digest_v2
from src.infrastructure.plugins.v2.protocol import profile_source_v2_to_payload
from src.infrastructure.plugins.v2.scope import parse_scope_v2
from src.tests.unit.infrastructure.plugins.v2.layer_composer_test_support import _layer, _source

pytestmark = pytest.mark.unit
PATH = "/api/v1/platform-plugins/v2/profile-sources"


@pytest.fixture
async def authenticated_source(db_session):
    for name in ("owner", "visitor"):
        db_session.add(
            User(
                id=name,
                email=f"{name}@source.test",
                hashed_password="unused",
                is_active=True,
                is_superuser=False,
            )
        )
    await db_session.flush()
    db_session.add(Tenant(id="t", name="Tenant", slug="source-t", owner_id="owner"))
    await db_session.flush()
    db_session.add(Project(id="p", name="Project", tenant_id="t", owner_id="owner"))
    await db_session.flush()
    db_session.add_all(
        [
            Conversation(id="s", title="Session", tenant_id="t", project_id="p", user_id="owner"),
            UserTenant(id="ut", user_id="owner", tenant_id="t", role="admin"),
            UserProject(id="up", user_id="owner", project_id="p", role="admin"),
            UserTenant(id="visitor-ut", user_id="visitor", tenant_id="t", role="member"),
            UserProject(id="visitor-up", user_id="visitor", project_id="p", role="member"),
        ]
    )
    keys = {}
    for name in ("owner", "visitor"):
        keys[name], _ = await create_api_key(db_session, name, "source-test", [])
    await db_session.commit()
    app = FastAPI()
    definition = next(
        route for route in platform_plugins_route_definitions_v2() if route.path == PATH
    )
    app.add_api_route(definition.path, definition.endpoint, methods=list(definition.methods))
    desired_route = next(
        route
        for route in platform_plugins_route_definitions_v2()
        if route.path.endswith("/desired-bundle-sets/current") and "PUT" in route.methods
    )
    app.add_api_route(desired_route.path, desired_route.endpoint, methods=["PUT"])

    async def database():
        return db_session

    app.dependency_overrides[get_db] = database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, keys


def payload(kind="tenant", revision=1, expected=None):
    scope = {"kind": kind, "tenant_id": "t"}
    if kind in {"project", "session"}:
        scope["project_id"] = "p"
    if kind == "session":
        scope["session_id"] = "s"
    source = _source(
        (
            _layer(
                "layer",
                ProfileLayerKindV2(kind),
                scope=parse_scope_v2(scope),
                disabled_entry_ids=("entry",),
            ),
        )
    )
    source = replace(source, revision=revision)
    source = replace(source, digest=profile_source_digest_v2(source))
    return {
        "scope": scope,
        "source": profile_source_v2_to_payload(source),
        "expected_revision": expected,
    }


@pytest.mark.parametrize("kind", ["tenant", "project", "session"])
async def test_source_authenticated_write_and_cas(authenticated_source, db_session, kind):
    client, keys = authenticated_source
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    request = payload(kind)
    response = await client.post(PATH, json=request, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"scope": request["scope"], "source": request["source"]}
    assert (await client.post(PATH, json=request, headers=headers)).status_code == 200
    assert (await client.post(PATH, json=payload(kind, 2), headers=headers)).status_code == 409
    assert (await client.post(PATH, json=payload(kind, 2, 1), headers=headers)).status_code == 200
    assert (
        await db_session.scalar(
            select(func.count()).select_from(PlatformPluginV2ProfileSourceModel)
        )
        == 2
    )


@pytest.mark.parametrize("kind", ["tenant", "project", "session"])
async def test_source_unauthenticated_or_member_cannot_write(
    authenticated_source, db_session, kind
):
    client, keys = authenticated_source
    request = payload(kind)
    assert (await client.post(PATH, json=request)).status_code in (401, 403)
    response = await client.post(
        PATH, json=request, headers={"Authorization": f"Bearer {keys['visitor']}"}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["reason_code"] == "profile_source_scope_forbidden"
    assert (
        await db_session.scalar(
            select(func.count()).select_from(PlatformPluginV2ProfileSourceModel)
        )
        == 0
    )


async def test_source_rejects_foreign_layer_and_fetch_field(authenticated_source, db_session):
    client, keys = authenticated_source
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    request = payload()
    request["fetch_url"] = "https://invalid.example/private-canary"
    response = await client.post(PATH, json=request, headers=headers)
    assert response.status_code == 400
    assert "private-canary" not in response.text
    request = payload()
    request["scope"]["tenant_id"] = "missing"
    assert (await client.post(PATH, json=request, headers=headers)).status_code == 403
    request = payload("project")
    request["scope"] = {"kind": "tenant", "tenant_id": "t"}
    assert (await client.post(PATH, json=request, headers=headers)).status_code == 400
    assert (
        await db_session.scalar(
            select(func.count()).select_from(PlatformPluginV2ProfileSourceModel)
        )
        == 0
    )


async def test_source_post_then_desired_pointer_exact_scope_and_cas(
    authenticated_source, db_session
):
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
        PlatformPluginDesiredBundleSetRepositoryV2,
    )
    from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
    from src.infrastructure.plugins.v2.protocol import (
        desired_bundle_set_v2_to_payload,
        parse_profile_source_v2,
    )
    from src.tests.unit.infrastructure.plugins.v2.layer_composer_test_support import _desired

    client, keys = authenticated_source
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    request = payload()
    source = parse_profile_source_v2(request["source"])
    desired = replace(_desired((), source), revision=1)
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    desired_request = {
        "schema_version": 2,
        "scope": request["scope"],
        "expected_revision": None,
        "desired_bundle_set": desired_bundle_set_v2_to_payload(desired),
    }
    path = "/api/v1/platform-plugins/v2/desired-bundle-sets/current"
    assert (await client.put(path, json=desired_request, headers=headers)).status_code == 409
    assert (await client.post(PATH, json=request, headers=headers)).status_code == 200
    cross_scope = {
        **desired_request,
        "scope": {"kind": "project", "tenant_id": "t", "project_id": "p"},
    }
    assert (await client.put(path, json=cross_scope, headers=headers)).status_code == 409
    accepted = await client.put(path, json=desired_request, headers=headers)
    assert accepted.status_code == 200, accepted.text
    second = replace(desired, revision=2)
    second = replace(second, digest=desired_bundle_set_digest_v2(second))
    failed = await client.put(
        path,
        json={**desired_request, "desired_bundle_set": desired_bundle_set_v2_to_payload(second)},
        headers=headers,
    )
    assert failed.status_code == 409
    current = await PlatformPluginDesiredBundleSetRepositoryV2(db_session).current_desired_set(
        parse_scope_v2(request["scope"])
    )
    assert current is not None
    assert current.desired_set == desired
