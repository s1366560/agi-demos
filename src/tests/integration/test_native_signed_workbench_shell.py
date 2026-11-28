"""Exercise the native workbench chrome around an installed signed page."""

import os
import re

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_QA_SIGNED_WORKBENCH_CDP"),
        reason="requires a signed-in full Electron QA session with Automation installed",
    ),
]


def test_settings_market_opens_signed_page_in_the_original_workbench() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            os.environ["MEMSTACK_QA_SIGNED_WORKBENCH_CDP"]
        )
        page = browser.contexts[0].pages[0]
        page.set_default_timeout(30000)
        directory = page.get_by_role(
            "button", name=re.compile("全部功能|Feature directory|All features", re.I)
        )
        directory.click()
        page.locator("[role=dialog] button").filter(
            has_text=re.compile("插件|Plugins", re.I)
        ).first.click()
        page.locator("#pm-card-memstack-automation").click()
        workbench = page.locator(".app-shell .workbench main.desktop-package-workbench")
        expect(workbench).to_be_visible()
        expect(page.locator(".settings-window-dialog")).to_have_count(0)
        workbench.locator(".pm-page-list").get_by_role(
            "button", name="Project schedules", exact=True
        ).click()
        frame = workbench.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        expect(frame.get_by_role("heading", name=re.compile("Scheduled Tasks|定时任务"))).to_be_visible(timeout=30000)

        toggle = page.locator(".desktop-titlebar-button").first
        original = toggle.get_attribute("aria-pressed")
        toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", "false" if original == "true" else "true")
        toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", original)
        page.locator(".desktop-design-profile").click()
        page.get_by_role(
            "menuitem", name=re.compile("账户设置|帐号设置|账号设置|Account settings", re.I)
        ).click()
        expect(page.locator(".settings-window-dialog")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.locator(".settings-window-dialog")).to_have_count(0)
        page.locator(".desktop-design-brand").click()
        expect(page).not_to_have_url(re.compile(r"marketPage="))
        expect(page.locator(".desktop-titlebar")).to_be_visible()
