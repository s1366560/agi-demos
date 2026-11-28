"""Install the Environments package and invoke its independently built cluster health worker."""

import base64
import json
import os
import shutil
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from memstack_plugin_sdk.pack import build, stage_contribution

from plugins.business.environments.backend.package_sandbox_operations import SANDBOX_OPERATIONS
from src.configuration.config import get_settings
from src.infrastructure.adapters.primary.web.routers.project_sandbox import (
    get_project_sandbox_runtime_capabilities,
)
from src.infrastructure.plugins.v2 import project_package_execution
from src.tests.integration.test_automation_schedule_package import signed_automation  # noqa: F401
from src.tests.integration.test_oci_mcp_worker_docker import disposable_worker_registry
from src.tests.unit.routers.test_optional_business_http_v2 import http, publisher  # noqa: F401

ROOT = Path(__file__).resolve().parents[3] / "plugins/business/environments"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("OCI_WORKER_DOCKER_TESTS") != "1", reason="requires Docker"),
]


@pytest.fixture(scope="module")
def environment_release(tmp_path_factory):
    stage = tmp_path_factory.mktemp("environments")
    shutil.copyfile(ROOT / "package.json", stage / "package.json")
    stage_contribution(ROOT, stage)
    key = Ed25519PrivateKey.generate()
    with disposable_worker_registry() as (publish, registry, _):
        (stage / "worker.json").write_text(
            json.dumps(
                {
                    "schema": "memstack.mcp-oci-worker/1",
                    "image": publish(ROOT),
                    "entrypoint": "/app/worker",
                }
            )
        )
        raw = build(stage / "package.json", key)
        public = (
            key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        )
        # Reproduce a prior release whose text tool always returned LF. Both
        # revisions use the same signed API and run in different OCI images.
        previous = tmp_path_factory.mktemp("environments-lf")
        patch_module = Path("sandbox-mcp-server/src/tools/text_patch.py")
        for relative in (
            "Dockerfile",
            ".dockerignore",
            "backend/cluster_health.py",
            "worker.py",
            "contributions.json",
            patch_module,
        ):
            dest = previous / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, dest)
        module = previous / patch_module
        module.write_text(
            module.read_text()
            + """
_preserve_endings = patch_text

def patch_text(content, patch):
    result = _preserve_endings(content, patch)
    return {"content": normalize_line_endings(result["content"], "\\n")}
"""
        )
        metadata = json.loads((stage / "package.json").read_text())
        (stage / "package.json").write_text(json.dumps({**metadata, "version": "0.9.0"}))
        descriptor = json.loads((stage / "worker.json").read_text())
        (stage / "worker.json").write_text(json.dumps({**descriptor, "image": publish(previous)}))
        old = build(stage / "package.json", key)
        yield registry, public, base64.b64encode(raw).decode(), base64.b64encode(old).decode()


