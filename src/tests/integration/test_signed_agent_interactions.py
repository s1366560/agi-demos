"""Exercise persisted Agent events through the npm-installed full Web or Electron page."""

import asyncio
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep, time_ns
from uuid import uuid4

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import (
    apply,
    business_release,
    install_previous,
    more,
    open_market,
)
from src.tests.integration.test_signed_sidebar import qa_workspace

pytestmark = pytest.mark.integration


async def record_events(account, conversation):
    from src.domain.model.agent.execution.agent_execution_event import AgentExecutionEvent
    from src.domain.model.agent.hitl_types import HITLType
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
        engine,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
        SqlAgentExecutionEventRepository,
    )
    from src.infrastructure.agent.hitl.ray_hitl_handler import _persist_hitl_request

    stamp = datetime.now(UTC)
    message, block, call = (str(uuid4()) for _ in range(3))
    type_data = {
        "question": "Which package fixture?",
        "allow_custom": False,
        "options": [{"id": "fixture", "label": "Accept fixture"}],
    }
    await _persist_hitl_request(
        str(uuid4()),
        HITLType.CLARIFICATION,
        conversation,
        account["tenant_id"],
        account["project_id"],
        message,
        600,
        type_data,
        stamp,
    )
    await _persist_hitl_request(
        str(uuid4()),
        HITLType.A2UI_ACTION,
        conversation,
        account["tenant_id"],
        account["project_id"],
        message,
        600,
        {
            "question": "Apply fixture",
            "block_id": block,
            "surface_id": block,
            "allowed_actions": [{"source_component_id": "apply", "action_name": "accept"}],
        },
        stamp,
    )
    surface = [
        {"beginRendering": {"surfaceId": block, "root": "column"}},
        {
            "surfaceUpdate": {
                "surfaceId": block,
                "components": [
                    {
                        "id": "column",
                        "component": {"Column": {"children": {"explicitList": ["title", "apply"]}}},
                    },
                    {
                        "id": "apply",
                        "component": {"Button": {"child": "caption", "action": {"name": "accept"}}},
                    },
                    {
                        "id": "caption",
                        "component": {"Text": {"text": {"literalString": "Apply canvas action"}}},
                    },
                    {
                        "id": "title",
                        "component": {
                            "Text": {"text": {"literalString": "Rendered fixture canvas"}}
                        },
                    },
                ],
            }
        },
    ]
    entries = [
        (
            "act",
            {
                "tool_name": "fixture_lookup",
                "execution_id": call,
                "tool_input": {"fixture": "input"},
            },
        ),
        (
            "observe",
            {
                "tool_name": "fixture_lookup",
                "execution_id": call,
                "observation": "Persisted fixture output",
            },
        ),
        (
            "canvas_updated",
            {
                "action": "created",
                "block_id": block,
                "block": {
                    "id": block,
                    "block_type": "a2ui_surface",
                    "title": "Installed Agent canvas",
                    "content": "\n".join(json.dumps(row) for row in surface),
                },
            },
        ),
    ]
    async with async_session_factory() as db:
        await SqlAgentExecutionEventRepository(db).save_batch(
            [
                AgentExecutionEvent(
                    conversation_id=conversation,
                    message_id=message,
                    event_type=kind,
                    event_data=data,
                    event_time_us=time_ns() // 1000,
                    event_counter=i,
                )
                for i, (kind, data) in enumerate(entries)
            ]
        )
        await db.commit()
    await engine.dispose()


def fixture_workspace(client, account):
    workspace = qa_workspace(client, account, "Signed activity integration")
    path = f"/tenants/{account['tenant_id']}/projects/{account['project_id']}/workspaces/{workspace}/agent-policy"
    reply = client.get(path)
    reply.raise_for_status()
    policy = reply.json()
    if not policy["roles"].get("default"):
        assigned = client.get(f"/llm-providers/tenants/{account['tenant_id']}/provider")
        assigned.raise_for_status()
        provider = assigned.json()
        assert provider["is_enabled"] and provider["llm_model"]
        configured = client.patch(
            path,
            json={
                "expected_revision": policy["revision"],
                "capability_mode": "work",
                "route": {"provider_id": provider["id"], "model_id": provider["llm_model"]},
                "reasoning_effort": policy["reasoning_effort"],
                "permission_mode": policy["permission_mode"],
            },
        )
        configured.raise_for_status()
    return workspace


