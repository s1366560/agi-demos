"""Exercise original installed business controls on disposable full clients."""

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
)
from src.tests.integration.test_signed_directory_memory_views import (
    _guest,
    _native_market,
    _open_web,
    _page_button,
)

pytestmark = pytest.mark.integration
RELEASES = {name: business_release(name) for name in ("workspace", "knowledge")}


def _client(playwright, client):
    if client == "web":
        return _open_web(playwright)[0]
    endpoint = os.getenv("MEMSTACK_QA_ORIGINAL_PAGES_CDP")
    if not endpoint:
        pytest.skip("requires an isolated native Electron project marketplace")
    assert urlsplit(endpoint).hostname in {"localhost", "127.0.0.1", "::1"}
    page = playwright.chromium.connect_over_cdp(endpoint).contexts[0].pages[0]
    page.set_default_timeout(60000)
    owner = json.loads(Path(os.environ["MEMSTACK_QA_MARKET_FULL_OWNER"]).read_bytes())
    page.evaluate(
        "(tenant) => {location.hash = '/tenant/' + tenant + '/plugins?marketScope=project'}",
        owner["tenant_id"],
    )
    _native_market(page)
    return page


@pytest.mark.parametrize("client", ["web", "desktop"])
@pytest.mark.parametrize(
    ("package", "previous", "entry"),
    [
        ("knowledge", "1.4.0", "Memory editor"),
        ("workspace", "1.4.1", "Workspace directory"),
    ],
)
def test_restore_original_release(client, package, previous, entry):
    with sync_playwright() as pw:
        page = _client(pw, client)
        card = page.locator(f"#pm-card-memstack-{package}")
        card.click()
        install_previous(page, previous)
        button = page.locator(".pm-page-list").get_by_role("button", name=entry, exact=True)
        detail_hash = urlsplit(page.url).fragment
        apply(page, RELEASES[package])
        more(page, rf"Roll back to {re.escape(previous)}|回退至 {re.escape(previous)}")
        expect(page.locator(".pm-spec dd").first).to_have_text(previous, timeout=60000)
        button.click()
        guest = _guest(page)
        if package == "knowledge":
            expect(guest.get_by_label(re.compile("^(Title|标题)$"))).to_be_visible(timeout=60000)
            expect(guest.locator("#memory-title, .cloud-memory-editor input")).to_have_count(0)
        else:
            _open_first_workspace(guest, client)
            expect(guest.locator("h1,h2").first).to_be_visible(timeout=60000)
            expect(guest.get_by_role("tab", name=re.compile("Discussion|讨论"))).to_have_count(0)
        if client == "web":
            page.get_by_role("link", name="Back to plugin marketplace").click()
        else:
            page.evaluate("(hash) => {location.hash = hash}", detail_hash)
        detail = page.locator(".pm-spec")
        detail.or_(card).first.wait_for(timeout=60000)
        if not detail.is_visible():
            card.click()
        expect(detail).to_be_visible(timeout=60000)
        apply(page, RELEASES[package])
        button.click()
        if package == "knowledge":
            selector = "#memory-title" if client == "web" else ".cloud-memory-editor input"
            expect(guest.locator(selector)).to_be_visible(timeout=60000)
        else:
            _open_first_workspace(guest, client)
            expect(guest.get_by_role("tab", name=re.compile("Discussion|讨论"))).to_be_visible(
                timeout=60000
            )


def _open_first_workspace(guest, client):
    if client == "web":
        guest.locator("li a[aria-label]").first.click()
    else:
        guest.locator(".tenant-workspaces-grid article").first.get_by_role("button").click()


def test_write_objective_in_original_blackboard():
    with sync_playwright() as pw:
        page = _client(pw, "web")
        _page_button(page, "workspace", RELEASES["workspace"], "Workspace directory").click()
        guest = _guest(page)
        guest.locator("li a[aria-label]").first.click()
        guest.get_by_role("button", name="Add Objective", exact=True).click()
        dialog = guest.get_by_role("dialog")
        title = "QA signed workspace objective " + uuid4().hex[:8]
        dialog.get_by_role("textbox").first.fill(title)
        dialog.get_by_role("button", name="Create", exact=True).click()
        expect(guest.get_by_text(title, exact=True).first).to_be_visible(timeout=60000)
        page.reload()
        expect(guest.get_by_text(title, exact=True).first).to_be_visible(timeout=60000)


