"""Install the published Workspace package into a disposable empty project through Chromium."""

import csv
import io
import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_QA_NPM_OWNER"),
        reason="requires a disposable empty project and a populated loopback npm registry",
    ),
]


def test_workspace_from_local_npm_through_web():
    account = json.loads(Path(os.environ["MEMSTACK_QA_NPM_OWNER"]).read_bytes())
    origin = os.environ.get("MEMSTACK_QA_STANDARD_ORIGIN", "http://127.0.0.1:3000")
    assert urlsplit(origin).hostname in {"127.0.0.1", "localhost", "::1"}
    query = urlencode({"project": account["project_id"]})
    path = "/api/v1/platform-plugins/v2/optional-business/"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(locale="en-US")
        page.goto(f"{origin}/?{query}")
        page.get_by_label("Email", exact=True).fill(account["email"])
        page.get_by_label("Password", exact=True).fill(account["password"])
        with page.expect_response(lambda response: urlsplit(response.url).path == path) as listing:
            page.get_by_role("button", name="Sign In", exact=True).click()
        assert listing.value.ok
        existing = listing.value.json()["items"]
        assert all(row["plugin_id"] == "memstack-workspace" for row in existing), (
            "Use a disposable project reserved for the Workspace marketplace test."
        )
        page.get_by_role("button", name="Manage plugins").click()
        market = page.get_by_test_id("plugin-market")
        market.get_by_role("button", name="Workspace", exact=True).click()
        if existing:
            market.get_by_text("More actions", exact=True).click()
            market.get_by_role("button", name="Uninstall").click()
            page.get_by_role("dialog").get_by_role("button", name="Uninstall").click()
            expect(page.get_by_role("dialog")).to_have_count(0)
        versions = market.get_by_label("Select version")
        expect(versions).to_be_visible()
        latest = versions.input_value()
        previous = next(
            option for option in versions.locator("option").all_text_contents() if option != latest
        )
        versions.select_option(previous)
        expect(market.locator(".pm-digest")).to_contain_text("sha256:")
        market.get_by_role("button", name="Install", exact=True).click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_contain_text(previous)
        with page.expect_response(lambda r: urlsplit(r.url).path == path + "npm/apply") as applied:
            dialog.get_by_role("button", name="Approve and enable").click()
        assert applied.value.ok
        active = applied.value.json()
        submitted = applied.value.request.post_data_json
        assert submitted["expected_digest"] == active["actual_digest"]
        assert submitted["project_id"] == account["project_id"]
        assert active["running_version"] == previous
        expect(dialog).to_have_count(0)
        market.get_by_role("button", name="Open feature").click()
        _export_csv(page, active["actual_digest"])
        page.go_back()
        _update_and_rollback(page, market, path, previous, latest, active["actual_digest"])
        _uninstall(page, market)
        browser.close()


def _export_csv(page, digest):
    apps = page.get_by_role("combobox", name="Applications")
    expect(apps).to_be_visible(timeout=15000)
    expect(apps.locator("option:checked")).to_have_text("Workspace directory")
    guest = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
    expect(guest.get_by_role("heading", name="Workspace directory")).to_be_visible()
    sid = uuid4().hex[:12]
    guest.get_by_label("ID", exact=True).fill(sid)
    guest.get_by_label("Name", exact=True).fill("Independent npm workspace")
    with page.expect_response(lambda r: urlsplit(r.url).path.endswith("/commands")) as executed:
        guest.get_by_role("button", name="Export CSV").click()
    assert executed.value.ok
    assert executed.value.request.post_data_json["expected_digest"] == digest
    output = guest.locator("pre")
    expect(output).to_contain_text(sid)
    rows = list(csv.DictReader(io.StringIO(output.inner_text())))
    assert rows == [
        {
            "workspace_id": sid,
            "name": "Independent npm workspace",
            "office_status": "",
            "archived": "false",
        }
    ]


def _update_and_rollback(page, market, path, previous, latest, digest):
    dialog = page.get_by_role("dialog")
    market.get_by_label("Select version").select_option(latest)
    market.get_by_role("button", name=re.compile(r"^Update to")).click()
    expect(dialog).to_contain_text(latest)
    with page.expect_response(lambda r: urlsplit(r.url).path == path + "npm/apply") as upgraded:
        dialog.get_by_role("button", name="Approve update").click()
    assert upgraded.value.ok and upgraded.value.json()["running_version"] == latest
    assert upgraded.value.json()["actual_digest"] != digest
    expect(dialog).to_have_count(0)
    market.get_by_text("More actions", exact=True).click()
    market.get_by_role("button", name=f"Roll back to {previous}").click()
    with page.expect_response(lambda r: urlsplit(r.url).path.endswith("/rollback")) as restored:
        dialog.get_by_role("button", name="Confirm").click()
    assert restored.value.ok
    expect(market.locator("dt", has_text="Running version").locator("+ dd")).to_have_text(previous)
    market.get_by_role("button", name="Open feature").click()
    _export_csv(page, digest)
    page.go_back()
    expect(dialog).to_have_count(0)


def _uninstall(page, market):
    dialog = page.get_by_role("dialog")
    menu = market.locator("details.pm-menu")
    if menu.get_attribute("open") is None:
        menu.locator("summary").click()
    menu.get_by_role("button", name="Uninstall").click()
    expect(dialog).to_contain_text("Project data is retained")
    expect(dialog).to_contain_text("Workspace directory")
    with page.expect_response(lambda r: urlsplit(r.url).path.endswith("/uninstall")) as removed:
        dialog.get_by_role("button", name="Uninstall").click()
    assert removed.value.ok
    expect(market.get_by_role("button", name="Install", exact=True)).to_be_visible()
