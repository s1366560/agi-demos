"""Drive a reviewed release change through the shared desktop and Web marketplace."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import pytest
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, expect


def business_release(package: str) -> str:
    root = Path(__file__).resolve().parents[3]
    manifest = root / "plugins" / "business" / package / "package.json"
    return json.loads(manifest.read_bytes())["version"]


def apply(page: Page, version: str) -> None:
    page.locator(".pm-spec select").select_option(version)
    actions = page.locator(".pm-detail-actions")
    action = actions.get_by_role(
        "button", name=re.compile("^(Install|安装|Update to|更新至|切换版本|Switch version)")
    )
    action.click()
    dialog = page.locator("dialog.pm-dialog")
    expect(dialog).to_contain_text(version)
    confirm(page)

    expect(page.locator(".pm-spec dd").first).to_have_text(version, timeout=120000)


def more(page: Page, action: str) -> None:
    menu = page.locator(".pm-detail-actions details")
    menu.locator("summary").click()
    menu.get_by_role("button", name=re.compile(action)).click()
    confirm(page)


def confirm(page: Page) -> None:
    dialog = page.locator("dialog.pm-dialog")
    scope = os.getenv("MEMSTACK_QA_EXPECT_MARKET_SCOPE")
    if scope:
        expect(dialog).to_contain_text(scope)
    dialog.locator(".pm-actions button").last.click()
    page.wait_for_function(
        """() => !document.querySelector("dialog.pm-dialog[open]") ||
                 document.querySelector("dialog.pm-dialog .pm-error") !== null""",
        timeout=120000,
    )
    error = dialog.locator(".pm-error")
    if error.count():
        pytest.fail("Package change was rejected: " + error.inner_text())


def install_previous(page: Page, previous: str) -> None:
    active = page.locator(".pm-spec dd").first
    expect(active).to_be_visible(timeout=90000)
    menu = page.locator(".pm-detail-actions details")
    menu.locator("summary").click()
    uninstall = menu.get_by_role("button", name=re.compile("Uninstall|卸载"))
    if uninstall.is_visible():
        uninstall.click()
        confirm(page)
        expect(
            page.locator(".pm-detail-actions").get_by_role(
                "button", name=re.compile("^(Install|安装)")
            )
        ).to_be_visible(timeout=90000)
    else:
        menu.locator("summary").click()
    apply(page, previous)


def is_catalog(response):
    return urlsplit(response.url).path.endswith("/optional-business/npm/catalog") and response.ok


def open_market(page: Page, host, origin, account):
    project = account["project_id"]
    if host == "full":
        page.goto(origin + "/login")
        page.get_by_test_id("email-input").fill(account["email"])
        page.get_by_test_id("password-input").fill(account["password"])
        page.get_by_test_id("login-submit-button").click()
        expect(page.get_by_test_id("login-submit-button")).to_have_count(0, timeout=30000)
        market_url = f"{origin}/tenant/{account['tenant_id']}/plugins?" + urlencode(
            {"projectId": project}
        )
        for attempt in range(3):
            try:
                with page.expect_response(is_catalog, timeout=30000) as opened:
                    page.goto(market_url)
                break
            except PlaywrightTimeout:
                if attempt == 2:
                    raise
    else:
        page.goto(origin + "/?" + urlencode({"project": project}))
        page.get_by_label("Email", exact=True).fill(account["email"])
        page.get_by_label("Password", exact=True).fill(account["password"])
        page.get_by_role("button", name="Sign In", exact=True).click()
        with page.expect_response(is_catalog) as opened:
            page.get_by_role("button", name="Manage plugins").click()
    return opened.value
