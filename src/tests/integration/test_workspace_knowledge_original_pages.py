"""Exercise the original Web and Electron views installed from the loopback registry."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import expect, sync_playwright

from src.tests.integration.marketplace_browser import apply, open_market

pytestmark = pytest.mark.integration


def _command(name):
    return lambda response: (
        urlsplit(response.url).path.endswith("/commands")
        and response.request.method == "POST"
        and response.request.post_data_json.get("command_id") == name
    )


def _open(page, package, title):
    page.locator(f"#pm-card-memstack-{package}").click()
    active = page.locator(".pm-spec dd").first
    expect(active).to_be_visible(timeout=60000)
    version = "1.3.2" if package == "workspace" else "1.3.0"
    if active.inner_text() != version:
        apply(page, version)
    return page.locator(".pm-page-list").get_by_role("button", name=title, exact=True)


@pytest.mark.parametrize("package", ["workspace", "knowledge"])
@pytest.mark.parametrize("host", ["web", "desktop"])
def test_installed_original_page(package, host):
    with sync_playwright() as playwright:
        if host == "web":
            owner = os.getenv("MEMSTACK_QA_MARKET_FULL_OWNER")
            if not owner:
                pytest.skip("requires a disposable local full-workbench project")
            origin = os.getenv("MEMSTACK_QA_MARKET_FULL_ORIGIN", "http://127.0.0.1:3000")
            assert urlsplit(origin).hostname in {"localhost", "127.0.0.1", "::1"}
            browser = playwright.chromium.launch()
            page = browser.new_page(locale="en-US")
            catalog = open_market(page, "full", origin, json.loads(Path(owner).read_bytes()))
            assert urlsplit(catalog.json()["source"]).hostname in {"localhost", "127.0.0.1", "::1"}
        else:
            endpoint = os.getenv("MEMSTACK_QA_ORIGINAL_PAGES_CDP")
            if not endpoint:
                pytest.skip("requires an isolated native Electron project marketplace")
            assert urlsplit(endpoint).hostname in {"localhost", "127.0.0.1", "::1"}
            browser = playwright.chromium.connect_over_cdp(endpoint)
            page = browser.contexts[0].pages[0]
            back = page.get_by_role("button", name=re.compile("返回插件市场|Back to marketplace"))
            if back.is_visible():
                back.click()
            page.locator(".package-market-scope select").select_option("project")
            if page.locator(".pm-back").is_visible():
                page.locator(".pm-back").click()
        page.set_default_timeout(60000)
        guest = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        if package == "knowledge":
            _entities(page, guest, host)
        else:
            _create_workspace(page, guest, host)


def _entities(page, guest, host):
    button = _open(page, "knowledge", "Graph entities")
    if host == "web":
        with page.expect_response(_command("list-entities")) as loaded:
            button.click()
        assert loaded.value.ok
        search = guest.get_by_role("textbox")
        search.fill("original-page")
        expect(page).to_have_url(re.compile(r"[?&]q=original-page(&|$)"))
        page.reload()
        expect(search).to_have_value("original-page")
    else:
        button.click()
        section = guest.locator('section[data-authority="cloud"]')
        expect(section).to_have_attribute(
            "data-state", re.compile("^(empty|ready)$"), timeout=30000
        )
        expect(section.get_by_role("heading").first).to_have_text("project-project-entities")
        expect(section.locator("output").first).to_have_text(re.compile(r"^\d+$"))


def _check_host_appearance(page, guest, control):
    """Switch the isolated test host presentation, leaving account preferences intact."""
    root = page.locator("html")
    original = root.evaluate("(el) => [el.dataset.theme ?? null, el.classList.contains('dark')]")
    frame_root = guest.locator("html")
    try:
        for appearance in ("dark", "light"):
            root.evaluate(
                "(el, theme) => {el.dataset.theme = theme; el.classList.toggle('dark', theme === 'dark')}",
                appearance,
            )
            expect(frame_root).to_have_attribute("data-theme", appearance)
            desktop = bool(guest.locator(".radix-themes").count())
            if desktop:
                expect(guest.locator(".radix-themes").first).to_have_class(
                    re.compile(rf"\b{appearance}\b")
                )
            intensity = (
                (16 if desktop else 24) if appearance == "dark" else (240 if desktop else 255)
            )
            expect(control).to_have_css(
                "background-color", f"rgb({intensity}, {intensity}, {intensity})"
            )
    finally:
        root.evaluate(
            "(el, [theme, dark]) => {if (theme === null) delete el.dataset.theme; "
            "else el.dataset.theme = theme; el.classList.toggle('dark', dark)}",
            original,
        )


def _create_workspace(page, guest, host):
    _open(page, "workspace", "Create workspace").click()
    name = "Original UI " + uuid4().hex[:12]
    if host == "web":
        field = guest.locator("#workspace-name-input")
        expect(field).to_be_visible(timeout=20000)
        _check_host_appearance(page, guest, field)
        field.fill(name)
        guest.locator("#workspace-description-input").fill("Exercise the installed workspace")
        guest.get_by_role("radio", name=re.compile("Research|研究")).click()
        guest.get_by_role("radio", name=re.compile("Shared team|共享团队")).click()
        with page.expect_response(_command("create-workspace")) as created:
            guest.locator('button[form="workspace-create-form"]').click()
        assert created.value.ok, created.value.status
        result = created.value.json()
        assert result["name"] == name
        expect(page).to_have_url(re.compile(re.escape(result["id"])))
    else:
        dialog = guest.get_by_role("dialog")
        expect(dialog).to_be_visible(timeout=20000)
        _check_host_appearance(page, guest, dialog)
        dialog.get_by_role("textbox").nth(0).fill(name)
        dialog.get_by_role("textbox").nth(1).fill("Exercise the native workspace dialog")
        dialog.get_by_role("radio", name=re.compile("Research|研究")).click()
        dialog.get_by_role("radio", name=re.compile("Shared agents|共享")).click()
        dialog.locator('button[type="submit"]').click()
        expect(guest.get_by_role("heading", name=name, exact=True)).to_be_visible(timeout=30000)


@pytest.mark.parametrize(("package", "current"), [("workspace", "1.3.2"), ("knowledge", "1.3.0")])
def test_project_marketplace_restores_original_package_after_rollback(package, current):
    from src.tests.integration.marketplace_browser import more

    owner = os.getenv("MEMSTACK_QA_MARKET_FULL_OWNER")
    if not owner:
        pytest.skip("requires a disposable local full-workbench project")
    origin = os.getenv("MEMSTACK_QA_MARKET_FULL_ORIGIN", "http://127.0.0.1:3000")
    assert urlsplit(origin).hostname in {"localhost", "127.0.0.1", "::1"}
    with sync_playwright() as playwright:
        page = playwright.chromium.launch().new_page(locale="en-US")
        page.set_default_timeout(60000)
        open_market(page, "full", origin, json.loads(Path(owner).read_bytes()))
        page.locator(f"#pm-card-memstack-{package}").click()
        active = page.locator(".pm-spec dd").first
        expect(active).to_be_visible(timeout=60000)
        detail_url = page.url
        if active.inner_text() != "1.2.0":
            apply(page, "1.2.0")
        apply(page, current)
        with page.expect_response(
            lambda res: urlsplit(res.url).path.endswith(f"/memstack-{package}/rollback")
        ) as rollback:
            more(page, r"Roll back to 1\.2\.0|回退至 1\.2\.0")
        assert rollback.value.ok
        expect(active).to_have_text("1.2.0", timeout=60000)
        try:
            if package == "workspace":
                page.locator(".pm-page-list").get_by_role("button", name="Create workspace").click()
                guest = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
                expect(guest.get_by_label(re.compile("Use case|使用场景"))).to_have_js_property(
                    "tagName", "SELECT"
                )
        finally:
            if package == "workspace":
                page.goto(detail_url)
                expect(active).to_be_visible(timeout=60000)
            apply(page, current)
        expect(active).to_have_text(current)
