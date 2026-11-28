"""Send or cancel one real model turn in an isolated Electron marketplace project."""

import os
import re
from uuid import uuid4

import pytest
from playwright.sync_api import Page, expect, sync_playwright


def _open_agent(page: Page):
    marketplace = page.get_by_role("button", name=re.compile("返回插件市场|Back to marketplace"))
    if marketplace.is_visible():
        marketplace.click()
    page.locator(".package-market-scope select").select_option("project")
    card = page.locator("#pm-card-memstack-agent")
    back = page.locator(".pm-back")
    back.or_(card).first.wait_for()
    if back.is_visible():
        back.click()
    card.click()
    page.locator(".pm-page-list").get_by_role("button", name="Agent chat", exact=True).click()
    return page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")


@pytest.mark.integration
@pytest.mark.parametrize("cancel", [False, True], ids=["reply", "stop"])
def test_live_native_cloud_turn(cancel: bool) -> None:
    # Opt in explicitly because this test invokes a configured model for a real project.
    cdp = os.environ.get("MEMSTACK_QA_AGENT_MODEL_CDP")
    if not cdp:
        pytest.skip(
            "requires an isolated Electron project with the Agent package and a cloud model"
        )
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp)
        page = browser.contexts[0].pages[0]
        page.set_default_timeout(45000)
        guest = _open_agent(page)
        guest.get_by_role("combobox").click()
        guest.get_by_role("option", name=re.compile("云端|Cloud")).click()
        guest.locator(".agent-session-creation button[aria-label]").last.click()
        title = guest.get_by_role("textbox", name=re.compile("会话标题|Conversation title"))
        expect(title).to_have_value(re.compile("新会话|New conversation"), timeout=30000)
        name = "QA cloud turn " + uuid4().hex[:10]
        title.fill(name)
        title.press("Enter")
        expect(guest.get_by_role("button", name=name, exact=True)).to_be_visible(timeout=30000)

        expected = "MEMSTACK_STREAM_" + uuid4().hex[:10].upper()
        prompt = (
            "Outline five ways to plan a workshop." if cancel else f"Reply with exactly {expected}."
        )
        draft = guest.locator("textarea")
        draft.fill(prompt)
        submit = guest.get_by_role("button", name=re.compile("发送消息|Send message"))
        submit.click()
        if cancel:
            guest.get_by_role("button", name=re.compile("^停止$|^Stop$")).click(timeout=60000)
        else:
            expect(guest.locator("article.agent .transcript-content").last).to_have_text(
                expected, timeout=150000
            )
        # Returning to an editable, idle composer distinguishes a terminal event from a text delta.
        expect(draft).to_have_value("", timeout=60000)
        draft.fill("unsent")
        expect(submit).to_be_enabled(timeout=90000)
        expect(guest.get_by_role("alert")).to_have_count(0)
        draft.fill("")
