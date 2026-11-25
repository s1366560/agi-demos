"""Save a real workspace directory export from an installed page in both clients."""

import csv
import io
import json
import os
import re
from pathlib import Path
from time import monotonic, sleep

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

from scripts.dev.verify_six_workbenches import native_window
from src.tests.integration.marketplace_browser import business_release
from src.tests.integration.test_signed_sidebar import BASE, login, qa_workspace

pytestmark = pytest.mark.integration
WORKSPACE = 'CSV 导出, "QA"'


@pytest.fixture
def installed_export():
    owner_file = os.getenv("MEMSTACK_QA_EXPORT_OWNER")
    if not owner_file:
        pytest.skip("requires an isolated project and a local npm source")
    owner = json.loads(Path(owner_file).read_bytes())
    scope = {key: owner[key] for key in ("tenant_id", "project_id")}
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=120) as api:
        login_result = api.post(
            "/auth/token", data={"username": owner["email"], "password": owner["password"]}
        )
        login_result.raise_for_status()
        api.headers["authorization"] = "Bearer " + login_result.json()["access_token"]
        source = {"package_name": "@memstack/workspace", "version": business_release("workspace")}
        detail = api.get(
            BASE + "/npm/detail", params={**scope, **source, "plugin_id": "memstack-workspace"}
        )
        detail.raise_for_status()
        details = detail.json()
        release = details["release"]
        if (details.get("installation") or {}).get("actual_digest") != release["digest"]:
            applied = api.post(
                BASE + "/npm/apply",
                json={
                    **scope,
                    **source,
                    "expected_revision": details["desired_revision"],
                    "expected_digest": release["digest"],
                    "approved_permissions": release["permissions"],
                },
            )
            applied.raise_for_status()
        work_id = qa_workspace(api, scope, WORKSPACE)
    route = f"/tenant/{scope['tenant_id']}/project/{scope['project_id']}/workspaces/export"
    return owner, route, work_id


def preview(page):
    guest = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
    browse = guest.get_by_role("button", name=re.compile("Load project directory|读取项目目录"))
    browse.click()
    expect(browse).to_be_enabled(timeout=90000)
    # The directory replaces its initial empty editor asynchronously.
    expect(guest.get_by_role("textbox", name=re.compile("^Name$|^名称$")).first).not_to_have_value(
        "", timeout=30000
    )
    export = guest.get_by_role("button", name=re.compile("^Export CSV$|^导出 CSV$"))
    export.click()
    expect(export).to_be_enabled(timeout=90000)
    expect(guest.locator("pre")).to_contain_text("QA", timeout=30000)
    return guest.get_by_role("button", name=re.compile("Save CSV file|保存 CSV 文件"))


def verify_file(path, workspace_id):
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    assert any(row["name"] == WORKSPACE and workspace_id in row.values() for row in rows)


def test_fixed_web_workspace_csv_save_and_cancel(installed_export, tmp_path):
    owner, route, work_id = installed_export
    origin = os.getenv("MEMSTACK_QA_VERTICAL_ORIGIN")
    if not origin:
        pytest.skip("requires the fixed web host")
    assert re.fullmatch(r"http://(?:localhost|127\.0\.0\.1):\d+", origin)
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page(locale="en-US", accept_downloads=True)
        login(page, origin, owner)
        page.goto(origin + route)
        save = preview(page)
        downloads = []
        page.on("download", lambda download: downloads.append(download))
        save.click()
        dialog = page.get_by_role("dialog", name="Save exported file")
        dialog.get_by_role("button", name="Cancel").click(timeout=90000)
        expect(dialog).to_have_count(0)
        assert not downloads
        save.click()
        with page.expect_download(timeout=90000) as pending:
            dialog.get_by_role("link", name="Download CSV").click(timeout=90000)
        download = pending.value
        assert download.suggested_filename == "export.csv"
        output = tmp_path / "download.csv"
        download.save_as(output)
        verify_file(output, work_id)


def test_fixed_electron_workspace_csv_save_and_cancel(installed_export, tmp_path, monkeypatch):
    owner, route, work_id = installed_export
    if not (artifacts := os.getenv("MEMSTACK_QA_EXPORT_ARTIFACTS")):
        pytest.skip("requires the fixed desktop build")
    # Only the OS file picker decision is supplied. IPC, owner validation, name validation and
    # native file writing all execute in the unmodified Electron application.
    marker, output = tmp_path / "dialog.log", tmp_path / "selected.csv"
    hook = tmp_path / "choose-test-target.cjs"
    hook.write_text("""
if (process.versions.electron && process.type === 'browser') {
  setImmediate(() => {
    const { dialog } = require('electron');
    const { appendFileSync } = require('node:fs');
    let calls = 0;
    dialog.showSaveDialog = async (window, options) => {
      if (!window || window.isDestroyed() || options.defaultPath !== 'export.csv')
        throw Error('unexpected native file dialog');
      calls++;
      appendFileSync(process.env.TEST_PICKER_MARKER, 'dialog\\n');
      return calls === 1 ? { canceled: true } :
        { canceled: false, filePath: process.env.TEST_PICKER_DESTINATION };
    };
    appendFileSync(process.env.TEST_PICKER_MARKER, 'ready\\n');
  });
}
""")
    monkeypatch.setenv("TEST_PICKER_MARKER", str(marker))
    monkeypatch.setenv("TEST_PICKER_DESTINATION", str(output))
    monkeypatch.setenv("NODE_OPTIONS", "--require=" + str(hook))
    with (
        native_window(Path(artifacts), tmp_path / "electron.log", owner, True) as cdp,
        sync_playwright() as pw,
    ):
        assert marker.is_file() and "ready" in marker.read_text()
        page = pw.chromium.connect_over_cdp(cdp).contexts[0].pages[0]
        page.locator(".package-market-scope select").select_option("project")
        page.evaluate("path=>{location.hash=path}", route)
        save = preview(page)
        save.click()
        expect(save).to_be_enabled(timeout=90000)
        deadline = monotonic() + 10
        while not marker.read_text().count("dialog") and monotonic() < deadline:
            sleep(0.1)
        assert marker.read_text().count("dialog") == 1 and not output.exists()
        save.click()
        expect(save).to_be_enabled(timeout=90000)
        deadline = monotonic() + 10
        while not output.exists() and monotonic() < deadline:
            sleep(0.1)
        assert marker.read_text().count("dialog") == 2 and output.is_file()
        verify_file(output, work_id)