def create_fixture(account, version):
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=30) as client:
        auth = client.post(
            "/auth/token", data={"username": account["email"], "password": account["password"]}
        )
        auth.raise_for_status()
        client.headers["authorization"] = "Bearer " + auth.json()["access_token"]
        title = "Agent fixture " + uuid4().hex[:8]
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
        created = client.post(
            base + "/memstack-agent/commands",
            json={
                **scope,
                "expected_digest": release["digest"],
                "command_id": "chat-create",
                "payload": {
                    "title": title,
                    "workspace_id": fixture_workspace(client, account),
                    "execution_target": "cloud",
                },
            },
        )
        assert created.is_success, (created.status_code, created.json().get("detail"))
        conversation = created.json()["id"]
        origin_title = "Inbox origin " + uuid4().hex[:8]
        origin = client.post(
            base + "/memstack-agent/commands",
            json={
                **scope,
                "expected_digest": release["digest"],
                "command_id": "chat-create",
                "payload": {"title": origin_title, "execution_target": "cloud"},
            },
        )
        assert origin.is_success, (origin.status_code, origin.json().get("detail"))
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(asyncio.run, record_events(account, conversation)).result()
    return title, conversation, origin_title, origin.json()["id"]


def exercise_inbox(page, guest, title, conversation, account, cdp):
    guest.get_by_role(
        "button",
        name=re.compile(
            "Activity inbox|Open Activity and My Work|打开动态和我的工作|动态收件箱", re.I
        ),
    ).click()
    rows = guest.locator(".ant-drawer-body button").filter(has_text=title)
    expect(rows.first).to_be_visible(timeout=30000)
    all_read = guest.get_by_role(
        "button", name=re.compile("Mark all (?:as )?read|全部标为已读", re.I)
    )
    all_read.click()
    expect(all_read).to_be_disabled(timeout=30000)
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=30) as client:
        auth = client.post(
            "/auth/token", data={"username": account["email"], "password": account["password"]}
        )
        auth.raise_for_status()
        client.headers["authorization"] = "Bearer " + auth.json()["access_token"]
        work = client.get(f"/projects/{account['project_id']}/my-work")
        work.raise_for_status()
        ids = {
            item["id"] for item in work.json()["items"] if item["conversation_id"] == conversation
        }
        assert ids
        deadline = monotonic() + 15
        while True:
            read = client.get(f"/projects/{account['project_id']}/activity/read-state")
            read.raise_for_status()
            if ids <= {item["entry_id"] for item in read.json()["entries"]}:
                break
            assert monotonic() < deadline, "Fixture receipts did not persist"
            sleep(0.2)
    if cdp:
        rows.first.focus()
        rows.first.press("Enter")
    else:
        rows.first.click()
    expect(rows.first).not_to_be_visible(timeout=30000)


def reject_optional_tool_request(guest):
    deny = guest.get_by_role("button", name=re.compile("^(Deny|拒绝)$", re.I)).first
    if deny.is_visible() and deny.is_enabled():
        deny.click()


