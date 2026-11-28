"""Exercise Billing and Knowledge in a dedicated local tenant via the signed marketplace."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import apply, more

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_QA_VERTICAL_OWNER"),
        reason="requires a dedicated loopback tenant and the published 1.0.3/1.1.1 releases",
    ),
]


def catalog_detail(page, path, package):
    page.goto(path)
    page.locator(f"#pm-card-memstack-{package}").click()
    expect(page.locator(".pm-spec")).to_be_visible()


def open_page(page, title):
    page.locator(".pm-detail-actions").get_by_role(
        "button", name=re.compile("^(Open feature|打开功能)$")
    ).click()
    apps = page.get_by_role("combobox", name=re.compile("^(Applications|业务页面)$"))
    apps.select_option(label=title)
    frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
    return frame


def billing_account(page, tenant_name):
    frame = open_page(page, "Plans and invoices")
    frame.get_by_role("button", name=re.compile("^(View tenant account|查看租户账户)$")).click()
    expect(frame.get_by_role("heading", name=tenant_name)).to_be_visible()
    # Only the explicitly named disposable tenant may be changed in this test.
    plan = frame.get_by_text(re.compile("^(Current plan|当前套餐)$"), exact=True).locator("+ dd")
    original = plan.inner_text()
    other = "free" if original == "pro" else "pro"
    for target in (other, original):
        frame.get_by_role("combobox").select_option(target)
        frame.get_by_role("button", name=re.compile("^(Confirm plan change|确认更改套餐)$")).click()
        expect(plan).to_have_text(target)
        expect(
            frame.get_by_role("button", name=re.compile("^(Refresh account|刷新账户)$"))
        ).to_be_enabled()
    expect(
        frame.get_by_role("heading", name=re.compile("^(Tenant invoice history|租户历史发票)$"))
    ).to_be_visible()


def knowledge_memory(page, title):
    frame = open_page(page, "Project memories")
    frame.get_by_role("button", name=re.compile("^(New memory|新建记忆)$")).click()
    expect(frame.get_by_role("heading", name=re.compile("^(New memory|新建记忆)$"))).to_be_visible()
    title_field = frame.get_by_label(re.compile("^(Title|标题)$"), exact=True)
    content = frame.get_by_label(re.compile("^(Content|正文)$"), exact=True)
    title_field.fill(title)
    content.fill("Original content")

    def command(response, name):
        return (
            urlsplit(response.url).path.endswith("/memstack-knowledge/commands")
            and response.request.post_data_json["command_id"] == name
        )

    with page.expect_response(
        lambda response: command(response, "read-memory"), timeout=60000
    ) as opened:
        title_field.press("Enter")
    assert opened.value.ok, opened.value.status
    expect(
        frame.get_by_role("heading", name=re.compile("^(Memory details|记忆详情)$"))
    ).to_be_visible()
    expect(title_field).to_have_value(title)
    expect(content).to_have_value("Original content")
    content.fill("Edited content")
    with page.expect_response(
        lambda response: command(response, "save-memory"), timeout=60000
    ) as saved:
        frame.get_by_role("button", name=re.compile("^(Save memory|保存记忆)$")).click()
    assert saved.value.ok, saved.value.status
    assert saved.value.json()["content"] == "Edited content"
    with page.expect_response(lambda response: command(response, "read-memory")) as refreshed:
        frame.get_by_role(
            "button", name=re.compile("^(Reload saved version|重新读取已保存版本)$")
        ).click()
    assert refreshed.value.ok and refreshed.value.json()["version"] == saved.value.json()["version"]
    expect(content).to_have_value("Edited content")


@pytest.mark.parametrize("package", ["billing", "knowledge"])
def test_old_new_rollback_signed_vertical(package):
    account = json.loads(Path(os.environ["MEMSTACK_QA_VERTICAL_OWNER"]).read_text())
    assert account["tenant_name"] == "Signed billing and knowledge acceptance"
    origin = os.getenv("MEMSTACK_QA_VERTICAL_ORIGIN", "http://127.0.0.1:3000")
    assert urlsplit(origin).hostname in {"127.0.0.1", "localhost", "::1"}
    path = f"{origin}/tenant/{account['tenant_id']}/plugins?" + urlencode(
        {"projectId": account["project_id"]}
    )
    title = "Signed memory " + uuid4().hex[:12]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(locale="en-US")
        page.set_default_timeout(30000)
        page.goto(origin + "/login")
        page.get_by_test_id("email-input").fill(account["email"])
        page.get_by_test_id("password-input").fill(account["password"])
        page.get_by_test_id("login-submit-button").click()
        expect(page.get_by_test_id("login-submit-button")).to_have_count(0, timeout=30000)
        catalog_detail(page, path, package)
        running = page.locator(".pm-spec dd").first
        if running.inner_text() not in ("Inactive", "未运行"):
            more(page, "Uninstall|卸载")
            expect(running).to_have_text(re.compile("Inactive|未运行"))
        apply(page, "1.0.3")
        apply(page, "1.1.1")
        if package == "billing":
            billing_account(page, account["tenant_name"])
        else:
            knowledge_memory(page, title)
        catalog_detail(page, path, package)
        more(page, "Roll back|回退|回滚")
        expect(running).to_have_text("1.0.3")
        if package == "billing":
            frame = open_page(page, "Plans and invoices")
            frame.get_by_role("button", name="pro", exact=True).click()
            expect(
                frame.locator("output").filter(has_text=re.compile("bytes|字节"))
            ).to_be_visible()
            expect(
                frame.get_by_role("button", name=re.compile("^(View tenant account|查看租户账户)$"))
            ).to_have_count(0)
        else:
            frame = open_page(page, "Project memories")
            frame.get_by_role("searchbox").fill(title)
            frame.get_by_role("button", name=re.compile("^(Search|搜索)$"), exact=True).click()
            expect(frame.get_by_role("heading", name=title)).to_be_visible()
            expect(frame.get_by_text("Edited content", exact=True)).to_be_visible()
        catalog_detail(page, path, package)
        more(page, "Uninstall|卸载")
        expect(running).to_have_text(re.compile("Inactive|未运行"))
        browser.close()
