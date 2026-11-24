"""Exercise both clients' signed schedule editor and the native tenant billing account."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import (
    apply,
    business_release,
    install_previous,
    more,
    open_market,
)

pytestmark = pytest.mark.integration


def _details(page, package):
    spec = page.locator(".pm-spec")
    card = page.locator("#pm-card-memstack-" + package)
    spec.or_(card).first.wait_for(timeout=90000)
    if not spec.is_visible():
        card.click()
    expect(spec).to_contain_text("127.0.0.1:4873", timeout=90000)
    return spec.locator("dd").first


def _open(page, entry):
    page.locator(".pm-page-list").get_by_role("button", name=entry, exact=True).click()
    return page.frame_locator("iframe[data-page-ready=true]").first.frame_locator("iframe")


def _back(page, package):
    back = page.get_by_text(re.compile(r"^(返回插件市场|Back to (plugin )?marketplace)$"))
    back.scroll_into_view_if_needed()
    expect(back).to_be_in_viewport(ratio=1)
    back.focus()
    back.press("Enter")
    return _details(page, package)


def _native(pw, owner, scope):
    cdp = os.environ["MEMSTACK_QA_BUSINESS_MARKET_CDP"]
    assert urlsplit(cdp).hostname in {"localhost", "127.0.0.1", "::1"}
    page = pw.chromium.connect_over_cdp(cdp).contexts[0].pages[0]
    page.evaluate("(hash) => {location.hash=hash}", f"/tenant/{owner['tenant_id']}/plugins")
    page.locator(".package-market-scope select").select_option(scope)
    if page.locator(".pm-back").is_visible():
        page.locator(".pm-back").click()
    return page


def _edit_schedule(frame, scope):
    assert frame.locator("html").evaluate("async()=> (await memstack.scope()).projectId") == scope
    # The signed Ant page supplies its own reading surface even in a dark Electron window.
    expect(frame.locator("body")).not_to_have_css("background-color", "rgba(0, 0, 0, 0)")
    expect(
        frame.get_by_role("heading", name=re.compile("Scheduled Tasks|定时任务"))
    ).to_be_visible()
    frame.get_by_role("button", name=re.compile("Create Job|创建任务|新建任务")).click()
    form = frame.get_by_role("dialog")
    name = "Signed UI schedule " + uuid4().hex[:9]
    form.locator("input[id=name]").fill(name)
    form.locator("textarea[id=payload_config_content]").fill("QA schedule")
    form.get_by_role("switch").first.click()
    form.locator("button.ant-btn-primary").click()
    row = frame.get_by_role("row").filter(has_text=name)
    expect(row).to_be_visible(timeout=60000)
    row.get_by_role("button", name=re.compile("History|历史|记录")).click()
    history = frame.get_by_role("dialog", name=re.compile("Run History|运行历史|执行历史", re.I))
    history.get_by_role("button", name=re.compile("Close|关闭")).click()
    expect(history).not_to_be_visible()
    row.get_by_role("button", name=re.compile("Delete|删除")).click()
    frame.locator(".ant-popconfirm-buttons .ant-btn-primary").click()
    expect(row).to_have_count(0, timeout=60000)


@pytest.mark.parametrize("target", ["web", "desktop"])
def test_installed_schedule_lifecycle(target):
    owner_path = os.getenv("MEMSTACK_QA_SCHEDULE_OWNER")
    if not owner_path or (target == "desktop" and not os.getenv("MEMSTACK_QA_BUSINESS_MARKET_CDP")):
        pytest.skip("requires an isolated schedule project and selected client")
    owner = json.loads(Path(owner_path).read_bytes())
    with sync_playwright() as pw:
        if target == "web":
            page = pw.chromium.launch().new_page(locale="en-US")
            open_market(page, "full", os.environ["MEMSTACK_QA_MARKET_FULL_ORIGIN"], owner)
        else:
            page = _native(pw, owner, "project")
        page.set_default_timeout(60000)
        active = _details(page, "automation")
        install_previous(page, "1.3.1")
        apply(page, business_release("automation"))
        _edit_schedule(_open(page, "Project schedules"), owner["project_id"])
        _back(page, "automation")
        more(page, "Roll back to|回退至")
        expect(active).to_have_text("1.3.1", timeout=60000)
        old = _open(page, "Project schedules")
        expect(old.locator("fieldset,select").first).to_be_visible()
        expect(old.locator(".ant-table")).to_have_count(0)
        _back(page, "automation")
        apply(page, business_release("automation"))
        expect(_open(page, "Project schedules").locator(".ant-table").first).to_be_visible()


def test_installed_native_billing_lifecycle():
    owner_path = os.getenv("MEMSTACK_QA_FIXED_BILLING_OWNER")
    if not owner_path or not os.getenv("MEMSTACK_QA_BUSINESS_MARKET_CDP"):
        pytest.skip("requires an isolated tenant owner and Electron window")
    owner = json.loads(Path(owner_path).read_bytes())
    with sync_playwright() as pw:
        page = _native(pw, owner, "tenant")
        page.set_default_timeout(60000)
        active = _details(page, "billing")
        install_previous(page, "1.2.0")
        apply(page, business_release("billing"))
        billing = _open(page, "Tenant billing").locator('[data-tenant-admin-route="billing"]')
        expect(billing.locator(":scope > dl dd").first).to_have_text(owner["tenant_id"])
        expect(billing.get_by_role("heading", name=re.compile("Usage|用量"))).to_be_visible()
        baseline = billing.locator(":scope > dl dd").last.inner_text()
        _back(page, "billing")
        more(page, "Roll back|回退|回滚")
        expect(active).to_have_text("1.2.0", timeout=60000)
        old = _open(page, "Tenant billing")
        old.get_by_role("button", name=re.compile("View tenant account|查看租户账户")).click()
        expect(
            old.get_by_text(re.compile("^(Current plan|当前套餐)$")).locator("+ dd")
        ).to_have_text(baseline)
        _back(page, "billing")
        apply(page, business_release("billing"))
        expect(
            _open(page, "Tenant billing").locator('[data-tenant-admin-route="billing"]')
        ).to_be_visible()
