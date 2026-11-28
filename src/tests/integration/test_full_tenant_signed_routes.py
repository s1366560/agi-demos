"""Open original tenant workbench bookmarks using locally published package pages."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import apply, business_release, more

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_QA_EMPTY_TENANT_OWNER"),
        reason="requires an isolated local tenant and published npm releases",
    ),
]


@pytest.mark.parametrize(
    ("package", "version", "route", "search_label"),
    [
        ("automation", business_release("automation"), "patterns", "Search patterns|搜索模式"),
        ("environments", business_release("environments"), "clusters", "Search clusters|搜索集群"),
    ],
)
def test_tenant_bookmark_opens_installed_original(package, version, route, search_label):
    account = json.loads(Path(os.environ["MEMSTACK_QA_EMPTY_TENANT_OWNER"]).read_text())
    assert account["tenant_name"] == "Signed tenant billing without projects"
    origin = os.getenv("MEMSTACK_QA_VERTICAL_ORIGIN", "http://localhost:3000")
    assert urlsplit(origin).hostname in ("localhost", "127.0.0.1", "::1")
    tenant = f"{origin}/tenant/{account['tenant_id']}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(60000)
        page.goto(origin + "/login")
        page.get_by_test_id("email-input").fill(account["email"])
        page.get_by_test_id("password-input").fill(account["password"])
        page.get_by_test_id("login-submit-button").click()
        expect(page.get_by_test_id("login-submit-button")).to_have_count(0, timeout=60000)

        def market():
            page.goto(tenant + "/plugins")
            page.locator("#pm-card-memstack-" + package).click()
            return page.locator(".pm-spec dd").first.inner_text()

        previous = market()
        try:
            if previous != version:
                apply(page, version)
            for bookmark in (
                tenant + "/" + route + "?workbench=full",
                f"{origin}/tenant/{route}?workbench=full&tenant={account['tenant_id']}",
            ):
                page.goto(bookmark)
                frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
                search = frame.get_by_placeholder(re.compile(search_label))
                expect(search).to_be_visible(timeout=60000)
                search.fill("qa-missing-item")
                expect(search).to_have_value("qa-missing-item")
            if package == "environments":
                bookmark = tenant + "/org-settings/clusters?qa=readonly#node"
                page.goto(bookmark)
                expect(
                    page.get_by_role("link", name=re.compile("Clusters|集群")).last
                ).to_be_visible()
                panel = page.frame_locator('iframe[title="Organization clusters"]').frame_locator(
                    "iframe"
                )
                panel.get_by_role("button", name=re.compile("Manage Clusters|管理集群")).click()
                expect(
                    page.frame_locator('iframe[title="Clusters"]')
                    .frame_locator("iframe")
                    .get_by_placeholder(re.compile(search_label))
                ).to_be_visible()
                page.go_back()
                expect(page).to_have_url(bookmark)
                _open_runtime_template(page, tenant)
            if package == "automation":
                _open_tenant_activity(page, tenant)
        finally:
            if previous != version:
                current = market()
                if current == version:
                    if previous in {"Inactive", "未运行"}:
                        more(page, "Uninstall|卸载")
                        expect(page.locator(".pm-spec dd").first).to_have_text(
                            re.compile("Inactive|未运行"), timeout=60000
                        )
                    else:
                        apply(page, previous)
            browser.close()


def _open_runtime_template(page, tenant):
    frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
    page.goto(tenant + "/deploy")
    expect(frame.get_by_text(re.compile("Deploy Records|部署记录")).first).to_be_visible()
    with page.expect_response(
        lambda response: response.url.endswith("/commands")
        and response.request.post_data_json.get("command_id") == "read-runtime-pool"
        and response.request.post_data_json["payload"].get("resource") == "status"
    ) as pool:
        page.goto(tenant + "/pool")
    assert pool.value.ok, pool.value.status
    expect(frame.locator(".ant-statistic").first).to_be_visible()
    listing = tenant + "/instance-templates"
    page.goto(listing)
    name = "Signed QA " + uuid4().hex[:12]
    frame.get_by_role("button", name=re.compile("Create Template|创建模板")).click()
    dialog = frame.get_by_role("dialog")
    dialog.get_by_label(re.compile("Template Name|模板名称")).fill(name)
    dialog.locator("button.ant-btn-primary").click()
    view = frame.get_by_role("button", name=re.compile(rf"(View|查看) {name}"))
    expect(view).to_be_visible()
    try:
        view.click()
        deploy = frame.get_by_role("button", name=re.compile("Deploy from Template|从模板部署"))
        expect(deploy).to_be_visible()
        template_id = urlsplit(page.url).path.rsplit("/", 1)[-1]
        deploy.click()
        expect(page).to_have_url(
            re.compile(re.escape(tenant + "/instances/create?templateId=" + template_id) + r"(&|$)")
        )
        expect(frame.locator("input[value='" + name + " Instance']")).to_be_visible()
        page.go_back()
        expect(deploy).to_be_visible()
    finally:
        page.goto(listing)
        frame.get_by_role("button", name=re.compile(rf"(Delete|删除) {name}")).click()
        frame.locator(".ant-popconfirm-buttons .ant-btn-primary").click()
        expect(view).to_have_count(0)


def _open_tenant_activity(page, tenant):
    for path, command in (("events", "read-events"), ("webhooks", "list-webhooks")):
        with page.expect_response(
            lambda response: response.url.endswith("/commands")
            and response.request.post_data_json.get("command_id") == command
        ) as operation:
            page.goto(f"{tenant}/{path}")
        assert operation.value.ok, operation.value.status
        frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        if path == "events":
            frame.get_by_role("combobox", name=re.compile("Filter by type|按类型过滤")).click()
            expect(frame.locator(".ant-select-dropdown")).to_be_visible()
        else:
            frame.get_by_role("button", name=re.compile("Create Webhook|创建Webhook")).click()
            expect(frame.get_by_role("dialog").get_by_label("URL")).to_be_visible()


def test_original_palette_and_user_selected_compatibility_bookmark():
    account = json.loads(Path(os.environ["MEMSTACK_QA_EMPTY_TENANT_OWNER"]).read_text())
    origin = os.getenv("MEMSTACK_QA_VERTICAL_ORIGIN", "http://localhost:3000")
    assert urlsplit(origin).hostname in ("localhost", "127.0.0.1", "::1")
    tenant = account["tenant_id"]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(60000)

        def sign_in():
            page.get_by_test_id("email-input").fill(account["email"])
            page.get_by_test_id("password-input").fill(account["password"])
            page.get_by_test_id("login-submit-button").click()
            expect(page.get_by_test_id("login-submit-button")).to_have_count(0, timeout=60000)

        page.goto(origin + "/login")
        sign_in()
        page.goto(f"{origin}/tenant/{tenant}/plugins")
        expect(page.locator("#pm-card-memstack-automation")).to_be_visible()
        page.keyboard.press("Control+k")
        dialog = page.get_by_role("dialog")
        combo = dialog.get_by_role("combobox")
        expect(combo).to_be_focused()
        options = dialog.get_by_role("option")
        audit = options.filter(has_text=re.compile("审计|audit", re.I)).first
        expect(audit).to_be_visible()
        combo.fill(audit.inner_text().splitlines()[0])
        expect(options.first).to_be_visible()
        combo.press("Escape")
        expect(dialog).to_have_count(0)

        bookmark = f"/tenant/{tenant}/decision-records?view=recent#details"
        compat = os.getenv("MEMSTACK_QA_COMPAT_ORIGIN", f"http://{urlsplit(origin).hostname}:3001")
        assert urlsplit(compat).hostname in ("localhost", "127.0.0.1", "::1")
        compat_requests = []
        page.on(
            "request",
            lambda req: compat_requests.append(req.url)
            if req.url.startswith(compat + "/")
            else None,
        )
        page.goto(origin + bookmark)
        link = page.locator(f'a[href^="{compat}/"]')
        expect(link).to_have_attribute("href", compat + bookmark)
        assert not compat_requests
        link.click()
        sign_in()
        page.wait_for_url(compat + bookmark, timeout=90000)
        browser.close()