def verify_turn_and_receipts(guest, account, conversation):
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=30) as client:
        auth = client.post(
            "/auth/token", data={"username": account["email"], "password": account["password"]}
        )
        auth.raise_for_status()
        client.headers["authorization"] = "Bearer " + auth.json()["access_token"]
        deadline = monotonic() + 120
        while True:
            reject_optional_tool_request(guest)
            messages = client.get(
                f"/agent/conversations/{conversation}/messages",
                params={"project_id": account["project_id"]},
            )
            messages.raise_for_status()
            rows = messages.json()["timeline"]
            files = [f for row in rows for f in (row.get("metadata") or {}).get("fileMetadata", [])]
            if any(f.get("filename") == "interaction-check.txt" for f in files) and any(
                row["type"] == "assistant_message" and row.get("content") for row in rows
            ):
                break
            assert monotonic() < deadline, (
                "Cloud turn did not persist both the original file and an assistant reply"
            )
            sleep(1)
        while True:
            reject_optional_tool_request(guest)
            latest = client.get(f"/agent/conversations/{conversation}/latest-run")
            latest.raise_for_status()
            run = latest.json()["latest_run"]
            assert run and run["conversation_id"] == conversation
            summary = client.get(f"/agent/runs/{run['id']}/summary")
            summary.raise_for_status()
            state = summary.json()["status"]
            if state in ("cancelled", "failed"):
                history = client.get(
                    f"/agent/conversations/{conversation}/messages",
                    params={"project_id": account["project_id"]},
                )
                history.raise_for_status()
                codes = [
                    row["code"]
                    for row in history.json()["timeline"]
                    if row.get("type") == "error"
                    and re.fullmatch(r"[A-Z_]{1,64}", str(row.get("code", "")))
                ]
                pytest.fail(f"Cloud run {run['id']} ended {state}; persisted errors: {codes}")
            if state == "completed":
                pending = client.get(f"/agent/hitl/conversations/{conversation}/pending")
                pending.raise_for_status()
                assert pending.json()["requests"] == []
                return summary.json()
            assert monotonic() < deadline, "Cloud run did not persist its completed summary"
            sleep(0.5)


def exercise_page(page, title, conversation, origin_title, account, cdp):
    # A cold bookmark resolves the project and verifies the signed release before mounting chat.
    ready = page.locator('iframe[title="Agent chat"][data-page-ready=true]')
    expect(ready).to_be_visible(timeout=90000)
    guest = ready.content_frame.frame_locator("iframe")
    title_input = guest.get_by_role("textbox", name=re.compile("会话标题|Conversation title"))
    expect(title_input).to_be_visible(timeout=30000)
    expect(title_input).to_have_value(origin_title, timeout=30000)
    exercise_inbox(page, guest, title, conversation, account, cdp)
    expect(title_input).to_have_value(title, timeout=30000)
    guest.get_by_role("button", name="Apply canvas action").click()
    guest.locator("summary").filter(has_text="fixture_lookup").click()
    expect(guest.get_by_text("Persisted fixture output", exact=True)).to_be_visible()
    guest.get_by_text("Accept fixture", exact=True).click()
    guest.get_by_test_id("message-container").get_by_role(
        "button", name=re.compile(r"^(Submit|提\s*交|确\s*认|Confirm)$", re.I)
    ).click()
    expect(guest.get_by_text("Which package fixture?", exact=True)).to_have_count(0, timeout=90000)
    guest.locator("input[type=file]").set_input_files(
        {
            "name": "interaction-check.txt",
            "mimeType": "text/plain",
            "buffer": b"fixture data " * 6000,
        }
    )
    expect(guest.get_by_text("interaction-check.txt", exact=True)).to_be_visible(timeout=30000)
    draft = guest.locator("textarea").last
    draft.fill(
        "Reply with the word RECEIVED to acknowledge the filename shown in this message. "
        "Leave the attached file unopened. You do not need any tool to reply."
    )
    draft.press("Enter")
    expect(draft).to_have_value("", timeout=60000)
    transcript = guest.locator(".chat-history-viewport")
    expect(transcript.get_by_text("interaction-check.txt", exact=True)).to_be_visible(timeout=60000)
    expect(draft).to_be_enabled(timeout=180000)
    summary = verify_turn_and_receipts(guest, account, conversation)
    if cdp:
        guest.get_by_role("button", name=re.compile("Run context|运行上下文")).click()
        expect(guest.locator(".session-context-facts")).to_be_visible()
    guest.get_by_role("button", name=re.compile("Run review|运行审阅")).click()
    drawer = guest.get_by_role("dialog")
    expect(
        drawer.get_by_role("heading", name=re.compile("Completion summary|完成摘要"))
    ).to_be_visible(timeout=30000)
    expect(drawer).to_contain_text(summary["status"])
    if summary["completion_summary"]:
        expect(drawer).to_contain_text(summary["completion_summary"])
    drawer.get_by_role("button", name=re.compile("^turn$|^当前轮次$", re.I)).click()
    expect(drawer.get_by_role("heading", name=re.compile("^Changes$|^变更$"))).to_be_visible(
        timeout=30000
    )
    drawer.get_by_role("button", name=re.compile("close|关闭", re.I)).first.click()


