"""Exercise two newly signed releases in a running, fixed Electron host and disposable project."""

import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from playwright.sync_api import Error as BrowserError, Page, expect, sync_playwright

from src.tests.integration.rich_page_publisher import publish_page

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_QA_NATIVE_CDP"),
        reason="requires make -C agi-stack run-desktop in a disposable native profile",
    ),
]

BASE = "/api/v1/platform-plugins/v2/optional-business"


class PackageSession:
    def __init__(self, page: Page, scope: dict[str, str], plugin: str) -> None:
        self.page = page
        self.scope = scope
        self.plugin = plugin

    def bridge(self, command, data):
        return self.page.evaluate(
            "([command, data]) => window.__MEMSTACK_DESKTOP__.core.invoke(command, data)",
            [command, data],
        )

    def cloud(self, path, body=None):
        response = self.bridge(
            "cloud_request",
            {
                "requestId": str(uuid4()),
                "request": {"path": path, "method": "GET"}
                if body is None
                else {
                    "path": path,
                    "method": "POST",
                    "body": self.scope | body,
                },
            },
        )
        assert response["status"] // 100 == 2, response["status"]
        return response["body"]

    def record(self):
        rows = self.cloud(BASE + "/?" + urlencode(self.scope))["items"]
        return next(r for r in rows if r["plugin_id"] == self.plugin)

    def change(self, action):
        self.cloud(
            f"{BASE}/{self.plugin}/{action}",
            {"expected_revision": self.record()["desired_revision"]},
        )

    def install(self, archive):
        review = self.cloud(BASE + "/inspect", {"archive_base64": archive})
        self.cloud(
            BASE + "/install",
            {"archive_base64": archive, "approved_permissions": review["permissions"]},
        )
        if self.record()["running_version"] != review["version"]:
            self.change("enable")

    def device(self, action, token=None, **fields):
        return self.bridge(
            "device_plugin_manage_v2",
            {
                "input": {
                    **self.scope,
                    "plugin_id": self.plugin,
                    "context_token": token,
                    "operation": {"action": action, **fields},
                },
            },
        )

    def approve(self, archive):
        ctx = self.device("list")["context_token"]
        preview = self.device("inspect", ctx, archive_base64=archive)
        row = self.device(
            "install",
            ctx,
            archive_base64=archive,
            reference=preview["reference"],
            approved_permissions=preview["declared_permissions"],
            approve_for_day=True,
        )
        return ctx, {"grant_id": row["grant_id"], "reference": row["reference"]}

    def invoke_stale(self, handle):
        ctx, args = handle
        with pytest.raises(BrowserError, match="device_plugin_(context_changed|grant_denied)"):
            self.device("invoke", ctx, **args, tool="device_label", input={})

    def page_results(self, version):
        self.page.evaluate("path => { location.hash = path; }", f"/{self.plugin}/labels")
        frame = self.page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        expect(frame.get_by_role("heading", name=f"Inventory labels {version}")).to_be_visible(
            timeout=20000
        )
        for index, (label, target) in enumerate(
            (("Cloud", "python"), ("Device", "desktop-sidecar"))
        ):
            frame.get_by_role("button", name=f"{label} label").click()
            expect(frame.locator("output").nth(index)).to_contain_text(
                f"{target}-{version}", timeout=10000
            )


def sign_in(page, api, owner):
    page.locator("[name=origin]").fill(api)
    page.locator("[name=email]").fill(owner["email"])
    page.locator("[name=password]").fill(owner["password"])
    page.locator("form button").click()


