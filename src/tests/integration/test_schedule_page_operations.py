"""Edit and dispatch persisted project schedules through the signed Automation page commands."""

import base64
import os
from pathlib import Path

import pytest

from plugins.business.automation.backend.schedule_operations import SCHEDULE_OPERATIONS
from src.configuration.config import get_settings
from src.infrastructure.plugins.v2.boundary import pin_generation_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.tests.integration import test_automation_schedule_package as automation

http = automation.http
publisher = automation.publisher
signed_automation = automation.signed_automation

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("OCI_WORKER_DOCKER_TESTS") != "1", reason="requires a disposable worker registry"
    ),
]
ROOT = Path(__file__).resolve().parents[3]


async def verify_one_shot_edit_and_delete(post, path):
    once = {
        "name": "One shot",
        "enabled": False,
        "description": "Meeting",
        "action": {"kind": "agent_turn", "text": "Summarize the meeting"},
        "conversation_mode": "fresh",
        "delivery_kind": "none",
        "max_retries": 0,
        "trigger": {"kind": "at", "run_at": "2030-01-01T08:00:00+08:00"},
        "idempotency_key": "create-once",
    }
    single = await post(path, command_id="save-schedule", payload=once)
    assert (
        single["action_text"] == "Summarize the meeting" and single["conversation_mode"] == "fresh"
    )
    assert single["schedule"]["config"]["run_at"].endswith("+08:00")
    weekly = {
        **once,
        "job_id": single["id"],
        "expected_revision": single["revision"],
        "trigger": {"kind": "cron", "expr": "0 8 * * 1", "timezone": "Asia/Shanghai"},
        "idempotency_key": "weekly-cron",
    }
    changed = await post(path, command_id="save-schedule", payload=weekly)
    assert changed["schedule"]["config"] == {
        "expr": "0 8 * * 1",
        "timezone": "Asia/Shanghai",
    }
    delete = {
        "job_id": single["id"],
        "expected_revision": changed["revision"],
        "idempotency_key": "delete-weekly",
    }
    await post(path, command_id="delete-schedule", payload=delete)
    remaining = await post(path, command_id="list-schedules", payload={})
    assert single["id"] not in {row["id"] for row in remaining["items"]}


async def test_signed_schedules_edit_and_dispatch_once_with_revision_guard(
    http, signed_automation, monkeypatch
):
    client, credentials = http
    signer, registry, raw, _ = signed_automation
    app = client._transport.app
    app.state.plugin_marketplace_trusted_public_keys_v2 = (signer,)
    app.state.package_operations_v1 = SCHEDULE_OPERATIONS
    monkeypatch.setattr(get_settings(), "plugin_worker_allowed_registries", (registry,))
    scope = {"tenant_id": "t", "project_id": "p"}
    base = "/api/v1/platform-plugins/v2/optional-business"
    headers = {"Authorization": "Bearer " + credentials["owner"]}

    async def post(path, **body):
        response = await client.post(base + path, headers=headers, json={**scope, **body})
        response.raise_for_status()
        return response.json()

    encoded = base64.b64encode(raw).decode()
    inspected = await post("/inspect", archive_base64=encoded)
    await post("/install", archive_base64=encoded, approved_permissions=inspected["permissions"])
    plugin = "/memstack-automation"
    await post(plugin + "/enable")
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    try:
        assert publication.accepted, publication.receipt
        async with pin_generation_v2(host):
            inputs = {
                "name": "Weekly sync",
                "interval_seconds": 60,
                "enabled": False,
                "idempotency_key": "create-weekly",
            }
            path = plugin + "/commands"
            saved = await post(path, command_id="save-schedule", payload=inputs)
            assert (await post(path, command_id="save-schedule", payload=inputs))["id"] == saved[
                "id"
            ]
            assert (await post(path, command_id="list-schedules", payload={}))["items"] == [saved]
            edit = {
                **inputs,
                "job_id": saved["id"],
                "expected_revision": saved["revision"],
                "interval_seconds": 300,
                "idempotency_key": "weekly-five-minutes",
            }
            updated = await post(path, command_id="save-schedule", payload=edit)
            assert updated["revision"] > saved["revision"] and updated["interval_seconds"] == 300
            await verify_one_shot_edit_and_delete(post, path)
            run = {
                "job_id": saved["id"],
                "expected_revision": updated["revision"],
                "idempotency_key": "one-manual-run",
            }
            first = await post(path, command_id="run-schedule", payload=run)
            replay = await post(path, command_id="run-schedule", payload=run)
            assert first["run_id"] == replay["run_id"] and replay["duplicate"]
            history = await post(path, command_id="list-schedules", payload={"job_id": saved["id"]})
            assert history["total"] == 1 and history["items"][0]["id"] == first["run_id"]
            stale = await client.post(
                base + path,
                headers=headers,
                json={
                    **scope,
                    "command_id": "run-schedule",
                    "payload": {
                        **run,
                        "idempotency_key": "stale",
                        "expected_revision": saved["revision"],
                    },
                },
            )
            assert stale.status_code == 409
    finally:
        await host.close()
