"""Run the production gateway binary, a scoped Python HTTP listener and a real signed worker."""

import asyncio
import base64
import json
import os
from uuid import uuid4

import pytest

from src.configuration.config import get_settings
from src.infrastructure.plugins.v2.signed_optional_business_v2 import ScopeBindingV2
from src.tests.integration import package_gateway, test_oci_mcp_worker_docker as worker_fixtures
from src.tests.unit.routers import test_optional_business_http_v2 as package_api

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("OCI_WORKER_DOCKER_TESTS") != "1", reason="requires Docker and Cargo"
    ),
]
http = package_api.http
publisher = package_api.publisher
gateway_binary = package_gateway.gateway_binary
worker_image = worker_fixtures.worker_image


async def test_signed_command_progress_and_disconnect_reach_project_host(
    gateway_binary, http, worker_image, tmp_path, monkeypatch
):
    backend, users = http
    image, registry, engine = worker_image
    plugin = "gateway-" + uuid4().hex
    command = "run-" + uuid4().hex
    scope = {"tenant_id": "t", "project_id": "p"}
    _, digest, _, raw, public = worker_fixtures.signed_worker(
        tmp_path,
        image,
        ScopeBindingV2(**scope),
        plugin_id=plugin,
        command={
            "id": command,
            "tool": "probe",
            "payload": {},
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "permissions": ["tools.execute"],
        },
    )
    monkeypatch.setattr(get_settings(), "plugin_worker_allowed_registries", (registry,))
    backend._transport.app.state.plugin_marketplace_trusted_public_keys_v2 = (public,)
    base = "/api/v1/platform-plugins/v2/optional-business"
    path = base + "/" + plugin
    headers = {"Authorization": f"Bearer {users['owner']}"}
    async with package_gateway.gateway_client(gateway_binary, backend._transport.app) as proxy:
        assert (await proxy.get("/api/v1/memories/")).json() == {"upstream": "rust"}
        install = {
            **scope,
            "archive_base64": base64.b64encode(raw).decode(),
            "approved_permissions": ["tools.execute"],
        }
        unauthenticated = await proxy.post(base + "/install", json=install)
        assert unauthenticated.status_code == 401
        viewer = {"Authorization": f"Bearer {users['viewer']}"}
        assert (
            await proxy.post(base + "/install", json=install, headers=viewer)
        ).status_code == 403
        (await proxy.post(base + "/install", headers=headers, json=install)).raise_for_status()
        (await proxy.post(path + "/enable", headers=headers, json=scope)).raise_for_status()
        pinned = {**scope, "expected_digest": digest}
        result = await proxy.post(
            path + "/commands", headers=headers, json={**pinned, "command_id": command}
        )
        assert result.is_success and result.json()["uid"] == 65532

        async with proxy.stream(
            "POST",
            path + "/invoke-stream",
            headers=headers,
            json={**pinned, "tool_name": "probe", "payload": {"wait": True}},
        ) as response:
            response.raise_for_status()
            assert response.headers["content-type"].startswith("application/x-ndjson")
            assert response.headers["x-accel-buffering"] == "no"
            async with asyncio.timeout(8):
                async for line in response.aiter_lines():
                    message = json.loads(line)
                    if message["type"] == "keepalive":
                        continue
                    assert message == {
                        "type": "progress",
                        "data": {"progress": 1, "total": 2.5, "message": "working"},
                    }
                    break
                else:
                    pytest.fail("gateway ended the response before worker progress")
            workers = {"label": "memstack.release=" + digest}
            assert await asyncio.to_thread(engine.containers.list, filters=workers)
        # Exiting the HTTP stream must release the actual OCI process, ahead of its 30s quota.
        async with asyncio.timeout(8):
            while await asyncio.to_thread(engine.api.containers, all=True, filters=workers):
                await asyncio.sleep(0.05)

        async with proxy.stream(
            "POST",
            path + "/invoke-stream",
            headers=headers,
            json={**pinned, "tool_name": "probe", "payload": {}},
        ) as response:
            response.raise_for_status()
            events = [json.loads(line) async for line in response.aiter_lines()]
            delivered = [event for event in events if event["type"] != "keepalive"]
            assert [event["type"] for event in delivered] == ["progress", "result"]
            assert delivered[-1]["data"] == result.json()
