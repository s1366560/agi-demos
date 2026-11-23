"""Install the published Workspace package into a disposable empty project through Chromium."""

import csv
import hashlib
import io
import json
import os
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
        assert all(
            row["plugin_id"] == "memstack-workspace" and row["version"] == "1.0.2"
            for row in existing
        ), "Use a disposable project consisting only of this test's own release."
        if not existing:
            expect(
                page.get_by_text("This project has no available application pages.")
            ).to_be_visible()
        page.get_by_role("button", name="Manage plugins").click()
        panel = page.get_by_test_id("optional-business-panel")
        expect(panel).to_have_attribute("data-project", account["project_id"])
        panel.get_by_label("npm package name").fill("@memstack/workspace")
        panel.get_by_label("Exact npm version").fill("1.0.2")
        with page.expect_response(lambda r: urlsplit(r.url).path == path + "npm/resolve") as read:
            panel.get_by_role("button", name="Preview signed package").click()
        assert read.value.ok
        candidate = read.value.json()
        assert candidate["version"] == "1.0.2" and candidate["plugin_id"] == "memstack-workspace"
        approval = panel.get_by_text(candidate["digest"], exact=False)
        for permission in candidate["permissions"]:
            expect(approval).to_contain_text(permission)
        with page.expect_response(lambda r: urlsplit(r.url).path == path + "install") as installed:
            panel.get_by_test_id("optional-business-install").click()
        assert installed.value.ok
        submitted = installed.value.request.post_data_json
        assert submitted["project_id"] == account["project_id"]
        assert submitted["approved_permissions"] == candidate["permissions"]
        assert (
            hashlib.sha256(submitted["archive_base64"].encode()).digest()
            == hashlib.sha256(candidate["archive_base64"].encode()).digest()
        )
        with page.expect_response(lambda r: urlsplit(r.url).path.endswith("/enable")) as enabled:
            panel.get_by_test_id("optional-business-enable").click()
        assert enabled.value.ok
        _export_csv(page, candidate["digest"])
        browser.close()


def _export_csv(page, digest):
    apps = page.get_by_role("combobox", name="Applications")
    expect(apps).to_be_visible(timeout=15000)
    apps.select_option(label="Workspace directory")
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