def test_native_memory_create_reindex_and_delete():
    with sync_playwright() as pw:
        page = _client(pw, "desktop")
        _page_button(page, "knowledge", RELEASES["knowledge"], "Memory editor").click()
        guest = _guest(page)
        editor = guest.locator(".cloud-memory-editor")
        title = "QA signed native memory " + uuid4().hex[:8]
        editor.locator("input").fill(title)
        editor.locator("textarea").fill("Created in the original native form.")
        editor.locator("button[type=submit]").click()
        row = guest.locator("li").filter(has_text=title)
        expect(row.locator("h2")).to_have_text(title, timeout=60000)
        retry = row.get_by_role("button", name=re.compile("Reindex|重新索引", re.I))
        for _ in range(40):
            if retry.is_enabled():
                break
            page.wait_for_timeout(3000)
            guest.get_by_role("button", name=re.compile("^(Refresh|刷新)$")).click()
            expect(guest.get_by_role("button", name=re.compile("^(Refresh|刷新)$"))).to_be_enabled(
                timeout=60000
            )
        retry.click()
        expect(retry).to_be_disabled(timeout=30000)
        expect(guest.get_by_role("button", name=re.compile("^(Refresh|刷新)$"))).to_be_enabled(
            timeout=60000
        )
        expect(guest.get_by_role("alert")).to_have_count(0)
        row.get_by_role("button", name=re.compile("^(Delete|删除)$")).click()
        editor.get_by_role("button", name=re.compile("Confirm delet|确认删除", re.I)).click()
        expect(row).to_have_count(0, timeout=120000)


def test_web_editor_reindex_and_delete_memory():
    with sync_playwright() as pw:
        page, base = _open_web(pw)
        _page_button(page, "knowledge", RELEASES["knowledge"], "Memory editor").click()
        guest = _guest(page)
        title = "QA signed web memory " + uuid4().hex[:8]
        guest.locator("#memory-title").fill(title)
        guest.locator("textarea").fill("A record created from the installed original form.")

        def accepted(command):
            return (
                lambda r: r.url.endswith("/commands")
                and r.request.post_data_json.get("command_id") == command
            )

        with page.expect_response(accepted("save-memory"), timeout=60000) as saved:
            guest.get_by_role("button", name="Save Memory", exact=True).click()
        assert saved.value.ok
        memory = saved.value.json()
        page.goto(base + "/memory/" + memory["id"])
        retry = guest.get_by_role("button", name=re.compile("Reprocess|Reindex", re.I))
        expect(retry).to_be_visible(timeout=60000)
        for _ in range(40):
            if retry.is_enabled():
                break
            page.wait_for_timeout(3000)
            page.reload()
            expect(retry).to_be_visible(timeout=60000)
        with page.expect_response(accepted("reindex-memory"), timeout=60000) as indexing:
            retry.click()
        assert indexing.value.ok, indexing.value.status
        completed = guest.get_by_text("Completed", exact=True).first
        expect(completed).to_be_visible(timeout=120000)
        # A reload reads the persisted memory and its revision through the installed package.
        page.reload()
        expect(completed).to_be_visible(timeout=60000)
        guest.get_by_role("button", name="Delete", exact=True).click()
        with page.expect_response(accepted("delete-memory"), timeout=60000) as removed:
            guest.get_by_role("dialog").get_by_role("button", name="Delete", exact=True).click()
        assert removed.value.ok, removed.value.status


