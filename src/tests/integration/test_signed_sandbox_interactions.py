"""Exercise a release-scoped PTY and KasmVNC viewer through the installed marketplace page."""

import json
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import (
    apply,
    business_release,
    install_previous,
    more,
    open_market,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_INTERACTIVE_SANDBOX_OWNER"),
        reason="requires an isolated local development project with a sandbox",
    ),
]


def _exercise_viewer(page, owner):
    frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
    selector = frame.locator(".xterm-helper-textarea").first
    expect(selector).to_have_count(1, timeout=90000)
    expect(frame.get_by_text(re.compile(r"^(Terminal|终端)\s*[（(]")).first).to_be_visible(
        timeout=90000
    )
    assert (
        frame.locator("html").evaluate("async ()=> (await memstack.scope()).projectId")
        == owner["project_id"]
    )
    selector.focus()
    page.keyboard.type("printf '%d\\n' $((357*439))")
    page.keyboard.press("Enter")
    expect(frame.locator(".xterm-rows")).to_contain_text("156723", timeout=60000)
    frame.get_by_role("button", name=re.compile("^Remote desktop$|^远程桌面$")).click()
    expect(frame.get_by_text(re.compile("^Connected$|^已连接$")).first).to_be_visible(
        timeout=120000
    )
    canvas = frame.locator("canvas:visible").first
    expect(canvas).to_be_visible(timeout=30000)
    canvas.click(position={"x": 60, "y": 60})


@pytest.mark.parametrize("client", ["web", "electron"])
def test_installed_terminal_and_remote_desktop(client):
    owner = json.loads(Path(os.environ["MEMSTACK_INTERACTIVE_SANDBOX_OWNER"]).read_bytes())
    assert owner["project_name"] == "Signed interactive sandbox QA"
    native = client == "electron"
    if native and not os.getenv("MEMSTACK_INTERACTIVE_SANDBOX_CDP"):
        pytest.skip("requires a canonical native Electron QA window")
    with sync_playwright() as pw:
        if native:
            page = (
                pw.chromium.connect_over_cdp(os.environ["MEMSTACK_INTERACTIVE_SANDBOX_CDP"])
                .contexts[0]
                .pages[0]
            )
        else:
            page = pw.chromium.launch().new_page(locale="en-US")
            open_market(
                page,
                "full",
                os.getenv("MEMSTACK_QA_MARKET_FULL_ORIGIN", "http://127.0.0.1:3000"),
                owner,
            )
        page.set_default_timeout(60000)

        def details(*, returning=False):
            if returning:
                page.get_by_text(
                    re.compile(r"^(返回插件市场|Back to (plugin )?marketplace)$")
                ).click()
                detail = page.locator(".pm-spec")
                card = page.locator("#pm-card-memstack-environments")
                detail.or_(card).first.wait_for(timeout=60000)
                if detail.is_visible():
                    return
            elif native:
                dashboard = page.get_by_role("button", name=re.compile("全部功能|All features"))
                login = page.locator("input[type=email]:enabled")
                dashboard.or_(login).first.wait_for(timeout=60000)
                if login.is_visible():
                    url = page.locator("input[type=url]")
                    if url.input_value() != "http://127.0.0.1:8000":
                        url.fill("http://127.0.0.1:8000")
                    login.fill(owner["email"])
                    page.locator("input[type=password]").fill(owner["password"])
                    page.locator("button[type=submit]").click()
                expect(
                    page.get_by_role("button", name=re.compile("Native marketplace QA"))
                ).to_contain_text(owner["project_name"], timeout=60000)
                page.get_by_role("button", name=re.compile("全部功能|All features")).click()
                page.locator('[role="dialog"] button').filter(
                    has_text=re.compile("插件|Plugins")
                ).first.click()
            page.locator("#pm-card-memstack-environments").click()
            expect(page.locator(".pm-spec")).to_be_visible(timeout=60000)

        def entry():
            return page.locator(".pm-page-list").get_by_role(
                "button", name="Terminal and remote desktop", exact=True
            )

        current = os.getenv(
            "MEMSTACK_INTERACTIVE_SANDBOX_VERSION", business_release("environments")
        )
        details()
        install_previous(page, "1.4.0")
        expect(entry()).to_have_count(0)
        apply(page, current)
        entry().click()
        _exercise_viewer(page, owner)
        details(returning=True)
        more(page, "Roll back to|回退至")
        expect(page.locator(".pm-spec dd").first).to_have_text("1.4.0", timeout=60000)
        expect(entry()).to_have_count(0)
        apply(page, current)
        expect(entry()).to_be_visible()
