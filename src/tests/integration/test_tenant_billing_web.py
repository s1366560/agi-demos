"""Install Billing in an empty development tenant, then reload its signed business URL."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import apply, business_release, confirm, more

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_QA_EMPTY_TENANT_OWNER"),
        reason="requires the dedicated local empty tenant and published Billing releases",
    ),
]


def _check_original_billing_view(page):
    original_ui = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
    expect(
        original_ui.get_by_role("heading", name=re.compile("Current Plan|当前计划"))
    ).to_be_visible(timeout=30000)
    expect(
        original_ui.get_by_role("heading", name=re.compile("Billing History|账单历史|账单记录"))
    ).to_be_visible()
    original_ui.get_by_role("button", name=re.compile("Upgrade to Pro|升级到 Pro")).click()
    confirmation = original_ui.get_by_role("dialog")
    expect(confirmation).to_be_visible()
    confirmation.get_by_role("button", name=re.compile(r"Cancel|取\s*消")).click()
    expect(confirmation).to_have_count(0)


def _select_plan(page, frame, plan, choice):
    frame.get_by_role("combobox").select_option(choice)
    with page.expect_response(
        lambda response: (
            urlsplit(response.url).path.endswith("/tenant-packages/memstack-billing/commands")
            and response.request.method == "POST"
            and response.request.post_data_json.get("command_id") == "change-plan"
        ),
        timeout=60000,
    ) as changed:
        frame.get_by_role("button", name=re.compile("Confirm plan change|确认更改套餐")).click()
    assert changed.value.ok, changed.value.status
    expect(plan).to_have_text(choice, timeout=60000)
    expect(frame.get_by_role("button", name=re.compile("Refresh account|刷新账户"))).to_be_enabled(
        timeout=60000
    )


def _install_from_original_bookmark(page, base):
    bookmark = base + "/billing?view=history#invoices"
    page.goto(bookmark)
    page.get_by_role(
        "link", name=re.compile("返回插件市场|Back to (plugin )?market", re.I)
    ).click()
    page.locator("#pm-card-memstack-billing").click()
    page.locator(".pm-spec select").select_option("1.2.0")
    page.locator(".pm-detail-actions").get_by_role(
        "button", name=re.compile("^(Install|安装)")
    ).click()
    confirm(page)
    expect(page).to_have_url(bookmark, timeout=60000)


def test_empty_tenant_billing_via_market_and_direct_url():
    account = json.loads(Path(os.environ["MEMSTACK_QA_EMPTY_TENANT_OWNER"]).read_text())
    assert account["tenant_name"] == "Signed tenant billing without projects"
    origin = os.getenv("MEMSTACK_QA_VERTICAL_ORIGIN", "http://127.0.0.1:3000")
    assert urlsplit(origin).hostname in ("127.0.0.1", "localhost", "::1")
    base = f"{origin}/tenant/{account['tenant_id']}"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(30000)
        page.goto(origin + "/login")
        page.get_by_test_id("email-input").fill(account["email"])
        page.get_by_test_id("password-input").fill(account["password"])
        page.get_by_test_id("login-submit-button").click()
        expect(page.get_by_test_id("login-submit-button")).to_have_count(0, timeout=30000)

        def details():
            page.goto(base + "/plugins")
            page.locator("#pm-card-memstack-billing").click()
            expect(page.locator(".pm-spec")).to_be_visible()

        details()
        current = page.locator(".pm-spec dd").first
        if current.inner_text() not in ("Inactive", "未运行"):
            more(page, "Uninstall|卸载")
            expect(current).to_have_text(re.compile("Inactive|未运行"), timeout=60000)
        _install_from_original_bookmark(page, base)
        details()
        apply(page, business_release("billing"))
        page.goto(base + "/billing")
        _check_original_billing_view(page)
        details()
        more(page, "Roll back|回退|回滚")
        expect(current).to_have_text("1.2.0", timeout=60000)
        page.goto(base + "/billing")
        page.reload()
        frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        with page.expect_response(
            lambda response: urlsplit(response.url).path.endswith(
                "/tenant-packages/memstack-billing/commands"
            )
        ) as received:
            frame.get_by_role("button", name=re.compile("View tenant account|查看租户账户")).click()
        assert received.value.ok and received.value.json()["usage"]["projects"] == 0
        assert "project_id" not in received.value.request.post_data_json
        expect(frame.get_by_role("heading", name=account["tenant_name"])).to_be_visible()
        plan = frame.get_by_text(re.compile("^(Current plan|当前套餐)$"), exact=True).locator(
            "+ dd"
        )
        original = plan.inner_text()

        try:
            _select_plan(page, frame, plan, "free" if original == "pro" else "pro")
        finally:
            _select_plan(page, frame, plan, original)
        details()
        more(page, "Uninstall|卸载")
        expect(current).to_have_text(re.compile("Inactive|未运行"), timeout=60000)
        browser.close()
