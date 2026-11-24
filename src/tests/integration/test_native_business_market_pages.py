"""Exercise published official business pages through the signed-in desktop marketplace."""

import csv
import io
import os
import re
from uuid import uuid4

import pytest
from playwright.sync_api import FrameLocator, Page, expect, sync_playwright

from src.tests.integration.marketplace_browser import apply, more

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_QA_BUSINESS_MARKET_CDP"),
        reason="requires an Electron window open to the marketplace of a disposable project",
    ),
]


def open_page(page: Page, title: str) -> FrameLocator:
    page.locator(".pm-page-list").get_by_role("button", name=title, exact=True).click()
    frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
    expect(frame.get_by_role("heading").first).to_be_visible(timeout=25000)
    return frame


def detail(page: Page) -> None:
    page.go_back()
    expect(page.locator(".pm-spec select")).to_be_visible(timeout=15000)


def workspace(page: Page) -> None:
    frame = open_page(page, "Workspace directory")
    fields = frame.locator("tbody tr").first.locator("input")
    for index, value in enumerate(("native-csv", "QA workspace", "active")):
        fields.nth(index).fill(value)
    frame.get_by_role("button", name=re.compile("CSV", re.I)).click()
    output = frame.locator("pre")
    expect(output).to_contain_text("QA workspace")
    assert list(csv.reader(io.StringIO(output.inner_text())))[1][:3] == [
        "native-csv",
        "QA workspace",
        "active",
    ]
    detail(page)


def workflow(page: Page, saved: bool) -> None:
    frame = open_page(page, "Schedule workflow")
    frame.get_by_role("button", name=re.compile("添加间隔步骤|Add interval step")).click()
    if saved:
        name = "QA workflow " + uuid4().hex[:8]
        frame.get_by_label(re.compile("工作流名称|Workflow name")).fill(name)
        frame.get_by_role("button", name=re.compile("^保存工作流$|^Save workflow$")).click()
        expect(frame.get_by_role("status")).to_contain_text("1")
        frame.get_by_role("button", name=re.compile("重新载入版本|Reload saved revisions")).click()
        choices = frame.get_by_label(re.compile("已保存版本|Saved revisions"))
        choices.select_option(label=f"{name} · v1")
        frame.get_by_role("button", name=re.compile("运行已保存版本|Run saved revision")).click()
    else:
        frame.get_by_role("button", name=re.compile("^执行工作流$|^Run workflow$")).click()
    expect(frame.locator("ol[aria-live] li")).to_have_count(2, timeout=20000)
    detail(page)


def environment(page: Page, updated: bool) -> None:
    frame = open_page(page, "Sandbox patch preview")
    frame.get_by_label(re.compile("原始内容|Original content")).fill("one\n")
    frame.get_by_label(re.compile("统一差异补丁|Unified diff")).fill(
        "--- a/sample\n+++ b/sample\n@@ -1 +1 @@\n-one\n+two\n"
    )
    frame.get_by_role("button", name=re.compile("预览应用结果|Apply to preview")).click()
    expect(frame.locator("pre")).to_have_text("two")
    detail(page)
    if updated:
        frame = open_page(page, "Project sandbox")
        expect(frame.locator("output").first).to_have_text(re.compile(r".+"), timeout=20000)
        usage = frame.get_by_role("button", name=re.compile("读取资源用量|Load resource usage"))
        if usage.is_enabled():
            usage.click()
            expect(frame.locator("dt").filter(has_text=re.compile("CPU"))).to_be_visible()
        else:
            expect(frame.locator("output").first).to_contain_text(
                re.compile("项目尚无沙箱|No project sandbox")
            )
        detail(page)


