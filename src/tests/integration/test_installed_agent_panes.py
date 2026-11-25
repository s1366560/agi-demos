"""Run the npm-installed Agent, Workspace and Environments in one split workbench."""

import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import business_release
from src.tests.integration.test_signed_sidebar import BASE, login, qa_workspace

pytestmark = pytest.mark.integration


def _install_packages(owner):
    scope = {key: owner[key] for key in ("tenant_id", "project_id")}
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=120) as client:
        auth = client.post(
            "/auth/token", data={"username": owner["email"], "password": owner["password"]}
        )
        auth.raise_for_status()
        client.headers["Authorization"] = "Bearer " + auth.json()["access_token"]
        digests = {}
        for name in ("workspace", "environments", "agent"):
            package = "memstack-" + name
            source = {"package_name": "@memstack/" + name, "version": business_release(name)}
            detail = client.get(
                BASE + "/npm/detail", params={**scope, **source, "plugin_id": package}
            )
            detail.raise_for_status()
            detail = detail.json()
            release = detail["release"]
            digests[name] = release["digest"]
            if (detail.get("installation") or {}).get("actual_digest") == release["digest"]:
                continue
            assert detail["can_manage"]
            install = client.post(
                BASE + "/npm/apply",
                json={
                    **scope,
                    **source,
                    "expected_revision": detail["desired_revision"],
                    "expected_digest": release["digest"],
                    "approved_permissions": release["permissions"],
                },
            )
            install.raise_for_status()
        workspace = qa_workspace(client, scope, "Signed split collaboration")
        qa_workspace(client, scope, "Signed second collaboration")
        conversation = client.post(
            BASE + "/memstack-agent/commands",
            json={
                **scope,
                "expected_digest": digests["agent"],
                "command_id": "chat-create",
                "payload": {
                    "title": "Signed split chat " + uuid4().hex[:8],
                    "workspace_id": workspace,
                    "execution_target": "cloud",
                },
            },
        )
        conversation.raise_for_status()
        return digests, conversation.json()["id"]


def test_installed_agent_split_interactions():
    owner_path = os.getenv("MEMSTACK_QA_AGENT_PANES_OWNER")
    if not owner_path:
        pytest.skip("requires the isolated interactive sandbox project and local signed registry")
    account = json.loads(Path(owner_path).read_bytes())
    assert account["project_name"] == "Signed interactive sandbox QA"
    digests, conversation = _install_packages(account)
    origin = os.getenv("MEMSTACK_QA_MARKET_FULL_ORIGIN", "http://127.0.0.1:3000")
    desktop = os.getenv("MEMSTACK_QA_BUSINESS_MARKET_CDP")
    with sync_playwright() as playwright:
        path = f"/tenant/{account['tenant_id']}/agent-workspace/{conversation}?" + urlencode(
            {
                "projectId": account["project_id"],
            }
        )
        if desktop:
            browser = playwright.chromium.connect_over_cdp(desktop)
            page = browser.contexts[0].pages[0]
            project = page.locator(".package-market-scope select")
            if project.is_visible():
                project.select_option("project")
            page.evaluate("path => { location.hash = path; }", path)
            page.reload()
        else:
            browser = playwright.chromium.launch()
            page = browser.new_page(locale="en-US", viewport={"width": 1440, "height": 950})
            login(page, origin, account)
            page.goto(origin + path)
        agent = page.frame_locator(
            f'iframe[data-release-digest="{digests["agent"]}"]'
        ).frame_locator("iframe")
        draft = agent.get_by_test_id("chat-input")
        draft.fill("unsent split layout draft")
        modes = agent.locator('[data-tour="layout-selector"]')
        modes.get_by_role("button", name=re.compile("Collab|协作", re.I)).click()
        group = page.frame_locator(
            f'iframe[data-release-digest="{digests["workspace"]}"]'
        ).frame_locator("iframe")
        _drag_split(page, agent)
        message = "Signed group chat " + uuid4().hex
        _exercise_group_chat(group, message)
        expect(draft).to_have_value("unsent split layout draft")
        modes.get_by_role("button", name=re.compile("Code|代码", re.I)).click()
        expect(group.get_by_role("combobox")).to_have_count(0)
        code = page.frame_locator(
            f'iframe[data-release-digest="{digests["environments"]}"]'
        ).frame_locator("iframe")
        terminal = code.locator(".xterm-helper-textarea").first
        expect(code.get_by_text(re.compile(r"^(Terminal|终端)\s*[（(]")).first).to_be_visible(
            timeout=90000
        )
        terminal.focus()
        page.keyboard.type("printf '%d\\n' $((431*67))")
        page.keyboard.press("Enter")
        expect(code.locator(".xterm-rows")).to_contain_text("28877", timeout=60000)
        code.get_by_role("button", name=re.compile("^Remote desktop$|^远程桌面$")).click()
        expect(code.get_by_text(re.compile("^Connected$|^已连接$")).first).to_be_visible(
            timeout=120000
        )
        expect(code.locator("canvas:visible").first).to_be_visible()
        modes.get_by_role("button", name=re.compile("Collab|协作", re.I)).click()
        expect(group.get_by_text(message, exact=True)).to_be_visible()
        expect(draft).to_have_value("unsent split layout draft")

        _exercise_missing_target(page, account, agent, code)