def test_installed_agent_interactions():
    owner = os.getenv("MEMSTACK_QA_INTERACTION_OWNER")
    if not owner:
        pytest.skip("requires isolated local marketplace credentials")
    account = json.loads(Path(owner).read_bytes())
    version = os.getenv("MEMSTACK_QA_INTERACTION_VERSION", business_release("agent"))
    cdp = os.getenv("MEMSTACK_QA_BUSINESS_MARKET_CDP")
    origin = os.getenv("MEMSTACK_QA_MARKET_FULL_ORIGIN", "http://localhost:3000")
    with sync_playwright() as pw:
        if cdp:
            browser = pw.chromium.connect_over_cdp(cdp)
            page = browser.contexts[0].pages[0]
            if page.get_by_role(
                "button", name=re.compile("返回插件市场|Back to marketplace")
            ).count():
                page.get_by_role(
                    "button", name=re.compile("返回插件市场|Back to marketplace")
                ).click()
            page.locator(".package-market-scope select").select_option("project")
            if page.locator(".pm-back").is_visible():
                page.locator(".pm-back").click()
        else:
            browser = pw.chromium.launch()
            page = browser.new_page(locale="en-US")
            open_market(page, "full", origin, account)
        page.locator(".pm-spec, #pm-card-memstack-agent").first.wait_for(
            state="visible", timeout=60000
        )
        if not page.locator(".pm-spec").is_visible():
            page.locator("#pm-card-memstack-agent").click()
        installed = page.locator(".pm-spec dd").first
        install_previous(page, "1.3.1")
        apply(page, version)
        title, conversation, origin_title, origin_id = create_fixture(account, version)
        page.locator(".pm-page-list").get_by_role("button", name="Agent chat", exact=True).click()
        if cdp:
            page.evaluate(
                "path => { location.hash = path; }",
                f"/tenant/{account['tenant_id']}/agent-workspace/{origin_id}",
            )
            page.reload()
        else:
            # Conversation navigation belongs to the workbench shell. Exercise the original
            # bookmark, including a full-document reload, before opening a second chat via Inbox.
            page.goto(
                f"{origin}/tenant/{account['tenant_id']}/agent-workspace/{origin_id}"
                f"?projectId={account['project_id']}"
            )
            page.reload()
        exercise_page(page, title, conversation, origin_title, account, cdp)
        if cdp:
            page.evaluate(
                "path => { location.hash = path; }", f"/tenant/{account['tenant_id']}/plugins"
            )
        else:
            page.goto(
                origin
                + "/tenant/"
                + account["tenant_id"]
                + "/plugins?projectId="
                + account["project_id"]
            )
        page.locator(".pm-spec, #pm-card-memstack-agent").first.wait_for(
            state="visible", timeout=60000
        )
        if not page.locator(".pm-spec").is_visible():
            page.locator("#pm-card-memstack-agent").click()
        more(page, "Roll back to|回退至")
        expect(installed).to_have_text("1.3.1", timeout=30000)
        apply(page, version)
        if cdp and version == business_release("agent"):
            page.locator(".desktop-design-new-task").click()
            guest = page.frame_locator("iframe[data-page-ready=true]").first.frame_locator("iframe")
            expect(guest.get_by_test_id("chat-input")).to_be_visible(timeout=30000)
