"""Exercise conversation ownership across two npm releases on the full Web host."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import apply, more, open_market

pytestmark = pytest.mark.integration


def test_signed_agent_rename_survives_downgrade():
    """Use an explicitly selected loopback QA project, keeping its conversation for replay."""
    owner = os.getenv("MEMSTACK_QA_AGENT_MARKET_OWNER")
    if not owner:
        pytest.skip("requires a disposable full-host project and both published Agent releases")
    origin = os.getenv("MEMSTACK_QA_AGENT_MARKET_ORIGIN", "http://127.0.0.1:3000")
    assert urlsplit(origin).hostname in {"127.0.0.1", "localhost", "::1"}
    title = "Agent QA " + uuid4().hex[:10]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        open_market(page, "full", origin, json.loads(Path(owner).read_bytes()))
        market = page.url

        def details():
            page.goto(market)
            page.locator("#pm-card-memstack-agent").click()

        def chat():
            page.locator(".pm-detail-actions").get_by_role(
                "button", name=re.compile("^(Open feature|打开功能)$")
            ).click()
            guest = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
            expect(
                guest.get_by_role("heading", name=re.compile("Agent chat|智能体对话"))
            ).to_be_visible()
            return guest

        details()
        current = page.locator(".pm-spec dd").first
        expect(current).to_be_visible()
        if current.inner_text() != "1.0.4":
            apply(page, "1.0.4")
        rename = re.compile("^(Rename conversation|重命名会话)$")
        expect(chat().get_by_role("button", name=rename)).to_have_count(0)
        details()
        apply(page, "1.1.0")
        guest = chat()
        guest.get_by_role("button", name=re.compile("^(New conversation|新会话)$")).click()
        guest.get_by_role("textbox", name=re.compile("Conversation title|会话标题")).fill(title)
        guest.get_by_role("button", name=rename).click()
        expect(guest.locator("select").first.locator("option:checked")).to_have_text(title)
        details()
        more(page, "Roll back to|回退至")
        expect(current).to_have_text("1.0.4", timeout=45000)
        guest = chat()
        expect(guest.get_by_role("button", name=rename)).to_have_count(0)
        expect(guest.locator("select").first).to_contain_text(title)
        browser.close()
