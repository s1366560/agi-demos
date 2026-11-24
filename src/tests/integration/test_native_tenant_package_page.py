"""Validate tenant package installation and its real cluster detail in the native workbench."""

import os

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import apply


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
