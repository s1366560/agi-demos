"""Install the Automation package and compare its preview with the production trigger."""

import base64
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from plugins.business.automation.triggers import build_trigger
from src.configuration.config import get_settings
from src.tests.integration.test_oci_mcp_worker_docker import disposable_worker_registry
from src.tests.unit.routers import test_optional_business_http_v2 as package_api

http = package_api.http
publisher = package_api.publisher
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("OCI_WORKER_DOCKER_TESTS") != "1", reason="requires Docker"),
]


@pytest.fixture(scope="module")
def signed_automation(tmp_path_factory):
    from memstack_plugin_sdk.pack import build, stage_contribution

    package = Path(__file__).resolve().parents[3] / "plugins/business/automation"
    directory = tmp_path_factory.mktemp("automation-publisher")
    stage_contribution(package, directory)
    metadata = json.loads((package / "package.json").read_text())
    key = Ed25519PrivateKey.generate()

    def archive(version, image):
        spec = directory / "package.json"
        spec.write_text(json.dumps({**metadata, "version": version}))
        (directory / "worker.json").write_text(
            json.dumps(
                {
                    "schema": "memstack.mcp-oci-worker/1",
                    "image": image,
                    "entrypoint": "/app/schedule-worker",
                }
            )
        )
        return build(spec, key)

    with disposable_worker_registry() as (publish, registry, _):
        current = publish(package)
        second = tmp_path_factory.mktemp("automation-next-interval")
        for item in (
            "Dockerfile",
            ".dockerignore",
            "contributions.json",
            "triggers.py",
            "worker.py",
        ):
            shutil.copyfile(package / item, second / item)
        shutil.copytree(
            package / "workflow", second / "workflow", ignore=shutil.ignore_patterns("__pycache__")
        )
        # A second publisher revision schedules periodic work strictly after start.
        # The MCP worker, workflow engine and public inputs are identical.
        with (second / "triggers.py").open("a") as trigger_module:
            trigger_module.write("""

_inclusive_trigger = build_trigger

def build_trigger(kind, config, *, timezone="UTC", start=None):
    trigger = _inclusive_trigger(kind, config, timezone=timezone, start=start)
    if kind == "every" and start is not None:
        trigger.next()
    return trigger
""")
        upgraded = publish(second)
        assert current.split("@")[1] != upgraded.split("@")[1]
        yield (
            key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode(),
            registry,
            archive("1.0.0", current),
            archive("2.0.0", upgraded),
        )


async def test_authorized_preview_uses_production_trigger(http, signed_automation, monkeypatch):
    client, credentials = http
    public, registry, raw, _ = signed_automation
    client._transport.app.state.plugin_marketplace_trusted_public_keys_v2 = (public,)
    monkeypatch.setattr(get_settings(), "plugin_worker_allowed_registries", (registry,))
    base = "/api/v1/platform-plugins/v2/optional-business"
    package = base + "/memstack-automation"
    headers = {"Authorization": "Bearer " + credentials["owner"]}
    scope = {"tenant_id": "t", "project_id": "p"}
    installed = await client.post(
        base + "/install",
        headers=headers,
        json={
            **scope,
            "approved_permissions": ["ui.slot", "tools.execute", "app.automation.playbooks.read"],
            "archive_base64": base64.b64encode(raw).decode(),
        },
    )
    installed.raise_for_status()
    (await client.post(package + "/enable", headers=headers, json=scope)).raise_for_status()
    start = datetime.fromisoformat("2026-11-01T00:00:00+00:00")
    steps, expected = [], []
    for kind, config in (
        ("cron", {"expr": "0 9 * * *", "timezone": "Asia/Shanghai"}),
        ("every", {"interval_seconds": 60}),
        ("at", {"run_at": "2026-11-02T12:00:00+00:00"}),
    ):
        next_time = build_trigger(kind, config, start=start).next()
        assert next_time is not None
        result = await client.post(
            package + "/invoke",
            headers=headers,
            json={
                **scope,
                "tool_name": "next_scheduled_run",
                "payload": {"kind": kind, "config": config, "start": start.isoformat()},
            },
        )
        assert result.is_success, result.text
        assert result.json() == {"next_run_at": next_time.isoformat()}
        steps.append({"kind": kind, "config": config, "start": start.isoformat()})
        expected.append(result.json())
    workflow = await client.post(
        package + "/invoke",
        headers=headers,
        json={**scope, "tool_name": "run_schedule_workflow", "payload": {"steps": steps}},
    )
    workflow.raise_for_status()
    assert workflow.json() == {"results": expected}


async def test_workflow_upgrade_and_rollback_restore_schedule_semantics(
    http, signed_automation, monkeypatch
):
    client, credentials = http
    key, registry, current, upgraded = signed_automation
    client._transport.app.state.plugin_marketplace_trusted_public_keys_v2 = (key,)
    monkeypatch.setattr(get_settings(), "plugin_worker_allowed_registries", (registry,))
    base = "/api/v1/platform-plugins/v2/optional-business"
    path = "/memstack-automation"
    scope = {"tenant_id": "t", "project_id": "p"}
    headers = {"Authorization": "Bearer " + credentials["owner"]}

    async def post(endpoint, **body):
        response = await client.post(base + endpoint, headers=headers, json={**scope, **body})
        assert response.is_success, response.text
        return response.json()

    async def activate(raw):
        await post(
            "/install",
            archive_base64=base64.b64encode(raw).decode(),
            approved_permissions=["ui.slot", "tools.execute", "app.automation.playbooks.read"],
        )
        await post(path + "/enable")

    async def check_schedule(version, next_interval):
        state = await client.get(base + path, headers=headers, params=scope)
        state.raise_for_status()
        assert state.json()["running_version"] == version
        start = "2026-11-01T00:00:00+00:00"
        date = "2026-11-02T12:00:00+00:00"
        result = await post(
            path + "/invoke",
            tool_name="run_schedule_workflow",
            payload={
                "steps": [
                    {"kind": "every", "config": {"interval_seconds": 60}, "start": start},
                    {"kind": "at", "config": {"run_at": date}, "start": start},
                ]
            },
        )
        assert result == {"results": [{"next_run_at": next_interval}, {"next_run_at": date}]}

    await activate(current)
    await check_schedule("1.0.0", "2026-11-01T00:00:00+00:00")
    await activate(upgraded)
    await check_schedule("2.0.0", "2026-11-01T00:01:00+00:00")
    await post(path + "/rollback")
    await check_schedule("1.0.0", "2026-11-01T00:00:00+00:00")
