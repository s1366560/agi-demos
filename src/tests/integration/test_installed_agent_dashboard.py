"""Verify the installed tenant dashboard against persisted QA traces on a fixed client."""

import asyncio
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import apply, business_release, open_market
from src.tests.integration.test_fixed_workbench_market import _details, _native, _open

pytestmark = pytest.mark.integration


async def record_trace(conversation: str, label: str, trace: str) -> None:
    from src.infrastructure.agent.subagent.async_run_registry_v2 import registry_call_v2
    from src.infrastructure.agent.subagent.production_run_registry_v2 import (
        production_subagent_run_registry_v2,
    )

    registry = production_subagent_run_registry_v2()
    parent = None
    for suffix in ("parent", "child"):
        run = await registry_call_v2(
            registry, "create_run", conversation, label + suffix, "Fixture " + suffix
        )
        await registry_call_v2(
            registry, "set_trace_context", conversation, run.run_id, trace, parent_span_id=parent
        )
        await registry_call_v2(registry, "mark_running", conversation, run.run_id)
        await registry_call_v2(
            registry, "mark_completed", conversation, run.run_id, summary="QA " + suffix
        )
        parent = run.run_id


def seed(account, version):
    label = "Dashboard QA " + uuid4().hex[:8] + " "
    trace = str(uuid4())
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=30) as client:
        login = client.post(
            "/auth/token", data={"username": account["email"], "password": account["password"]}
        )
        login.raise_for_status()
        client.headers["authorization"] = "Bearer " + login.json()["access_token"]
        scope = {key: account[key] for key in ("tenant_id", "project_id")}
        base = "/platform-plugins/v2/optional-business"
        info = client.get(
            base + "/npm/detail",
            params={
                **scope,
                "plugin_id": "memstack-agent",
                "package_name": "@memstack/agent",
                "version": version,
            },
        )
        info.raise_for_status()
        release = info.json()["release"]
        assert not {p for p in release["permissions"] if p.startswith("app.agent.dashboard.")}
        command = {**scope, "expected_digest": release["digest"]}
        denied = client.post(
            base + "/memstack-agent/commands",
            json={**command, "command_id": "dashboard-read", "payload": {"view": "runs"}},
        )
        assert denied.status_code == 403
        created = client.post(
            base + "/memstack-agent/commands",
            json={
                **command,
                "command_id": "chat-create",
                "payload": {"title": label, "execution_target": "cloud"},
            },
        )
        created.raise_for_status()
        conversation = created.json()["id"]
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(asyncio.run, record_trace(conversation, label, trace)).result()
        canonical = client.get(f"/agent/trace/runs/{conversation}/trace/{trace}")
        canonical.raise_for_status()
        assert canonical.json()["total"] == 2
        config = client.get("/agent/config", params={"tenant_id": account["tenant_id"]})
        config.raise_for_status()
        return label, config.json()["llm_model"]


def test_installed_tenant_agent_dashboard(monkeypatch):
    path = os.getenv("MEMSTACK_QA_INTERACTION_OWNER")
    if not path:
        pytest.skip("Dedicated fixed-host Agent QA account required")
    owner = json.loads(Path(path).read_bytes())
    version = business_release("agent")
    origin = os.environ["MEMSTACK_QA_VERTICAL_ORIGIN"]
    assert urlsplit(origin).hostname in ("localhost", "127.0.0.1", "::1")
    label, model = seed(owner, version)
    tenant = owner["tenant_id"]
    monkeypatch.setenv("MEMSTACK_QA_EXPECT_MARKET_SCOPE", tenant)
    cdp = os.getenv("MEMSTACK_QA_BUSINESS_MARKET_CDP")
    with sync_playwright() as pw:
        if cdp:
            page = _native(pw, owner, "tenant")
        else:
            page = pw.chromium.launch().new_page(locale="en-US")
            open_market(page, "full", origin, owner)
            page.goto(f"{origin}/tenant/{tenant}/plugins")
        active = _details(page, "agent")
        if active.inner_text() != version:
            apply(page, version)
        if cdp:
            guest = _open(page, "Multi-agent dashboard")
        else:
            page.goto(f"{origin}/tenant/{tenant}/agents")
            page.reload()
            guest = page.frame_locator("iframe[data-page-ready=true]").first.frame_locator("iframe")
        expect(guest.get_by_text(model, exact=True).first).to_be_visible(timeout=60000)
        candidate = guest.get_by_text(label + "parent", exact=True)
        if not candidate.is_visible():
            guest.get_by_role("button", name=re.compile("trace|追踪|执行轨迹", re.I)).first.click()
        candidate.first.click()
        selected = guest.locator("button:has(svg.lucide-arrow-right)").filter(
            has_text=label + "child"
        )
        expect(selected.get_by_text("QA child", exact=True)).to_be_visible(timeout=30000)
        verify_config_revision(owner, version)


def verify_config_revision(owner, version):
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=30) as client:
        login = client.post(
            "/auth/token", data={"username": owner["email"], "password": owner["password"]}
        )
        login.raise_for_status()
        client.headers["authorization"] = "Bearer " + login.json()["access_token"]
        tenant = {"tenant_id": owner["tenant_id"]}
        details = client.get(
            "/tenant-packages/npm/detail",
            params={
                **tenant,
                "plugin_id": "memstack-agent",
                "package_name": "@memstack/agent",
                "version": version,
            },
        )
        details.raise_for_status()
        release = details.json()["release"]
        assert set(release["permissions"]) == {
            "ui.slot",
            "app.agent.dashboard.read",
            "app.agent.dashboard.trace",
            "app.agent.dashboard.configure",
        }

        def invoke(cmd, payload):
            response = client.post(
                "/tenant-packages/memstack-agent/commands",
                json={
                    **tenant,
                    "expected_digest": release["digest"],
                    "command_id": cmd,
                    "payload": payload,
                },
            )
            response.raise_for_status()
            return response.json()

        before = invoke("dashboard-read", {"view": "config"})
        request = {
            "expected_revision": before["authority_revision"],
            "config": {"llm_temperature": before["llm_temperature"]},
        }
        saved = invoke("dashboard-configure", request)
        assert saved["status"] == 200
        assert saved["config"]["authority_revision"] == before["authority_revision"] + 1
        assert invoke("dashboard-configure", request) == {"status": 409}
        actual = client.get("/agent/config", params=tenant)
        actual.raise_for_status()
        assert actual.json() == saved["config"]
