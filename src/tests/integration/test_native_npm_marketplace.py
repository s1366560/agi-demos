"""Native marketplace lifecycle against a published test package in a disposable project."""

import os
import re

import pytest
from playwright.sync_api import Page, expect, sync_playwright

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.getenv("MEMSTACK_QA_MARKET_CDP") and os.getenv("MEMSTACK_QA_MARKET_PLUGIN")),
        reason="requires the signed two-release inventory fixture and a disposable native project",
    ),
]


def apply(page: Page, version: str) -> None:
    page.locator(".pm-spec select").select_option(version)
    actions = page.locator(".pm-detail-actions")
    action = actions.get_by_role(
        "button", name=re.compile("^(Install|安装|Update to|更新至|切换版本|Switch version)")
    )
    action.click()
    dialog = page.locator("dialog.pm-dialog")
    expect(dialog).to_contain_text(version)
    dialog.locator(".pm-actions button").last.click()
    expect(page.locator(".pm-spec dd").first).to_have_text(version, timeout=30000)


def approve_device(page: Page) -> None:
    device = page.locator(".pm-detail-main .local-plugin-settings")
    ready = device.get_by_text(re.compile("^(设备授权有效|Device authorization active)$"))
    if ready.is_visible():
        return
    device.get_by_role("button", name=re.compile("审阅此版本|Review this release")).click()
    device.get_by_role("checkbox").check()
    device.get_by_role("button", name=re.compile("批准并安装|Approve and install")).click()
    expect(ready).to_be_visible(timeout=25000)


def run_labels(page: Page, version: int) -> None:
    page.locator(".pm-detail-actions").get_by_role(
        "button", name=re.compile("^(打开功能|Open feature)$")
    ).click()
    frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
    expect(frame.get_by_role("heading", name=f"Inventory labels {version}")).to_be_visible(
        timeout=25000
    )
    for index, (button, target) in enumerate((("Cloud", "python"), ("Device", "desktop-sidecar"))):
        frame.get_by_role("button", name=f"{button} label").click()
        expect(frame.locator("output").nth(index)).to_contain_text(
            f"{target}-{version}", timeout=15000
        )
    page.go_back()
    expect(page.locator(".pm-spec")).to_be_visible(timeout=15000)


def more(page: Page, action: str) -> None:
    menu = page.locator(".pm-detail-actions details")
    menu.locator("summary").click()
    menu.get_by_role("button", name=re.compile(action)).click()
    page.locator("dialog.pm-dialog .pm-actions button").last.click()


def test_native_project_marketplace_lifecycle() -> None:
    """Start in the signed-in project's market with neither fixture version installed."""
    plugin = os.environ["MEMSTACK_QA_MARKET_PLUGIN"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(os.environ["MEMSTACK_QA_MARKET_CDP"])
        page = browser.contexts[0].pages[0]
        page.set_default_timeout(15000)
        page.locator(".pm-search input").fill(plugin)
        page.locator("[id='pm-card-" + plugin + "']").click()
        expect(page.locator(".pm-spec dd").first).to_have_text(re.compile("未运行|Inactive"))
        apply(page, "1.1.0")
        approve_device(page)
        run_labels(page, 1)
        apply(page, "1.2.0")
        approve_device(page)
        run_labels(page, 2)
        more(page, "回退|回滚|Roll back")
        expect(page.locator(".pm-spec dd").first).to_have_text("1.1.0")
        approve_device(page)
        run_labels(page, 1)
        more(page, "卸载|Uninstall")
        expect(page.locator(".pm-spec dd").first).to_have_text(re.compile("未运行|Inactive"))
        expect(page.locator(".pm-detail-actions .pm-primary")).to_have_text(
            re.compile("安装|Install")
        )