async def test_environment_worker_through_project_http(http, environment_release, monkeypatch):  # noqa: F811
    registry, public, archive, _ = environment_release
    client, keys = http
    client._transport.app.state.plugin_marketplace_trusted_public_keys_v2 = (public,)
    settings = get_settings().model_copy(update={"plugin_worker_allowed_registries": (registry,)})
    monkeypatch.setattr(project_package_execution, "get_settings", lambda: settings)
    scope = {"tenant_id": "t", "project_id": "p"}
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    root = "/api/v1/platform-plugins/v2/optional-business"
    install = await client.post(
        root + "/install",
        headers=headers,
        json={
            **scope,
            "archive_base64": archive,
            "approved_permissions": [
                "ui.slot",
                "tools.execute",
                "app.environments.inventory.read",
                "app.environments.deploys.read",
                "app.environments.deploys.write",
                "app.environments.templates.read",
                "app.environments.templates.write",
                "app.environments.instances.create",
                "app.environments.pool.read",
                "app.environments.pool.control",
                "app.environments.pool.tier",
                "app.environments.clusters.write",
                "app.environments.runners.read",
                "app.environments.runners.create",
                "app.environments.runners.register",
                "app.environments.clusters.delete",
                "app.environments.sandbox.read",
                "app.environments.sandbox.prepare",
                "app.environments.sandbox.restart",
                "app.environments.sandbox.terminate",
                "app.environments.terminal.authorize",
                "app.environments.terminal.interact",
                "app.environments.desktop.interact",
            ],
        },
    )
    assert install.status_code == 200, install.text
    package = root + "/memstack-environments"
    enable = await client.post(package + "/enable", headers=headers, json=scope)
    assert enable.status_code == 200, enable.text
    call = {**scope, "tool_name": "cluster_health"}
    metrics = {"total_nodes": 3, "used_cpu": 2, "total_cpu": 8, "memory_usage": 0}
    invoked = await client.post(
        package + "/invoke", headers=headers, json={**call, "payload": metrics}
    )
    assert invoked.status_code == 200, invoked.text
    assert invoked.json() == {"node_count": 3, "cpu_usage": 25, "memory_usage": 0}
    invalid = await client.post(
        package + "/invoke",
        headers=headers,
        json={
            **call,
            "payload": {**metrics, "provider_config": {}},
        },
    )
    assert invalid.status_code == 400, invalid.text
    assert "schema validation" in invalid.json()["detail"]
    patch = "--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-before\n+after\n"
    result = await client.post(
        package + "/invoke",
        headers=headers,
        json={
            **scope,
            "tool_name": "patch_text",
            "payload": {"content": "before\r\n", "patch": patch},
        },
    )
    result.raise_for_status()
    assert result.json() == {"content": "after\r\n"}

    terminal = {
        **scope,
        "command_id": "authorize-run-terminal",
        "payload": {
            "run_id": "run",
            "expected_run_revision": 1,
        },
    }
    unavailable = await client.post(package + "/commands", headers=headers, json=terminal)
    assert unavailable.status_code == 503
    app = client._transport.app
    app.state.package_operations_v1 = SANDBOX_OPERATIONS
    app.add_api_route(
        "/api/v1/projects/{project_id}/sandbox/capabilities",
        get_project_sandbox_runtime_capabilities,
        methods=["GET"],
    )
    degraded = await client.post(package + "/commands", headers=headers, json=terminal)
    assert degraded.status_code == 503
    assert "canonical_run_authority_unavailable" in degraded.json()["detail"]
    denied = await client.post(
        package + "/commands", headers={"Authorization": f"Bearer {keys['viewer']}"}, json=terminal
    )
    assert denied.status_code == 403


async def test_sandbox_patch_upgrade_and_rollback_keep_workflow_available(
    http,  # noqa: F811
    environment_release,
    signed_automation,  # noqa: F811
    monkeypatch,
):
    registry, public, current, previous = environment_release
    automation_key, automation_registry, automation, _ = signed_automation
    client, users = http
    client._transport.app.state.plugin_marketplace_trusted_public_keys_v2 = (public, automation_key)
    monkeypatch.setattr(
        get_settings(), "plugin_worker_allowed_registries", (registry, automation_registry)
    )
    scope = {"tenant_id": "t", "project_id": "p"}
    headers = {"Authorization": "Bearer " + users["owner"]}
    base = "/api/v1/platform-plugins/v2/optional-business"
    env = "/memstack-environments"
    workflow = "/memstack-automation"
    patch = "--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-before\n+after\n"

    async def post(path, **body):
        response = await client.post(base + path, headers=headers, json={**scope, **body})
        assert response.is_success, response.text
        return response.json()

    async def activate(path, archive):
        inspected = await post("/inspect", archive_base64=archive)
        await post(
            "/install", archive_base64=archive, approved_permissions=inspected["permissions"]
        )
        await post(path + "/enable")

    async def check_tools(ending):
        assert await post(
            env + "/invoke",
            tool_name="patch_text",
            payload={"content": "before\r\n", "patch": patch},
        ) == {"content": "after" + ending}
        result = await post(
            workflow + "/invoke",
            tool_name="run_schedule_workflow",
            payload={
                "steps": [
                    {
                        "kind": "at",
                        "config": {"run_at": "2026-11-02T12:00:00+00:00"},
                        "start": "2026-11-01T00:00:00+00:00",
                    }
                ]
            },
        )
        assert result == {"results": [{"next_run_at": "2026-11-02T12:00:00+00:00"}]}

    await activate(workflow, base64.b64encode(automation).decode())
    await activate(env, previous)
    await check_tools("\n")
    await activate(env, current)
    await check_tools("\r\n")
    await post(env + "/rollback")
    await check_tools("\n")
