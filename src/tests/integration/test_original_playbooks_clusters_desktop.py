"""Open the npm releases in a signed-in native workbench with a disposable QA project."""

import os
import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import apply

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_QA_ORIGINAL_VIEWS_CDP"),
        reason="requires a signed-in local Electron QA marketplace",
    ),
]


def test_native_playbook_verdicts_and_cluster_health():
    origin = os.environ["MEMSTACK_QA_ORIGINAL_VIEWS_CDP"]
    assert urlsplit(origin).hostname in {"localhost", "127.0.0.1", "::1"}
    with sync_playwright() as pw:
        page = pw.chromium.connect_over_cdp(origin).contexts[0].pages[0]
        page.set_default_timeout(25000)
        page.locator(".package-market-scope select").select_option("project")
        if not page.locator(".pm-page-list").count():
            page.locator("#pm-card-memstack-automation").click()
        if page.locator(".pm-spec dd").first.inner_text() != "1.3.1":
            apply(page, "1.3.1")
        page.locator(".pm-page-list").get_by_role(
            "button", name="Project playbooks", exact=True
        ).click()
        frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        view = frame.locator('[data-route-id="project-playbooks"]')
        expect(view).to_have_attribute("data-state", re.compile("ready|empty"), timeout=40000)
        expect(view.get_by_role("heading", level=2).nth(1)).to_be_visible()
        view.get_by_role("button", name=re.compile("Refresh|刷新")).click()
        expect(view).to_have_attribute("data-state", re.compile("ready|empty"), timeout=40000)
        page.go_back()
        page.locator(".package-market-scope select").select_option("tenant")
        page.locator("#pm-card-memstack-environments").click()
        if page.locator(".pm-spec dd").first.inner_text() != "1.3.0":
            apply(page, "1.3.0")
        page.locator(".pm-page-list").get_by_role("button", name="Clusters", exact=True).click()
        view = frame.locator(".runtime-clusters-page")
        expect(view.get_by_role("searchbox")).to_be_enabled(timeout=40000)
        expect(view.locator(".runtime-clusters-inventory")).to_be_visible()
        name = os.environ.get("MEMSTACK_QA_ORIGINAL_CLUSTER_NAME")
        if name:
            row = view.get_by_role("row").filter(has_text=name)
            row.get_by_role(
                "button", name=re.compile("Inspect health|查看健康|检查健康|健康检查")
            ).click()
            expect(view.get_by_role("dialog").locator("dl dd").first).to_be_visible(timeout=30000)
        page.go_back()
