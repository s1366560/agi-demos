"""Drive a reviewed release change through the shared desktop and Web marketplace."""

import re

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
