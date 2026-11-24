"""Exercise persisted Agent events through the npm-installed full Web or Electron page."""

import asyncio
import json
import os
import re
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


def create_fixture(account):
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=30) as client:
        auth = client.post(
            "/auth/token", data={"username": account["email"], "password": account["password"]}
        )
        auth.raise_for_status()
        client.headers["authorization"] = "Bearer " + auth.json()["access_token"]
        title = "Agent fixture " + uuid4().hex[:8]
        created = client.post(
            "/agent/conversations", json={"title": title, "project_id": account["project_id"]}
        )
        created.raise_for_status()
        conversation = created.json()["id"]
    asyncio.run(record_events(account, conversation))
    return title, conversation


def exercise_page(page, title, conversation, account, cdp):
    guest = page.frame_locator("iframe[data-page-ready=true]").first.frame_locator("iframe")
    title_input = guest.get_by_role("textbox", name=re.compile("会话标题|Conversation title"))
    expect(title_input).to_be_visible(timeout=30000)
    if title_input.input_value() != title:
        guest.locator("aside").get_by_text(title, exact=True).click()
    expect(guest.get_by_text("Rendered fixture canvas", exact=True)).to_be_visible(timeout=30000)
    guest.get_by_role("button", name="Apply canvas action").click()
    guest.locator("summary").filter(has_text="fixture_lookup").click()
    expect(guest.get_by_text("Persisted fixture output", exact=True)).to_be_visible()
    guest.get_by_text("Accept fixture", exact=True).click()
    if not cdp:
        guest.get_by_role("button", name=re.compile("Submit|提交|确认|Confirm", re.I)).last.click()
    expect(guest.get_by_text("Which package fixture?", exact=True)).to_have_count(0, timeout=20000)
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
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=30) as client:
        auth = client.post(
            "/auth/token", data={"username": account["email"], "password": account["password"]}
        )
        auth.raise_for_status()
        client.headers["authorization"] = "Bearer " + auth.json()["access_token"]
        requests = client.get(f"/agent/hitl/conversations/{conversation}/pending")
        requests.raise_for_status()
        assert requests.json()["requests"] == []
        deadline = monotonic() + 120
        while True:
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


def test_installed_agent_interactions():
    owner = os.getenv("MEMSTACK_QA_INTERACTION_OWNER")
    if not owner:
        pytest.skip("requires isolated local marketplace credentials")
    account = json.loads(Path(owner).read_bytes())
    title, conversation = create_fixture(account)
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
        page.locator(".pm-page-list").get_by_role("button", name="Agent chat", exact=True).click()
        exercise_page(page, title, conversation, account, cdp)
        if cdp:
            page.get_by_role("button", name=re.compile("返回插件市场|Back to marketplace")).click()
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