def verify_account_switch(session, api, owner, second, handle):
    page = session.page
    page.locator("header button").click()
    expect(page.locator("form button")).to_be_enabled()
    expect(page.locator("iframe")).to_have_count(0)
    sign_in(page, api, second)
    picker = page.locator("main > label select")
    project = second["project_id"]
    expect(picker.locator(f'option[value="{project}"]')).to_be_attached()
    if picker.input_value() != project:
        picker.select_option(project)
    expect(page.locator("header")).to_contain_text(second["email"])
    ctx, args = handle
    with pytest.raises(BrowserError, match="device_mcp_(cloud_authority_rejected|scope_mismatch)"):
        session.device("invoke", ctx, **args, tool="device_label", input={})
    page.locator("header button").click()
    expect(page.locator("form button")).to_be_enabled()
    sign_in(page, api, owner)
    expect(page.locator("header")).to_contain_text(owner["email"])
    session.invoke_stale(handle)
    session.page_results(1)
    return session.device("list")["context_token"]


def host_hashes():
    stack = Path(__file__).resolve().parents[3] / "agi-stack"
    files = sorted((stack / "apps/desktop/out").rglob("*"))
    files.append(stack / "target/debug/agistack-desktop-sidecar")
    result = {}
    for file in files:
        if file.is_file():
            with file.open("rb") as content:
                result[file.relative_to(stack)] = hashlib.file_digest(content, "sha256").hexdigest()
    assert Path("target/debug/agistack-desktop-sidecar") in result
    assert Path("apps/desktop/out/main/index.js") in result
    assert Path("apps/desktop/out/renderer/index.html") in result
    return result


def test_native_project_package_upgrade_revoke_rollback(tmp_path):
    state = Path(os.environ["MEMSTACK_QA_STANDARD_DIRECTORY"])
    cdp, api = os.environ["MEMSTACK_QA_NATIVE_CDP"], os.environ["MEMSTACK_QA_NATIVE_API"]
    assert all(
        urlsplit(value).hostname in {"127.0.0.1", "localhost", "::1"} for value in (cdp, api)
    )
    key = serialization.load_pem_private_key((state / "publisher.key").read_bytes(), password=None)
    assert isinstance(key, Ed25519PrivateKey)
    owner = json.loads((state / "owner.json").read_bytes())
    plugin = "qa-" + uuid4().hex
    frozen = host_hashes()
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp)
        page = browser.contexts[0].pages[0]
        assert page.url.startswith("agistack://app/index.html")
        page.goto("agistack://app/index.html")
        page.locator("header button,form button:enabled").first.wait_for()
        if page.locator("form").count():
            sign_in(page, api, owner)
        expect(page.locator("header")).to_contain_text(owner["email"])
        projection = page.evaluate(
            "() => window.__MEMSTACK_DESKTOP__.core.invoke('cloud_session_projection',{requestId:crypto.randomUUID()})"
        )
        assert projection["api_base_url"] == api
        scope = {
            name: projection["workspace_context"]["context"][name]
            for name in ("tenant_id", "project_id")
        }
        session = PackageSession(page, scope, plugin)
        assert page.evaluate("() => window.__MEMSTACK_DESKTOP__.iab === undefined")
        with pytest.raises(BrowserError, match="desktop command is not supported"):
            session.bridge("sandbox_desktop_grant_open", {})
        with pytest.raises(BrowserError, match="cloud request endpoint is not allowed"):
            session.cloud(f"/api/v1/projects/{scope['project_id']}/playbooks?limit=200")

        archives = {
            i: base64.b64encode(publish_page(tmp_path / str(i), plugin, i, key)).decode()
            for i in (1, 2)
        }
        session.install(archives[1])
        handle = session.approve(archives[1])
        session.page_results(1)
        page.reload()
        session.page_results(1)
        session.install(archives[2])
        session.invoke_stale(handle)
        handle = session.approve(archives[2])
        session.page_results(2)
        session.change("rollback")
        session.invoke_stale(handle)
        ctx, args = session.approve(archives[1])
        session.page_results(1)
        if other_owner := os.getenv("MEMSTACK_QA_NATIVE_SECOND_OWNER"):
            second = json.loads(Path(other_owner).read_text())
            ctx = verify_account_switch(session, api, owner, second, (ctx, args))
        session.device("revoke", ctx, **args)
        session.invoke_stale((ctx, args))
        assert host_hashes() == frozen
