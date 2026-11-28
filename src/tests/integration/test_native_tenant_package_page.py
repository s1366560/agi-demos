"""Validate tenant package installation and its real cluster detail in the native workbench."""

import os
import re

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import apply, business_release, more


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("MEMSTACK_QA_TENANT_CLUSTER_NAME"),
    reason="requires a signed-in Electron QA window and a cluster in its disposable tenant",
)
def test_install_tenant_environment_and_read_cluster_without_project():
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            os.environ["MEMSTACK_QA_BUSINESS_MARKET_CDP"]
        )
        page = browser.contexts[0].pages[0]
        page.set_default_timeout(20000)
        page.locator(".package-market-scope select").select_option("tenant")
        page.locator("#pm-card-memstack-environments").click()
        if page.locator(".pm-spec dd").first.inner_text() != "1.2.0":
            apply(page, "1.2.0")
        page.locator(".pm-page-list").get_by_role("button", name="Clusters", exact=True).click()
        expect(page.locator("main.desktop-package-workbench")).to_be_visible()
        frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        name = os.environ["MEMSTACK_QA_TENANT_CLUSTER_NAME"]
        frame.get_by_role("button", name=name, exact=True).click()
        expect(frame.get_by_role("heading", name=name, exact=True)).to_be_visible()
        expect(frame.locator("dd", has_text="docker")).to_be_visible()
        page.go_back()
        expect(frame.get_by_role("button", name=name, exact=True)).to_be_visible()
        page.go_back()
        expect(page.locator(".pm-spec select")).to_be_visible()


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("MEMSTACK_QA_TENANT_CLUSTER_NAME"), reason="requires native QA tenant"
)
def test_tenant_automation_uses_the_original_patterns_view():
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            os.environ["MEMSTACK_QA_BUSINESS_MARKET_CDP"]
        )
        page = browser.contexts[0].pages[0]
        page.set_default_timeout(30000)
        page.locator(".package-market-scope select").select_option("tenant")
        page.locator("#pm-card-memstack-automation").click()
        if page.locator(".pm-spec dd").first.inner_text() != "1.2.2":
            apply(page, "1.2.2")
        page.locator(".pm-page-list").get_by_role(
            "button", name="Workflow patterns", exact=True
        ).click()
        frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        search = frame.get_by_placeholder(re.compile("Search patterns|搜索模式"))
        expect(search).to_be_visible(timeout=20000)
        frame.get_by_role("button", name=re.compile("Refresh|刷新")).click()
        frame.get_by_role("combobox").select_option("name")
        search.fill("no such pattern")
        expect(frame.get_by_role("region", name=re.compile("Pattern table|模式表"))).to_be_visible()
        expect(
            frame.get_by_text(re.compile("No patterns found|未找到模式|没有找到|暂无模式"))
        ).to_be_visible()
        page.get_by_role("button", name=re.compile("返回插件市场|Back to marketplace")).click()
        expect(page.locator(".pm-spec select")).to_be_visible(timeout=30000)


@pytest.mark.integration
@pytest.mark.skipif(
    not (
        os.getenv("MEMSTACK_QA_NATIVE_BILLING") and os.getenv("MEMSTACK_QA_NATIVE_BILLING_TENANT")
    ),
    reason="requires a disposable owner tenant in Electron",
)
def test_native_original_billing_respects_plan_authority():
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            os.environ["MEMSTACK_QA_BUSINESS_MARKET_CDP"]
        )
        page = browser.contexts[0].pages[0]
        page.locator(".package-market-scope select").select_option("tenant")
        page.locator("#pm-card-memstack-billing").click()
        if page.locator(".pm-spec dd").first.inner_text() != "1.3.1":
            apply(page, "1.3.1")
        page.locator(".pm-page-list").get_by_role("button", name="Tenant billing").click()
        frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        billing = frame.locator('[data-tenant-admin-route="billing"]')
        expect(billing).to_be_visible(timeout=30000)
        expect(billing.locator(":scope > dl dd").first).to_have_text(
            os.environ["MEMSTACK_QA_NATIVE_BILLING_TENANT"]
        )
        plan = billing.locator(":scope > dl dd").last
        before = plan.inner_text()
        if os.getenv("MEMSTACK_QA_NATIVE_BILLING") == "admin":
            expect(billing.get_by_role("button", name="pro", exact=True)).to_have_count(0)
            expect(billing.get_by_role("heading", name=re.compile("Usage|用量"))).to_be_visible()
            return
        try:
            choice = "free" if before == "pro" else "pro"
            billing.get_by_role("button", name=choice, exact=True).click()
            expect(plan).to_have_text(choice, timeout=30000)
        finally:
            if plan.inner_text() != before:
                billing.get_by_role("button", name=before, exact=True).click()
                expect(plan).to_have_text(before, timeout=30000)
        page.get_by_role(
            "button", name=re.compile("^返回工作台$|^Back to workspace$", re.I)
        ).click()
        close = page.get_by_role("button", name=re.compile("^关闭设置$|^Close settings$", re.I))
        if close.is_visible():
            close.click()
        page.get_by_role("button", name=re.compile("^全部功能$|^All features$", re.I)).click()
        page.locator('[role="dialog"] button').filter(
            has_text=re.compile("账单|Billing")
        ).first.click()
        expect(billing).to_be_visible(timeout=30000)
        expect(billing.locator(":scope > dl dd").first).to_have_text(
            os.environ["MEMSTACK_QA_NATIVE_BILLING_TENANT"]
        )
        expect(plan).to_have_text(before)


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("MEMSTACK_QA_NATIVE_ENVIRONMENTS"),
    reason="requires a disposable native tenant and published Environments release",
)
def test_native_deployments_templates_and_pool():
    from src.tests.integration.test_fixed_workbench_market import _back, _details, _open

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            os.environ["MEMSTACK_QA_BUSINESS_MARKET_CDP"]
        )
        page = browser.contexts[0].pages[0]
        page.set_default_timeout(60000)
        page.locator(".package-market-scope select").select_option("tenant")
        active = _details(page, "environments")
        previous = active.inner_text()
        current = business_release("environments")
        if previous != current:
            apply(page, current)
        try:
            templates = _open(page, "Instance templates")
            expect(templates.locator("#instance-templates-title")).to_be_visible()
            create = templates.locator(".instance-templates-header button").last
            create.click()
            expect(templates.get_by_role("dialog").locator("input").first).to_be_visible()
            _back(page, "environments")
            deployments = _open(page, "Deployments")
            expect(deployments.locator("#runtime-deployments-title")).to_be_visible()
            _back(page, "environments")
            pool = _open(page, "Runtime pool")
            expect(pool.locator(".ant-statistic").first).to_be_visible()
        finally:
            _back(page, "environments")
            if previous != current:
                if previous in {"Inactive", "未运行"}:
                    more(page, "Uninstall|卸载")
                else:
                    apply(page, previous)
