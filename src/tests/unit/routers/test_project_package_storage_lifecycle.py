"""Exercise retained and purged signed records through each project package router."""

import pytest

from src.infrastructure.adapters.secondary.persistence.models import Project, UserProject
from src.tests.unit.routers import test_optional_business_http_v2 as fixtures

http = fixtures.http
publisher = fixtures.publisher
pytestmark = pytest.mark.unit


async def test_project_purge_erases_only_its_records_while_uninstall_retains_them(
    http, publisher, db_session
):
    assert str(db_session.get_bind().url) == "sqlite+aiosqlite:///:memory:"
    client, keys = http
    db_session.add(Project(id="sibling", tenant_id="t", name="Sibling", owner_id="owner"))
    await db_session.flush()
    db_session.add(
        UserProject(id="sibling-owner", user_id="owner", project_id="sibling", role="owner")
    )
    await db_session.commit()
    owner = {"Authorization": "Bearer " + keys["owner"]}
    viewer = {"Authorization": "Bearer " + keys["viewer"]}
    base = "/api/v1/platform-plugins/v2/optional-business"
    item = base + "/sample.notes"
    key = item + "/storage/record"
    primary = {"tenant_id": "t", "project_id": "p"}
    sibling = {"tenant_id": "t", "project_id": "sibling"}
    archive, _ = publisher[1](storage_limit=1024)

    async def activate(scope):
        assert (
            await client.post(base + "/install", json={**archive, **scope}, headers=owner)
        ).is_success
        assert (await client.post(item + "/enable", json=scope, headers=owner)).is_success

    async def document(scope):
        response = await client.get(key, params=scope, headers=owner)
        assert response.is_success, response.text
        return response.json()["document"]

    for scope in (primary, sibling):
        await activate(scope)
        written = await client.put(
            key, json={**scope, "document": {"project": scope["project_id"]}}, headers=owner
        )
        assert written.is_success

    assert (await client.post(item + "/purge", json=primary, headers=viewer)).status_code == 403
    assert (await client.get(key, params=sibling, headers=viewer)).status_code == 403
    removed = await client.post(item + "/uninstall", json=primary, headers=owner)
    assert removed.is_success and removed.json()["retention"] == "retained"
    await activate(primary)
    assert await document(primary) == {"project": "p"}

    first = await client.post(item + "/purge", json=primary, headers=owner)
    assert first.is_success and first.json()["retention"] == "purged"
    projection = await client.get(item, params=primary, headers=owner)
    assert projection.is_success
    second = await client.post(item + "/purge", json=primary, headers=owner)
    assert second.is_success and second.json() == first.json()
    current = await client.get(item, params=primary, headers=owner)
    assert current.json()["desired_revision"] == projection.json()["desired_revision"]
    assert (await client.get(key, params=primary, headers=owner)).status_code == 403
    await activate(primary)
    assert await document(primary) is None
    assert await document(sibling) == {"project": "sibling"}


async def test_incompatible_signed_update_preserves_namespace_and_running_command(
    http, publisher, db_session
):
    assert str(db_session.get_bind().url) == "sqlite+aiosqlite:///:memory:"
    client, keys = http
    owner = {"Authorization": "Bearer " + keys["owner"]}
    base = "/api/v1/platform-plugins/v2/optional-business"
    item = base + "/sample.notes"
    scope = {"tenant_id": "t", "project_id": "p"}
    release, digest = publisher[1](storage_limit=256)
    assert (await client.post(base + "/install", json=release, headers=owner)).is_success
    assert (await client.post(item + "/enable", json=scope, headers=owner)).is_success
    key = item + "/storage/state"
    document = {"sequence": 8}
    assert (await client.put(key, json={**scope, "document": document}, headers=owner)).is_success

    for options, reason in (
        ({"storage_schema_version": 2}, "storage schema"),
        ({"input_schema": {"type": "unknown-json-type"}}, "is not valid"),
    ):
        upgrade, _ = publisher[1]("2.0.0", storage_limit=256, **options)
        rejected = await client.post(base + "/install", json=upgrade, headers=owner)
        assert rejected.status_code == 400 and reason in rejected.json()["detail"], rejected.text
    active = (await client.get(item, params=scope, headers=owner)).json()
    assert active["actual_digest"] == active["desired_digest"] == digest
    assert (await client.get(key, params=scope, headers=owner)).json()["document"] == document
    executed = await client.post(
        item + "/commands",
        json={**scope, "command_id": "ping", "expected_digest": digest},
        headers=owner,
    )
    assert executed.is_success and executed.json()["op"] == "ping"
