"""Drive a reviewed release change through the shared desktop and Web marketplace."""

import re
from urllib.parse import urlencode, urlsplit

from playwright.sync_api import Page, expect


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


def more(page: Page, action: str) -> None:
    menu = page.locator(".pm-detail-actions details")
    menu.locator("summary").click()
    menu.get_by_role("button", name=re.compile(action)).click()
    page.locator("dialog.pm-dialog .pm-actions button").last.click()


def is_catalog(response):
    return urlsplit(response.url).path.endswith("/optional-business/npm/catalog") and response.ok


def open_market(page: Page, host, origin, account):
    project = account["project_id"]
    if host == "full":
        page.goto(origin + "/login")
        page.get_by_test_id("email-input").fill(account["email"])
        page.get_by_test_id("password-input").fill(account["password"])
        page.get_by_test_id("login-submit-button").click()
        expect(page.get_by_test_id("login-submit-button")).to_have_count(0)
        with page.expect_response(is_catalog) as opened:
            page.goto(
                f"{origin}/tenant/{account['tenant_id']}/plugins?"
                + urlencode({"projectId": project})
            )
    else:
        page.goto(origin + "/?" + urlencode({"project": project}))
        page.get_by_label("Email", exact=True).fill(account["email"])
        page.get_by_label("Password", exact=True).fill(account["password"])
        page.get_by_role("button", name="Sign In", exact=True).click()
        with page.expect_response(is_catalog) as opened:
            page.get_by_role("button", name="Manage plugins").click()
    return opened.value
