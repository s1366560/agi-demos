"""Observed HTTP generation conditions against real publication and PostgreSQL."""

from __future__ import annotations

import json
import os
from copy import deepcopy

import pytest
from sqlalchemy import select

from src.infrastructure.adapters.primary.web.cloud_knowledge_sync_generation_v2 import (
    KNOWLEDGE_SYNC_GENERATION_HEADER as HEADER,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncChangeModel as Change,
    KnowledgeSyncEnrollmentModel as Enrollment,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory
from src.tests.integration.test_cloud_knowledge_sync_generation_postgres import (
    BASE,
    ENROLL,
    cloud_sync_http as _cloud_sync_http,
    mutation,
    pg_sync as _pg_sync,
)

cloud_sync_http = _cloud_sync_http
pg_sync = _pg_sync
pytestmark = pytest.mark.skipif(
    os.getenv("KNOWLEDGE_SYNC_POSTGRES_TESTS") != "1",
    reason="Requires the existing dedicated PostgreSQL QA database opt-in",
)


async def conditioned_requests(client, headers):
    return (
        await client.post(BASE + "/enrollment", json=ENROLL, headers=headers),
        await client.post(BASE + "/mutations", json=mutation(), headers=headers),
        await client.get(BASE + "/changes", headers=headers),
        await client.get(BASE + "/conflicts/conflict", headers=headers),
        await client.post(
            BASE + "/conflicts/conflict/resolve",
            json={
                "change_id": "resolve",
                "expected_current_revision": 1,
                "decision": "keep_current",
            },
            headers=headers,
        ),
    )


async def assert_no_writes(f):
    async with f.sessions() as db:
        assert not (await db.get(Enrollment, "project")).enabled
        assert (await db.scalars(select(Memory))).all() == []
        assert (await db.scalars(select(Change))).all() == []


async def test_missing_condition_rejects_all_five_routes_before_authentication_or_sql(
    cloud_sync_http,
):
    f = cloud_sync_http
    del f.client.headers[HEADER]
    before = (f.events.auth_calls, f.events.db_sessions)
    for response in await conditioned_requests(f.client, []):
        assert response.status_code == 428, response.text
        assert response.json()["detail"]["code"] == "knowledge_sync_generation_required"
    assert (f.events.auth_calls, f.events.db_sessions) == before
    await assert_no_writes(f)


@pytest.mark.parametrize(
    ("section", "field", "value", "remove"),
    [
        ("envelope", "extra", True, False),
        ("envelope", "descriptor", None, True),
        ("envelope", "contract_version", "2.0.0", False),
        ("descriptor", "generation", True, False),
        ("descriptor", "generation", 81.0, False),
        ("descriptor", "generation", "81", False),
        ("descriptor", "generation", 0, False),
        ("descriptor", "generation", -1, False),
        ("descriptor", "extra", True, False),
        ("descriptor", "digest", None, True),
        ("descriptor", "digest", "A" * 64, False),
        ("descriptor", "digest", "a", False),
        ("descriptor", "profile_id", "", False),
        ("descriptor", "profile_id", " padded-profile", False),
    ],
)
async def test_invalid_condition_fields_reject_data_and_observation_before_sql(
    cloud_sync_http, section, field, value, remove
):
    f = cloud_sync_http
    payload = json.loads(f.client.headers.pop(HEADER))
    target = payload if section == "envelope" else payload["descriptor"]
    if remove:
        del target[field]
    else:
        target[field] = value
    await assert_invalid_before_sql(f, [(HEADER, json.dumps(payload))])


@pytest.mark.parametrize(
    "invalid",
    [
        "duplicate_header",
        "empty",
        "oversize",
        "invalid_json",
        "array",
        "null",
        "duplicate_version",
        "duplicate_descriptor_field",
        "nan_generation",
    ],
)
async def test_invalid_header_encoding_rejects_data_and_observation_before_sql(
    cloud_sync_http, invalid
):
    f = cloud_sync_http
    original = f.client.headers.pop(HEADER)
    raw = original
    match invalid:
        case "empty":
            raw = ""
        case "oversize":
            raw = " " * 2049
        case "invalid_json":
            raw = "{"
        case "array":
            raw = "[]"
        case "null":
            raw = "null"
        case "duplicate_version":
            raw = '{"contract_version":"1.0.0",' + original[1:]
        case "duplicate_descriptor_field":
            raw = original.replace('"generation": 81', '"generation": 81, "generation": 81')
            assert raw != original
        case "nan_generation":
            raw = original.replace('"generation": 81', '"generation": NaN')
    headers = [(HEADER, raw)]
    if invalid == "duplicate_header":
        headers.append((HEADER.lower(), original))
    await assert_invalid_before_sql(f, headers)


async def assert_invalid_before_sql(f, headers):
    before = (f.events.auth_calls, f.events.db_sessions)
    responses = await conditioned_requests(f.client, headers)
    observation = await f.client.get(BASE + "/enrollment", headers=headers)
    for response in (*responses, observation):
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "knowledge_sync_generation_invalid"
    assert (f.events.auth_calls, f.events.db_sessions) == before
    await assert_no_writes(f)


@pytest.mark.parametrize("field", ["profile_id", "generation", "digest"])
async def test_every_descriptor_component_is_compared_before_sql(cloud_sync_http, field):
    f = cloud_sync_http
    payload = json.loads(f.client.headers.pop(HEADER))
    payload["descriptor"][field] = {
        "profile_id": "foreign-profile",
        "generation": 80,
        "digest": "0" * 64,
    }[field]
    before = (f.events.auth_calls, f.events.db_sessions)
    for response in await conditioned_requests(f.client, {HEADER: json.dumps(payload)}):
        assert response.status_code == 412, response.text
        assert response.json()["detail"]["code"] == "knowledge_sync_generation_mismatch"
    assert (f.events.auth_calls, f.events.db_sessions) == before
    await assert_no_writes(f)


async def test_publication_drift_requires_new_observation_and_does_not_pin_enrollment(
    cloud_sync_http,
):
    f = cloud_sync_http
    old = json.loads(f.client.headers.pop(HEADER))
    new_descriptor = await f.publish(82)
    assert new_descriptor != old["descriptor"]
    before = (f.events.auth_calls, f.events.db_sessions)
    for response in await conditioned_requests(f.client, {HEADER: json.dumps(old)}):
        assert response.status_code == 412, response.text
    assert (f.events.auth_calls, f.events.db_sessions) == before
    await assert_no_writes(f)

    observed = await f.client.get(BASE + "/enrollment")
    assert observed.status_code == 200, observed.text
    new = observed.json()["generation"]
    assert new == {"contract_version": "1.0.0", "descriptor": new_descriptor}
    f.client.headers[HEADER] = json.dumps(new)
    enrolled = await f.client.post(BASE + "/enrollment", json=ENROLL)
    assert enrolled.status_code == 200, enrolled.text
    assert enrolled.json()["generation"] == new
    assert (await f.client.post(BASE + "/mutations", json=mutation())).status_code == 200

    # A durable enrolled project remains usable after a later request observes a new generation.
    await f.publish(83)
    del f.client.headers[HEADER]
    observed = await f.client.get(BASE + "/enrollment")
    assert observed.json()["enabled"] is True
    f.client.headers[HEADER] = json.dumps(observed.json()["generation"])
    changes = await f.client.get(BASE + "/changes")
    assert changes.status_code == 200, changes.text
    assert changes.json()["next_cursor"] == 1


async def test_observation_reports_its_request_pin_when_host_publishes_during_authentication(
    cloud_sync_http,
):
    f = cloud_sync_http
    old = deepcopy(json.loads(f.client.headers.pop(HEADER)))
    f.events.on_auth = lambda: f.publish(82)
    observed = await f.client.get(BASE + "/enrollment")
    assert observed.status_code == 200, observed.text
    assert observed.json()["generation"] == old
    assert f.host.current_distribution.descriptor.generation == 82
    stale = await f.client.post(
        BASE + "/enrollment", json=ENROLL, headers={HEADER: json.dumps(old)}
    )
    assert stale.status_code == 412, stale.text
    await assert_no_writes(f)


async def test_disabling_profile_removes_all_six_routes_even_with_a_previous_condition(
    cloud_sync_http,
):
    f = cloud_sync_http
    old = f.client.headers.pop(HEADER)
    await f.publish(82, routes_enabled=False)
    for response in (
        await f.client.get(BASE + "/enrollment"),
        *await conditioned_requests(f.client, {HEADER: old}),
    ):
        assert response.status_code == 404, response.text
    await assert_no_writes(f)