def _exercise_missing_target(page, account, agent, code):
    draft = agent.get_by_test_id("chat-input")
    modes = agent.locator('[data-tour="layout-selector"]')
    modes.get_by_role("button", name=re.compile("Code|代码", re.I)).click()
    with _temporarily_disabled(account, "memstack-environments"):
        page.evaluate("window.dispatchEvent(new Event('focus'))")
        expect(
            page.get_by_text(re.compile("required package is unavailable|当前项目未安装"))
        ).to_be_visible(timeout=30000)
        expect(code.locator("canvas")).to_have_count(0)
        expect(draft).to_have_value("unsent split layout draft")
        turn = "Reply with the number 27. QA " + uuid4().hex[:8]
        draft.fill(turn)
        draft.press("Enter")
        expect(agent.get_by_text(turn, exact=True).first).to_be_visible(timeout=30000)
        expect(draft).to_have_value("")
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(
        code.get_by_role("button", name=re.compile("^Remote desktop$|^远程桌面$"))
    ).to_be_visible(timeout=30000)


@contextmanager
def _temporarily_disabled(account, plugin):
    scope = {key: account[key] for key in ("tenant_id", "project_id")}
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=90) as client:
        auth = client.post(
            "/auth/token", data={"username": account["email"], "password": account["password"]}
        )
        auth.raise_for_status()
        client.headers["Authorization"] = "Bearer " + auth.json()["access_token"]
        path = BASE + "/" + plugin
        state = client.get(path, params=scope)
        state.raise_for_status()
        revision = state.json()["desired_revision"]
        result = client.post(path + "/disable", json={**scope, "expected_revision": revision})
        result.raise_for_status()
        try:
            yield
        finally:
            disabled = client.get(path, params=scope)
            disabled.raise_for_status()
            assert disabled.json()["desired_revision"] == revision + 1
            enabled = client.post(
                path + "/enable",
                json={
                    **scope,
                    "expected_revision": disabled.json()["desired_revision"],
                },
            )
            enabled.raise_for_status()
            restored = client.get(path, params=scope)
            restored.raise_for_status()
            assert restored.json()["actual_digest"] == state.json()["actual_digest"]


def _drag_split(page, agent):
    slider = agent.get_by_role("slider", name=re.compile("Resize panels|调整.*面板", re.I))
    box = slider.bounding_box()
    assert box
    left = box["x"] + box["width"] / 2
    top = box["y"] + box["height"] / 2
    before = slider.get_attribute("aria-valuenow")
    page.mouse.move(left, top)
    page.mouse.down()
    page.mouse.move(left + 50, top, steps=16)
    page.mouse.up()
    expect(slider).not_to_have_attribute("aria-valuenow", before)


def _exercise_group_chat(group, message):
    expect(
        group.get_by_role("button", name="Signed split collaboration", exact=True)
    ).to_be_visible(timeout=60000)
    transcript = group.locator('[aria-live="polite"]')
    composer = group.get_by_role("combobox")
    composer.fill(message)
    composer.press("Enter")
    expect(composer).to_have_value("", timeout=30000)
    expect(transcript.get_by_text(message, exact=True)).to_be_visible()
    group.get_by_role("button", name="Signed split collaboration").click()
    group.get_by_role("option", name=re.compile("Signed second collaboration")).click()
    expect(group.get_by_role("button", name="Signed second collaboration")).to_be_visible()
    expect(transcript.get_by_text(message, exact=True)).to_have_count(0)
    group.get_by_role("button", name="Signed second collaboration").click()
    group.get_by_role("option", name=re.compile("Signed split collaboration")).click()
    expect(transcript.get_by_text(message, exact=True)).to_be_visible()
