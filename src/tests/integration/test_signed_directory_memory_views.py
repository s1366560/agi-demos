"""Verify the installed directory and memory workbenches through their public controls."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import apply, more, open_market

pytestmark = pytest.mark.integration


def _page_button(page, package, version, title):
    page.locator(f"#pm-card-memstack-{package}").click()
    active = page.locator(".pm-spec dd").first
    expect(active).to_be_visible(timeout=60000)
    if active.inner_text() != version:
        apply(page, version)
    return page.locator(".pm-page-list").get_by_role("button", name=title, exact=True)


def _guest(page):
    return page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")


def _open_web(playwright):
    owner = os.getenv("MEMSTACK_QA_MARKET_FULL_OWNER")
    if not owner:
        pytest.skip("requires a disposable local full-workbench project")
    origin = os.getenv("MEMSTACK_QA_MARKET_FULL_ORIGIN", "http://127.0.0.1:3000")
    assert urlsplit(origin).hostname in {"localhost", "127.0.0.1", "::1"}
    account = json.loads(Path(owner).read_bytes())
    page = playwright.chromium.launch().new_context(locale="en-US").new_page()
    page.set_default_timeout(60000)
    open_market(page, "full", origin, account)
    base = f"{origin}/tenant/{account['tenant_id']}/project/{account['project_id']}"
    return page, base


def _native_market(page):
    back = page.get_by_role("button", name=re.compile("返回插件市场|Back to marketplace"))
    if back.is_visible():
        back.click()
    page.locator(".package-market-scope select").select_option("project")
    if page.locator(".pm-back").is_visible():
        page.locator(".pm-back").click()


def test_installed_web_directory_search_and_open_card():
    with sync_playwright() as pw:
        page, _ = _open_web(pw)
        _page_button(page, "workspace", "1.4.1", "Workspace directory").click()
        guest = _guest(page)
        card = guest.locator("li a[aria-label]").first
        expect(card).to_be_visible(timeout=60000)
        title = card.get_attribute("aria-label")
        guest.locator("#workspace-search-input").fill(title)
        expect(page).to_have_url(re.compile(r"[?&]q="))
        page.reload()
        expect(guest.locator("#workspace-search-input")).to_have_value(title, timeout=60000)
        guest.get_by_role("link", name=title, exact=True).first.click()
        expect(guest.get_by_role("heading", name=title, exact=True)).to_be_visible(timeout=60000)


def _create_memory(guest):
    title = "Original workbench " + uuid4().hex[:10]
    guest.get_by_label(re.compile("^(Title|标题)$")).fill(title)
    guest.get_by_label(re.compile("^(Content|正文)$")).fill(
        "Content from the installed memory page"
    )
    guest.get_by_role("button", name=re.compile("Save memory|保存记忆")).click()
    return title


def test_installed_web_memory_search_and_detail():
    with sync_playwright() as pw:
        page, _ = _open_web(pw)
        _page_button(page, "knowledge", "1.4.0", "Project memories").click()
        guest = _guest(page)
        guest.get_by_role(
            "link", name=re.compile("Add Memory|Create Memory|添加记忆|创建记忆", re.I)
        ).first.click()
        title = _create_memory(guest)
        expect(guest.get_by_role("tabpanel")).to_contain_text(
            "Content from the installed memory page", timeout=60000
        )
        guest.get_by_role("tab", name=re.compile("Metadata|元数据")).click()
        expect(page).to_have_url(re.compile(r"tab=metadata"))
        page.reload()
        expect(guest.get_by_role("tab", name=re.compile("Metadata|元数据"))).to_have_attribute(
            "aria-selected", "true", timeout=60000
        )
        guest.locator('a[href$="/memories"]').click()
        field = guest.get_by_role("searchbox")
        field.fill(title)
        expect(page).to_have_url(re.compile(r"[?&]q="))
        guest.get_by_role("link", name=title, exact=True).click()
        expect(guest.get_by_role("tabpanel")).to_contain_text(
            "Content from the installed memory page", timeout=60000
        )

        guest.get_by_role("button", name=re.compile("Edit memory|编辑记忆", re.I)).click()
        dialog = guest.get_by_role("dialog")
        dialog.locator("textarea").first.fill("Edited from the original memory modal")
        dialog.get_by_role("button", name=re.compile("Save changes|保存更改", re.I)).click()
        expect(dialog).to_have_count(0, timeout=30000)
        expect(guest.get_by_role("tabpanel")).to_contain_text(
            "Edited from the original memory modal"
        )


def test_installed_native_directory_and_memory_detail():
    endpoint = os.getenv("MEMSTACK_QA_ORIGINAL_PAGES_CDP")
    if not endpoint:
        pytest.skip("requires an isolated native Electron project marketplace")
    assert urlsplit(endpoint).hostname in {"localhost", "127.0.0.1", "::1"}
    with sync_playwright() as pw:
        page = pw.chromium.connect_over_cdp(endpoint).contexts[0].pages[0]
        page.set_default_timeout(60000)
        _native_market(page)
        _page_button(page, "workspace", "1.4.1", "Workspace directory").click()
        guest = _guest(page)
        card = guest.locator(".tenant-workspaces-grid article").first
        expect(card).to_be_visible(timeout=60000)
        title = card.locator("h2").inner_text()
        card.get_by_role("button").click()
        guest.get_by_role("link", name=re.compile("Workspace details|工作区详情")).click()
        expect(guest.get_by_role("heading", name=title)).to_be_visible(timeout=30000)
        _native_market(page)
        _page_button(page, "knowledge", "1.4.0", "Memory editor").click()
        title = _create_memory(guest)
        expect(guest.get_by_label(re.compile("^(Title|标题)$"))).to_have_value(title)
        _native_market(page)
        _page_button(page, "knowledge", "1.4.0", "Project memories").click()
        item = guest.locator(".cloud-memories-page li").filter(has_text=title)
        item.get_by_role("button", name=re.compile("View|查看")).click()
        expect(guest.locator(".cloud-memory-editor h2")).to_have_text(title, timeout=60000)
        expect(guest.locator(".cloud-memory-body")).to_have_text(
            "Content from the installed memory page"
        )


@pytest.mark.parametrize(
    ("package", "previous", "current", "page_name", "old_control", "new_control"),
    [
        ("workspace", "1.3.2", "1.4.1", "Workspace directory", "table", "#workspace-search-input"),
        (
            "knowledge",
            "1.3.0",
            "1.4.0",
            "Project memories",
            "form input[type=search]",
            "a[href$='/memories/new']",
        ),
    ],
)
def test_restore_installed_directory_after_rollback(
    package, previous, current, page_name, old_control, new_control
):
    with sync_playwright() as pw:
        page, _ = _open_web(pw)
        button = _page_button(page, package, previous, page_name)
        detail_url = page.url
        apply(page, current)
        more(page, rf"Roll back to {re.escape(previous)}|回退至 {re.escape(previous)}")
        expect(page.locator(".pm-spec dd").first).to_have_text(previous, timeout=60000)
        guest = _guest(page)
        try:
            button.click()
            expect(guest.locator(old_control).first).to_be_visible(timeout=60000)
        finally:
            page.goto(detail_url)
            apply(page, current)
        button.click()
        expect(guest.locator(new_control).first).to_be_visible(timeout=60000)
