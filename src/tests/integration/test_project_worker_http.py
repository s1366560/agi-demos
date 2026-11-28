"""Install an unknown signed OCI worker and consume its real project HTTP stream."""

import asyncio
import base64
import json
import logging
import os
import socket

import httpx
import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from memstack_plugin_sdk.pack import build

from src.configuration.config import get_settings
from src.tests.integration.test_oci_mcp_worker_docker import DOC, worker_image  # noqa: F401
from src.tests.unit.routers.test_optional_business_http_v2 import http, publisher  # noqa: F401

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("OCI_WORKER_DOCKER_TESTS") != "1", reason="requires Docker"),
]


async def test_closed_worker_release_through_project_http(
    http,  # noqa: F811
    worker_image,  # noqa: F811
    tmp_path,
    monkeypatch,
    caplog,
    db_session,
):
    caplog.set_level(logging.INFO, logger="plugin_audit")
    from src.infrastructure.plugins.v2 import project_package_execution

    image, registry, docker = worker_image
    key = Ed25519PrivateKey.generate()
    client, keys = http
    client._transport.app.state.plugin_marketplace_trusted_public_keys_v2 = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
    )
    (tmp_path / "worker.json").write_text(
        json.dumps(
            {"schema": "memstack.mcp-oci-worker/1", "image": image, "entrypoint": "/app/worker"}
        )
    )
    signed_command = {
        "id": "probe-action",
        "tool": "probe",
        "payload": {},
        "accepts_input": True,
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "permissions": ["tools.execute"],
    }
    (tmp_path / "contribution.json").write_text(json.dumps({**DOC, "commands": [signed_command]}))
    cfg = tmp_path / "package.json"
    cfg.write_text(
        json.dumps(
            {
                "plugin_id": "sample-worker",
                "tool_name": "probe",
                "version": "1.0.0",
                "target": "python",
                "worker": "worker.json",
                "contribution": "contribution.json",
                "provenance": "repo://qa/closed-worker",
            }
        )
    )
    raw = build(cfg, key)
    scope = {"tenant_id": "t", "project_id": "p"}
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    base = "/api/v1/platform-plugins/v2/optional-business"
    archive = {**scope, "archive_base64": base64.b64encode(raw).decode()}
    admitted = (await client.post(base + "/inspect", json=archive, headers=headers)).json()
    assert admitted["permissions"] == ["tools.execute"]
    created = await client.post(
        base + "/install",
        json={**archive, "approved_permissions": admitted["permissions"]},
        headers=headers,
    )
    assert created.status_code == 200
    root = base + "/sample-worker"
    settings = get_settings().model_copy(update={"plugin_worker_allowed_registries": ()})
    monkeypatch.setattr(project_package_execution, "get_settings", lambda: settings)
    denied = await client.post(root + "/enable", json=scope, headers=headers)
    assert denied.status_code == 409
    settings = settings.model_copy(update={"plugin_worker_allowed_registries": (registry,)})
    enabled = await client.post(root + "/enable", json=scope, headers=headers)
    assert enabled.status_code == 200, enabled.text
    await _check_replica_execution_backend(client._transport.app, db_session, image, monkeypatch)
    response = await client.post(
        root + "/invoke-stream",
        json={**scope, "tool_name": "probe", "payload": {}, "expected_digest": admitted["digest"]},
        headers=headers,
    )
    assert response.status_code == 200
    frames = [json.loads(line) for line in response.text.splitlines()]
    # Queueing a container on a busy daemon can legitimately generate idle heartbeats.
    events = [frame for frame in frames if frame != {"type": "keepalive"}]
    assert [event["type"] for event in events] == ["progress", "result"]
    assert events[0]["data"] == {"progress": 1, "total": 2.5, "message": "working"}
    assert events[1]["data"]["uid"] == 65532
    assert events[1]["data"]["writable"] is False
    assert not docker.containers.list(
        all=True, filters={"label": f"memstack.release={admitted['digest']}"}
    )

    command = await client.post(
        root + "/commands?stream=true",
        json={**scope, "command_id": "probe-action", "expected_digest": admitted["digest"]},
        headers=headers,
    )
    assert command.is_success and command.headers["content-type"] == "application/x-ndjson"
    messages = [json.loads(line) for line in command.text.splitlines()]
    assert [msg for msg in messages if msg["type"] != "keepalive"] == events

    # ASGITransport buffers the response. Use TCP for the client-disconnect contract.
    await _disconnect_after_progress(
        client._transport.app,
        root + "/invoke-stream",
        {"tool_name": "probe"},
        scope,
        headers,
        admitted["digest"],
        docker,
    )
    await _disconnect_after_progress(
        client._transport.app,
        root + "/commands?stream=true",
        {"command_id": "probe-action"},
        scope,
        headers,
        admitted["digest"],
        docker,
    )
    receipts = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "plugin_audit.project_package"
    ]
    command_calls = [event for event in receipts if event["operation"] == "command"]
    assert [event["outcome"] for event in command_calls] == ["ok", "cancelled"]
    calls = [event for event in receipts if event["operation"] == "tool"]
    assert [(e["executor"], e["outcome"]) for e in calls] == [("oci", "ok"), ("oci", "cancelled")]
    assert all(e["actor_id"] == "owner" and e["digest"] == admitted["digest"] for e in calls)


async def _check_replica_execution_backend(app, db_session, image, monkeypatch):
    from starlette.requests import Request

    from src.host.operations.project_package_readiness import (
        project_packages_ready,
    )
    from src.infrastructure.plugins.v2 import oci_mcp_worker, project_package_execution

    request = Request({"type": "http", "app": app})
    assert await project_packages_ready(request, db_session)
    assert await project_packages_ready(request, db_session)
    missing = image.split("@")[0] + "@sha256:" + "0" * 64
    assert oci_mcp_worker.missing_worker_images({image, missing}) == {missing}

    def offline(images):
        raise OSError("execution daemon offline")

    with monkeypatch.context() as interrupted:
        interrupted.setattr(oci_mcp_worker, "missing_worker_images", offline)
        assert not await project_packages_ready(request, db_session)
    with monkeypatch.context() as revoked:
        settings = get_settings().model_copy(update={"plugin_worker_allowed_registries": ()})
        revoked.setattr(project_package_execution, "get_settings", lambda: settings)
        assert not await project_packages_ready(request, db_session)
    assert await project_packages_ready(request, db_session)


async def _disconnect_after_progress(app, path, operation, scope, headers, digest, engine):
    options = uvicorn.Config(app, lifespan="off", log_level="error", access_log=False)
    server = uvicorn.Server(options)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(16)
        port = listener.getsockname()[1]
        run = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    await asyncio.sleep(0.02)
            async with (
                httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{port}", timeout=15, trust_env=False
                ) as tcp,
                tcp.stream(
                    "POST",
                    path,
                    json={
                        **scope,
                        "expected_digest": digest,
                        **operation,
                        "payload": {"wait": True},
                    },
                    headers=headers,
                ) as response,
            ):
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    event = json.loads(line)
                    if event["type"] == "keepalive":
                        continue
                    assert event == {
                        "type": "progress",
                        "data": {"progress": 1, "total": 2.5, "message": "working"},
                    }
                    break
            async with asyncio.timeout(8):
                while await asyncio.to_thread(
                    engine.api.containers,
                    all=True,
                    filters={"label": f"memstack.release={digest}"},
                ):
                    await asyncio.sleep(0.05)
        finally:
            server.should_exit = True
            await asyncio.wait_for(run, 12)
