"""Use the original schedule editor and Sandbox settings with their real npm packages."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import apply, business_release, open_market

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_QA_CRON_SANDBOX_OWNER"),
        reason="requires a dedicated local QA project with no existing sandbox",
    ),
]


@pytest.fixture
def market():
    account = json.loads(Path(os.environ["MEMSTACK_QA_CRON_SANDBOX_OWNER"]).read_bytes())
    assert account["project_name"].startswith("Signed sandbox lifecycle QA ")
    origin = os.getenv("MEMSTACK_QA_ORIGINAL_VIEWS_ORIGIN", "http://127.0.0.1:3000")
    assert urlsplit(origin).hostname in {"127.0.0.1", "localhost", "::1"}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        p = b.new_page(locale="en-US")
        p.set_default_timeout(60000)
        open_market(p, "full", origin, account)
        yield p, account
        b.close()


def enter(page, plugin, title):
    page.locator("#pm-card-memstack-" + plugin).click()
    active = page.locator(".pm-spec dd").first
    version = business_release("automation") if plugin == "automation" else "1.4.0"
    if active.inner_text(timeout=90000) != version:
        apply(page, version)
    page.locator(".pm-page-list").get_by_role("button", name=title, exact=True).click()
    return page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")


def command(name):
    return lambda r: (
        r.request.method == "POST"
        and urlsplit(r.url).path.endswith("/commands")
        and r.request.post_data_json["command_id"] == name
    )


def test_original_cron_job_editor_history_and_delete(market):
    p, _ = market
    frame = enter(p, "automation", "Project schedules")
    frame.get_by_role("button", name=re.compile("Create Job|创建任务|新建任务")).click()
    form = frame.get_by_role("dialog")
    name = "Signed UI schedule " + uuid4().hex[:9]
    form.locator('input[id="name"]').fill(name)
    form.locator('textarea[id="payload_config_content"]').fill("QA schedule")
    form.get_by_role("switch").first.click()
    with p.expect_response(command("save-schedule")) as created:
        form.locator("button.ant-btn-primary").click()
    assert created.value.ok, created.value.text()[:180]
    row = frame.get_by_role("row").filter(has_text=name)
    expect(row).to_be_visible(timeout=30000)
    with p.expect_response(command("list-schedules")) as history:
        row.get_by_role("button", name=re.compile("History|历史|记录")).click()
    assert history.value.ok
    frame.get_by_role("dialog").locator(".ant-drawer-close").click()
    row.get_by_role("button", name=re.compile("Delete|删除")).click()
    with p.expect_response(command("delete-schedule")) as deleted:
        frame.locator(".ant-popconfirm-buttons .ant-btn-primary").click()
    assert deleted.value.ok
    expect(row).to_have_count(0)


def test_original_sandbox_lifecycle_in_disposable_empty_project(market):
    p, account = market
    with p.expect_response(command("sandbox-status"), timeout=90000) as initial:
        frame = enter(p, "environments", "Project sandbox")
    assert (
        initial.value.ok
        and initial.value.request.post_data_json["project_id"] == account["project_id"]
    )
    assert initial.value.json()["sandbox"] is None, (
        "This destructive lifecycle test needs its own empty QA sandbox."
    )
    panel = frame.locator("section#sandbox")
    expect(panel.get_by_role("heading")).to_be_visible()
    panel.get_by_role("combobox").select_option("standard")
    with p.expect_response(command("prepare-sandbox"), timeout=150000) as prepared:
        panel.get_by_role("button", name=re.compile("Prepare sandbox|准备沙箱")).click()
    assert prepared.value.ok, prepared.value.text()[:180]
    created = prepared.value.json()["sandbox"]
    assert created and created["sandbox_id"]
    with p.expect_response(command("restart-sandbox"), timeout=150000) as restarted:
        panel.get_by_role("button", name=re.compile("Restart|重启")).click()
    assert restarted.value.ok, restarted.value.text()[:180]
    panel.get_by_role("button", name=re.compile("Terminate|终止")).click()
    with p.expect_response(command("terminate-sandbox"), timeout=90000) as terminated:
        frame.get_by_role("dialog").locator("button.ant-btn-primary").click()
    assert terminated.value.ok
    expect(panel.get_by_role("button", name=re.compile("Restart|重启"))).to_have_count(0)


@pytest.mark.skipif(
    not os.getenv("MEMSTACK_QA_ORIGINAL_VIEWS_CDP"),
    reason="requires a native Electron QA window on the project marketplace",
)
def test_fixed_electron_opens_the_original_schedule_form_and_sandbox():
    origin = os.environ["MEMSTACK_QA_ORIGINAL_VIEWS_CDP"]
    assert urlsplit(origin).hostname in {"localhost", "127.0.0.1", "::1"}
    with sync_playwright() as pw:
        p = pw.chromium.connect_over_cdp(origin).contexts[0].pages[0]
        p.set_default_timeout(45000)
        frame = enter(p, "automation", "Project schedules")
        frame.get_by_role("button", name=re.compile("Create Job|创建任务|新建任务")).click()
        expect(
            frame.get_by_role("dialog").locator('textarea[id="payload_config_content"]')
        ).to_be_visible()
        p.go_back()
        p.locator(".pm-back").click()
        frame = enter(p, "environments", "Project sandbox")
        expect(
            frame.get_by_text(re.compile("尚未配置沙盒|No sandbox configured|Sandbox ID|沙盒 ID"))
        ).to_be_visible(timeout=45000)
        expect(frame.locator("section#sandbox").get_by_role("combobox")).to_be_visible()
        frame.get_by_role(
            "button", name=re.compile("Metrics and terminal access|资源指标与终端授权")
        ).click()
        expect(
            frame.get_by_role("button", name=re.compile("Load resource usage|读取资源用量"))
        ).to_be_visible(timeout=30000)


@pytest.mark.parametrize(
    ("plugin", "prior", "current", "title", "original_selector", "previous_selector"),
    [
        (
            "automation",
            "1.3.1",
            business_release("automation"),
            "Project schedules",
            ".ant-table",
            "fieldset,select",
        ),
        ("environments", "1.3.0", "1.4.0", "Project sandbox", "section#sandbox", "fieldset,output"),
    ],
)
def test_switch_original_editor_without_rebuilding_host(
    market, plugin, prior, current, title, original_selector, previous_selector
):
    from src.tests.integration.marketplace_browser import more

    page, _ = market
    catalog_url = page.url

    def details():
        page.goto(catalog_url)
        page.locator("#pm-card-memstack-" + plugin).click()
        expect(page.locator(".pm-spec")).to_be_visible(timeout=60000)

    def feature():
        page.locator(".pm-page-list").get_by_role("button", name=title, exact=True).click()
        return page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")

    details()
    if page.locator(".pm-spec dd").first.inner_text() != prior:
        apply(page, prior)
    apply(page, current)
    expect(feature().locator(original_selector).first).to_be_visible(timeout=30000)
    details()
    more(page, "Roll back to|回退至")
    expect(page.locator(".pm-spec dd").first).to_have_text(prior, timeout=45000)
    restored = feature()
    expect(restored.locator(previous_selector).first).to_be_visible(timeout=30000)
    expect(restored.locator(original_selector)).to_have_count(0)
    details()
    apply(page, current)
    expect(feature().locator(original_selector).first).to_be_visible(timeout=30000)
