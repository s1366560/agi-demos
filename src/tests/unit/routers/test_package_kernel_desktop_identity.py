"""Native cloud-session discovery with real memberships and persisted revisions."""

import httpx
import pytest
from sqlalchemy import delete

from src.host.transport.package_kernel import create_app
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import create_api_key
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def desktop(db_session):
    user = User(
        id="desktop-reader",
        email="desktop-reader@example.org",
        hashed_password="unused",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    for tenant in ("one", "two", "other"):
        db_session.add(Tenant(id=tenant, name=tenant, slug=tenant, owner_id=user.id))
    await db_session.flush()
    for tenant, project in (
        ("one", "first"),
        ("two", "second"),
        ("other", "unscoped"),
        ("one", "nonmember"),
    ):
        db_session.add(Project(id=project, tenant_id=tenant, name=project, owner_id=user.id))
    await db_session.flush()
    db_session.add(UserTenant(id="a-first", tenant_id="one", user_id=user.id, role="member"))
    for project in ("first", "second", "unscoped"):
        db_session.add(
            UserProject(id="up-" + project, project_id=project, user_id=user.id, role="viewer")
        )
    token, _ = await create_api_key(db_session, user.id, "desktop-identity", [])
    await db_session.commit()
    app = create_app()

    async def session():
        return db_session

    app.dependency_overrides[get_db] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://kernel"
    ) as client:
        yield client, {"Authorization": f"Bearer {token}"}


async def test_identity_catalogs_are_paginated_and_recheck_both_memberships(desktop, db_session):
    client, headers = desktop
    assert (await client.get("/api/v1/tenants/")).status_code in (401, 403)
    db_session.add(
        UserTenant(id="b-second", tenant_id="two", user_id="desktop-reader", role="member")
    )
    await db_session.commit()
    db_session.add(
        UserTenant(id="duplicate-one", tenant_id="one", user_id="desktop-reader", role="member")
    )
    db_session.add(
        UserProject(
            id="duplicate-first", project_id="first", user_id="desktop-reader", role="viewer"
        )
    )
    await db_session.commit()
    for path, key, expected in (
        ("tenants/", "tenants", ["one", "two"]),
        ("projects/", "projects", ["first", "second"]),
    ):
        results = []
        for page in (1, 2, 3):
            result = await client.get(
                "/api/v1/" + path, params={"page": page, "page_size": 1}, headers=headers
            )
            assert result.status_code == 200, result.text
            body = result.json()
            assert (body["page"], body["page_size"], body["total"]) == (page, 1, 2)
            results.extend(item["id"] for item in body[key])
        if key == "tenants":
            assert results == expected
        else:
            assert sorted(results) == expected
    denied = await client.get("/api/v1/projects/?tenant_id=other", headers=headers)
    assert denied.json() == {
        "projects": [],
        "owner_ids": [],
        "page": 1,
        "page_size": 20,
        "total": 0,
    }
    good = await client.get("/api/v1/projects/first?tenant_id=one", headers=headers)
    assert good.json()["tenant_id"] == "one"
    for pair in ("first?tenant_id=two", "unscoped?tenant_id=other", "nonmember?tenant_id=one"):
        assert (await client.get("/api/v1/projects/" + pair, headers=headers)).status_code == 404
    assert (await client.get("/api/v1/tenants/?page_size=101", headers=headers)).status_code == 422


async def test_context_is_fenced_and_revocation_prevents_replay(desktop, db_session):
    client, headers = desktop
    root = "/api/v1/workspace-context"
    initial = await client.get(root, headers=headers)
    assert initial.status_code == 200, initial.text
    assert initial.json()["context"]["project_id"] == "first"
    switch = {
        "tenant_id": "two",
        "project_id": "second",
        "idempotency_key": "switch-second",
        "expected_revision": 0,
    }
    assert (await client.post(root + "/switch", json=switch, headers=headers)).status_code == 403
    db_session.add(
        UserTenant(id="b-second", tenant_id="two", user_id="desktop-reader", role="member")
    )
    await db_session.commit()
    changed = await client.post(root + "/switch", json=switch, headers=headers)
    assert changed.status_code == 200, changed.text
    assert changed.json()["context"]["revision"] == 1
    assert (await client.get(root, headers=headers)).json()["context"]["project_id"] == "second"
    assert (await client.post(root + "/switch", json=switch, headers=headers)).json()[
        "changed"
    ] is False
    assert (
        await client.post(
            root + "/switch", json={**switch, "idempotency_key": "new-request"}, headers=headers
        )
    ).status_code == 409
    await db_session.execute(delete(UserTenant).where(UserTenant.id == "b-second"))
    await db_session.commit()
    assert (await client.post(root + "/switch", json=switch, headers=headers)).status_code == 403
    repaired = (await client.get(root, headers=headers)).json()["context"]
    assert (repaired["project_id"], repaired["revision"]) == ("first", 2)


async def test_first_context_with_multiple_projects_preserves_explicit_user_choice(
    desktop, db_session
):
    client, headers = desktop
    db_session.add(
        UserTenant(id="b-second", tenant_id="two", user_id="desktop-reader", role="member")
    )
    await db_session.commit()
    root = "/api/v1/workspace-context"
    assert (await client.get(root, headers=headers)).status_code == 404
    chosen = await client.post(
        root + "/switch",
        headers=headers,
        json={
            "tenant_id": "two",
            "project_id": "second",
            "expected_revision": 0,
            "idempotency_key": "initial-selection",
        },
    )
    assert chosen.status_code == 200, chosen.text
    observed = (await client.get(root, headers=headers)).json()["context"]
    assert observed == chosen.json()["context"]