@pytest.mark.parametrize("package", ["workspace", "automation", "environments"])
def test_official_market_update_and_rollback(package: str) -> None:
    """Start on the overview, run both releases, then restore the prior release through its menu."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            os.environ["MEMSTACK_QA_BUSINESS_MARKET_CDP"]
        )
        page = browser.contexts[0].pages[0]
        page.set_default_timeout(20000)
        if page.locator(".pm-back").is_visible():
            page.locator(".pm-back").click()
        page.locator("#pm-card-memstack-" + package).click()
        prior = os.getenv(
            "MEMSTACK_QA_PRIOR_" + package.upper(),
            "1.0.2" if package == "environments" else "1.0.3",
        )
        release = os.getenv(
            "MEMSTACK_QA_RELEASE_" + package.upper(),
            "1.1.1" if package == "automation" else "1.1.0",
        )
        running = page.locator(".pm-spec dd").first
        if running.inner_text() != prior:
            apply(page, prior)
        for version in (prior, release, prior):
            if version == release:
                apply(page, release)
            elif running.inner_text() != prior:
                more(page, "回退|回滚|Roll back")
            expect(running).to_have_text(version)
            page.locator(".pm-spec select").select_option(version)
            if package == "workspace":
                workspace(page)
            elif package == "automation":
                workflow(page, version == release)
            else:
                environment(page, version == release)
        page.locator(".pm-back").click()


@pytest.mark.parametrize("package", ["knowledge", "agent"])
def test_signed_react_page_upgrade_and_rollback(package: str) -> None:
    """Use the fixed native host to switch the signed runtime and operate its new page."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            os.environ["MEMSTACK_QA_BUSINESS_MARKET_CDP"]
        )
        page = browser.contexts[0].pages[0]
        page.set_default_timeout(25000)
        page.locator(".package-market-scope select").select_option("project")
        page.locator("#pm-card-memstack-" + package).click()
        running = page.locator(".pm-spec dd").first
        prior = "1.1.1" if package == "knowledge" else "1.1.0"
        if running.inner_text() != prior:
            apply(page, prior)
        apply(page, "1.2.0")
        title = "Graph entities" if package == "knowledge" else "Agent chat"
        page.locator(".pm-page-list").get_by_role("button", name=title, exact=True).click()
        expect(page.locator("main.desktop-package-workbench")).to_be_visible()
        frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        if package == "knowledge":
            search = frame.get_by_placeholder(re.compile("Search entities|搜索实体|名称或摘要"))
            search.fill("native-filter")
            expect(search).to_have_value("native-filter")
            expect(page).to_have_url(re.compile("native-filter"))
        else:
            history = frame.get_by_role("region", name=re.compile("Conversation history|会话历史"))
            expect(history).to_be_visible()
            frame.get_by_role("button", name=re.compile("Reload history|刷新历史")).click()
            expect(history).to_be_visible()
        page.get_by_role(
            "button", name=re.compile("Return to market|返回插件市场|Back to market")
        ).click()
        expect(page.locator(".pm-spec select")).to_be_visible(timeout=30000)
        more(page, "回退|回滚|Roll back")
        expect(running).to_have_text(prior, timeout=30000)
        page.locator(".pm-spec select").select_option(prior)
        if package == "knowledge":
            expect(page.locator(".pm-page-list button", has_text="Graph entities")).to_have_count(0)
        else:
            open_page(page, title)
            expect(
                frame.get_by_role("region", name=re.compile("Conversation history|会话历史"))
            ).to_have_count(0)
            detail(page)
        page.locator(".pm-back").click()


def test_signed_schedule_form_persists_and_deletes_agent_turn() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            os.environ["MEMSTACK_QA_BUSINESS_MARKET_CDP"]
        )
        page = browser.contexts[0].pages[0]
        page.set_default_timeout(30000)
        page.locator(".package-market-scope select").select_option("project")
        page.locator("#pm-card-memstack-automation").click()
        if page.locator(".pm-spec dd").first.inner_text() != "1.2.0":
            apply(page, "1.2.0")
        frame = open_page(page, "Project schedules")
        name = "Native schedule " + uuid4().hex[:10]
        schedule = frame.get_by_label(re.compile("^(Schedule|计划任务)"))
        expect(schedule.locator("option").first).to_be_attached()
        frame.get_by_label(re.compile("^(Name|名称)$")).fill(name)
        frame.get_by_label(re.compile("^(Action|任务操作)")).select_option("agent_turn")
        message = frame.get_by_label(re.compile("^(Message|消息内容)$"))
        message.fill("Native review")
        frame.get_by_label(re.compile("^(Conversation|会话)")).select_option("fresh")
        frame.get_by_role("button", name=re.compile("^Save|^保存")).click()
        expect(schedule.locator("option:checked")).to_have_text(name, timeout=20000)
        frame.get_by_role("button", name=re.compile("Refresh|刷新")).click()
        expect(message).to_have_value("Native review")
        frame.get_by_role("button", name=re.compile("^Delete schedule$|^删除计划任务$")).click()
        frame.get_by_role("button", name=re.compile("^Confirm deletion$|^确认删除$")).click()
        expect(frame.get_by_role("status")).to_contain_text(re.compile("deleted|已删除"))
        expect(schedule.locator("option", has_text=name)).to_have_count(0)
        detail(page)