def test_native_blackboard_post_is_retained():
    with sync_playwright() as pw:
        page = _client(pw, "desktop")
        _page_button(page, "workspace", RELEASES["workspace"], "Workspace directory").click()
        guest = _guest(page)
        guest.locator(".tenant-workspaces-grid article").first.get_by_role("button").click()
        tab = guest.get_by_role("tab", name=re.compile("Discussion|讨论"))
        tab.click()
        panel = guest.get_by_role("tabpanel")
        title = "QA signed native discussion " + uuid4().hex[:8]
        panel.locator("form input").first.fill(title)
        panel.locator("form textarea").first.fill(
            "Posted from the installed native collaboration canvas."
        )
        panel.get_by_role("button", name=re.compile("Publish|发布")).first.click()
        expect(panel.get_by_text(title, exact=True).first).to_be_visible(timeout=120000)
        page.reload()
        tab.click()
        expect(panel.get_by_text(title, exact=True).first).to_be_visible(timeout=60000)


def test_web_blackboard_upload_and_preview_chunks():
    with sync_playwright() as pw:
        page = _client(pw, "web")
        _page_button(page, "workspace", RELEASES["workspace"], "Workspace directory").click()
        guest = _guest(page)
        guest.locator("li a[aria-label]").first.click()
        guest.get_by_role("tab", name=re.compile("Files")).click()
        region = guest.get_by_role("region", name="Shared files")
        name = "QA-board-" + uuid4().hex[:8] + ".txt"
        data = "Signed file begin\n" + "workspace content\n" * 3300 + "Signed file end"
        region.locator("input[type=file]").set_input_files(
            {"name": name, "mimeType": "text/plain", "buffer": data.encode()}
        )
        region.get_by_role("button", name=name, exact=True).click(timeout=90000)
        expect(guest.get_by_role("dialog").locator("pre")).to_have_text(data, timeout=90000)


def test_web_opens_installed_agent_from_original_board():
    with sync_playwright() as pw:
        page = _client(pw, "web")
        page.locator("#pm-card-memstack-agent").click()
        versions = page.locator(".pm-spec select")
        release = versions.input_value()
        active = page.locator(".pm-spec dd").first
        if active.inner_text() != release:
            apply(page, release)
        page.locator(".pm-back").click()
        _page_button(page, "workspace", RELEASES["workspace"], "Workspace directory").click()
        guest = _guest(page)
        guest.locator("li a[aria-label]").first.click()
        guest.get_by_role("link", name="Open in Agent Workspace").click()
        expect(page.locator('iframe[title="Agent chat"][data-page-ready=true]')).to_be_visible(
            timeout=60000
        )


def test_web_graph_loads_through_installed_original_controls():
    with sync_playwright() as pw:
        page = _client(pw, "web")
        _page_button(page, "knowledge", RELEASES["knowledge"], "Knowledge graph").click()
        view = _guest(page).get_by_test_id("memory-graph-page")
        expect(view).to_be_visible(timeout=60000)
        with page.expect_response(
            lambda response: response.url.endswith("/commands")
            and response.request.method == "POST"
            and response.request.post_data_json.get("command_id") == "read-graph",
            timeout=60000,
        ) as pending:
            view.get_by_role("button", name="Reload Data").click()
        response = pending.value
        assert response.ok, response.status
        elements = response.json()["elements"]
        assert isinstance(elements["nodes"], list) and isinstance(elements["edges"], list)
        nodes = view.get_by_role("table", name="Graph nodes")
        expect(nodes.locator("tbody tr")).to_have_count(len(elements["nodes"]))


def test_native_graph_refreshes_installed_original_projection():
    with sync_playwright() as pw:
        page = _client(pw, "desktop")
        _page_button(page, "knowledge", RELEASES["knowledge"], "Knowledge graph").click()
        view = _guest(page).locator(".project-graph-page")
        expect(
            view.get_by_role("heading", name=re.compile("Knowledge graph|知识图谱"))
        ).to_be_visible(timeout=60000)
        counts = view.locator(".project-graph-summary strong")
        expect(counts).to_have_count(2, timeout=60000)
        refresh = view.get_by_role("button", name=re.compile("^(Refresh|刷新)$"))
        refresh.click()
        expect(refresh).to_be_enabled(timeout=60000)
        expect(counts.first).to_have_text(re.compile(r"^\d+$"))
        expect(counts.last).to_have_text(re.compile(r"^\d+$"))
