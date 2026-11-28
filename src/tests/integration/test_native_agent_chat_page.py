"""Run the signed Agent chat through the real Electron project marketplace."""

import os
import re
from uuid import uuid4

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import apply, more


@pytest.mark.integration
def test_native_agent_chat_upgrade_and_rollback() -> None:
    cdp = os.getenv("MEMSTACK_QA_BUSINESS_MARKET_CDP")
    if not cdp:
        pytest.skip("requires an isolated Electron project marketplace")
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp)
        page = browser.contexts[0].pages[0]
        if not page.locator(".package-market-scope select").count():
            page.get_by_role("button", name=re.compile("返回插件市场|Back to marketplace")).click()
        page.locator(".package-market-scope select").select_option("project")
        if page.locator(".pm-back").is_visible():
            page.locator(".pm-back").click()
        page.locator("#pm-card-memstack-agent").click()
        installed = page.locator(".pm-spec dd").first
        if installed.inner_text() != "1.2.0":
            apply(page, "1.2.0")
        apply(page, "1.3.1")
        page.locator(".pm-page-list").get_by_role("button", name="Agent chat", exact=True).click()
        frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        expect(frame.locator(".session-chat-narrative")).to_be_visible(timeout=25000)
        frame.get_by_role("button", name=re.compile("搜索会话|Search conversation")).click()
        frame.get_by_role("searchbox").fill(str(uuid4()))
        expect(frame.get_by_role("search")).to_contain_text(re.compile("0 个结果|0 results"))
        frame.get_by_role("button", name=re.compile("关闭搜索|Close search")).click()
        frame.get_by_role("combobox").click()
        frame.get_by_role("option", name=re.compile("Cloud|云端")).click()
        frame.locator(".agent-session-creation").get_by_role("button").click()
        title = frame.get_by_role("textbox", name=re.compile("会话标题|Conversation title"))
        expect(title).to_have_value(re.compile("新会话|New conversation"), timeout=30000)
        updated = "QA Agent " + uuid4().hex[:8]
        title.fill(updated)
        title.press("Enter")
        expect(frame.locator("aside").get_by_role("button", name=updated)).to_be_visible(
            timeout=30000
        )
        page.go_back()
        expect(installed).to_have_text("1.3.1", timeout=20000)
        more(page, "Roll back to|回退至")
        expect(installed).to_have_text("1.2.0", timeout=30000)
        page.locator(".pm-page-list").get_by_role("button", name="Agent chat", exact=True).click()
        expect(frame.locator(".agent-transcript")).to_be_visible(timeout=25000)
        expect(frame.locator(".session-chat-narrative")).to_have_count(0)
