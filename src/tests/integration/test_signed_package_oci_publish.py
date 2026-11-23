"""Publish externally built packages to a real registry and install through both API hosts."""

import asyncio
import base64
import io
import json
import os
import time
import zipfile

import httpx
import pytest
from memstack_plugin_sdk.publish import publish

import docker
from src.tests.unit.routers.test_optional_business_http_v2 import http, publisher  # noqa: F401

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("OCI_WORKER_DOCKER_TESTS") != "1", reason="requires Docker"),
]


@pytest.fixture(scope="module")
def registry_origin():
    engine = docker.from_env(timeout=60)
    container = engine.containers.run(
        "registry:2",
        detach=True,
        ports={"5000/tcp": ("127.0.0.1", None)},
        environment={"REGISTRY_HTTP_RELATIVEURLS": "true"},
    )
    try:
        container.reload()
        port = container.attrs["NetworkSettings"]["Ports"]["5000/tcp"][0]["HostPort"]
        origin = "http://127.0.0.1:" + port
        with httpx.Client(timeout=2) as probe:
            for _ in range(50):
                try:
                    if probe.get(origin + "/v2/").is_success:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail("disposable registry did not start")
        yield origin
    finally:
        container.remove(force=True, v=True)
        engine.close()


async def test_publish_install_upgrade_and_rollback(registry_origin, http, publisher):  # noqa: F811
    client, tokens = http
    headers = {"Authorization": "Bearer " + tokens["owner"]}
    actor = {"tenant_id": "t", "project_id": "p"}
    package = "/api/v1/platform-plugins/v2/optional-business/sample.notes"
    market = "/api/v1/plugin-marketplace/packages/sample.notes/install"
    client._transport.app.state.plugin_marketplace_allowed_registries_v2 = frozenset(
        {registry_origin}
    )
    for version, answer in (("1.0.0", "ping"), ("1.1.0", "pong")):
        local, digest = publisher[1](version, result=answer)
        raw = base64.b64decode(local["archive_base64"])
        receipt = await asyncio.to_thread(publish, raw, registry_origin, "memstack/notes")
        assert receipt == await asyncio.to_thread(publish, raw, registry_origin, "memstack/notes")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            descriptor = json.loads(archive.read("bundle.json"))
        body = {
            **receipt,
            **actor,
            "publisher": "official",
            "manifest": descriptor,
            "signature": {
                "public_key_pem": publisher[0],
                "signature_base64": descriptor["signature"],
            },
            "provenance": {
                "predicate_type": "package-build",
                "builder_id": "publisher",
                "subject_name": "sample.notes",
            },
            "approved_permissions": local["approved_permissions"],
            "tenant_admin_approved": True,
        }
        result = await client.post(market, json=body, headers=headers)
        assert result.status_code == 202 and result.json()["status"] == "approved", result.text
        call = await client.post(
            package + "/commands",
            json={**actor, "command_id": "ping", "expected_digest": digest},
            headers=headers,
        )
        assert call.json()["op"] == answer
    assert (await client.post(package + "/rollback", json=actor, headers=headers)).is_success
    call = await client.post(
        package + "/commands", json={**actor, "command_id": "ping"}, headers=headers
    )
    assert call.json()["op"] == "ping"
