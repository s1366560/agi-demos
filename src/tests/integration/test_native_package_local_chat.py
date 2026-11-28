"""Execute a signed Agent page on the approved workspace and replay the device result."""

import base64
import json
import os
import re
import tempfile
import threading
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import Error as BrowserError, expect, sync_playwright

from scripts.dev.verify_six_workbenches import CORE, SIDECAR, fingerprint, verify_sidecar_process

from .marketplace_browser import apply, business_release
from .test_native_history_retirement import native_page
from .test_native_package_pages import PackageSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_QA_NATIVE_AGENT_ARCHIVE"),
        reason="requires a fixed native Electron, Sidecar and signed Agent release",
    ),
]


@contextmanager
def local_model(marker):
    """A deterministic local model requests a real file read and checks its observation."""
    calls = []
    entered = threading.Event()
    resume = threading.Event()

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert body["model"] == "native-fixture"
            assert "Authorization" not in self.headers
            text = json.dumps(body["messages"])
            calls.append(body["model"])
            if "wait for cancellation" in text:
                entered.set()
                resume.wait(100)
                action = {"kind": "finish", "answer": "cancelled fixture"}
            elif marker in text:
                action = {"kind": "finish", "answer": f"Read {marker}"}
            else:
                action = {"kind": "call_tool", "tool": "read", "input_json": {"path": "note.txt"}}
            response = json.dumps(
                {"choices": [{"message": {"content": json.dumps(action)}}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    with ThreadingHTTPServer(("127.0.0.1", 0), Model) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield (
                {
                    "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                    "model": "native-fixture",
                },
                calls,
                entered,
                resume,
            )
        finally:
            resume.set()
            server.shutdown()
            thread.join(timeout=3)


def approve_workspace(view, frame, session, workspace, archive, model):
    ctx = session.device("list")["context_token"]
    preview = session.device("inspect", ctx, archive_base64=archive)
    assert preview["workspace"]["label"] == workspace.name
    assert preview["declared_permissions"] == ["device.local-chat"]
    with pytest.raises(BrowserError, match="device_local_workspace_review_required"):
        session.device(
            "install",
            ctx,
            archive_base64=archive,
            reference=preview["reference"],
            approved_permissions=preview["declared_permissions"],
            approve_for_day=True,
            local_model=model,
        )
    skip = frame.get_by_role("button", name=re.compile("^(Skip tour|跳过引导)$"))
    if skip.is_visible():
        skip.click()
    frame.get_by_role("button", name=re.compile("Device settings|设备设置")).click()
    dialog = view.get_by_role("dialog", name=re.compile("Device approval|设备授权"))
    dialog.get_by_role(
        "button",
        name=re.compile("Review this release|审阅此版本并授权设备"),
    ).click()
    expect(dialog.locator("fieldset legend").or_(dialog.get_by_role("alert"))).to_contain_text(
        workspace.name, timeout=60000
    )
    dialog.locator("fieldset input").nth(0).fill(model["base_url"])
    dialog.locator("fieldset input").nth(1).fill(model["model"])
    dialog.get_by_role("checkbox").check()
    dialog.get_by_role("button", name=re.compile("Approve and install|批准并安装")).click()
    active = dialog.locator("article")
    expect(active).to_contain_text(preview["reference"]["version"], timeout=60000)
    dialog.get_by_role("button", name=re.compile("^Close$|^关闭$")).click()
    catalog = session.device("list")
    installed = next(
        row for row in catalog["installations"] if row["reference"] == preview["reference"]
    )
    assert installed["grant_status"] == "approved" and str(workspace) not in json.dumps(installed)
    return catalog["context_token"], preview, installed


def install_signed_agent(view, api, owner, artifacts):
    view.locator("input[type=url]").fill(api)
    view.locator("input[type=email]").fill(owner["email"])
    view.locator("input[type=password]").fill(owner["password"])
    view.locator("button[type=submit]").click()
    expect(view.get_by_role("button", name=re.compile("^(全部功能|All features)$"))).to_be_visible(
        timeout=60000
    )
    browser = view.context.browser
    processes = browser.new_browser_cdp_session().send("SystemInfo.getProcessInfo")
    verify_sidecar_process(
        next(row["id"] for row in processes["processInfo"] if row["type"] == "browser"),
        artifacts / SIDECAR,
    )
    projection = view.evaluate(
        "() => window.__MEMSTACK_DESKTOP__.core.invoke('cloud_session_projection',{requestId:crypto.randomUUID()})"
    )
    scope = {
        key: projection["workspace_context"]["context"][key] for key in ("tenant_id", "project_id")
    }
    session = PackageSession(view, scope, "memstack-agent")
    if owner.get("project_id"):
        assert scope["project_id"] == owner["project_id"]
    view.evaluate("path => { location.hash = path; }", f"/tenant/{scope['tenant_id']}/plugins")
    view.locator(".package-market-scope select").select_option("project")
    card = view.locator("#pm-card-memstack-agent")
    card.click()
    active = view.locator(".pm-spec dd").first
    expect(active).to_be_visible(timeout=60000)
    if active.inner_text() != business_release("agent"):
        apply(view, business_release("agent"))
    return session


def test_native_package_local_chat_and_cancel(tmp_path, monkeypatch):
    api = os.environ["MEMSTACK_QA_NATIVE_API"]
    assert urlsplit(api).hostname in {"127.0.0.1", "localhost", "::1"}
    standard = Path(os.environ["MEMSTACK_QA_STANDARD_DIRECTORY"])
    owner = json.loads(
        Path(os.getenv("MEMSTACK_QA_NATIVE_AGENT_OWNER", standard / "owner.json")).read_bytes()
    )
    artifacts = Path(os.getenv("MEMSTACK_QA_FIXED_HOST_ROOT", Path(__file__).resolve().parents[3]))
    monkeypatch.setenv("AGISTACK_DESKTOP_PROFILE", "full")
    monkeypatch.setenv("DESKTOP_APP_DIR", str(artifacts / "agi-stack/apps/desktop"))
    monkeypatch.setenv("AGISTACK_SIDECAR_PATH", str(artifacts / SIDECAR))
    monkeypatch.setenv("AGISTACK_WORKSPACE_CORE_PATH", str(CORE))
    archive = base64.b64encode(
        Path(os.environ["MEMSTACK_QA_NATIVE_AGENT_ARCHIVE"]).read_bytes()
    ).decode()
    trust = tmp_path / "trusted.json"
    trust.write_text(
        json.dumps(
            {"schema_version": 1, "public_keys_pem": [(standard / "publisher.pem").read_text()]}
        )
    )
    marker = uuid4().hex
    frozen = fingerprint(artifacts, ["desktop"])
    with ExitStack() as stack:

        def folder():
            return Path(
                stack.enter_context(
                    tempfile.TemporaryDirectory(
                        dir=os.environ.get("TMPDIR"), prefix="agistack-desktop-qa-local-chat-"
                    )
                )
            )

        profile, workspace = folder(), folder()
        (workspace / "note.txt").write_text(marker)
        model, calls, entered, resume = stack.enter_context(local_model(marker))
        pw = stack.enter_context(sync_playwright())
        view = stack.enter_context(native_page(pw, profile, workspace, trust))
        session = install_signed_agent(view, api, owner, artifacts)
        view.evaluate("() => { location.hash='/agent/chat'; }")
        page = view.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        expect(
            page.get_by_role("combobox", name=re.compile("执行位置|Execution location"))
        ).to_have_value("local", timeout=30000)
        ctx, preview, installed = approve_workspace(view, page, session, workspace, archive, model)
        expect(page.locator('[data-execution-resource="directory"]')).to_have_text(
            workspace.name, timeout=60000
        )
        draft = page.get_by_test_id("chat-input")
        expect(draft).to_be_editable()
        draft.fill("Read note.txt")
        page.get_by_test_id("send-button").click()
        expect(page.get_by_role("log")).to_contain_text(marker, timeout=90000)
        assert len(calls) >= 2
        view.wait_for_url(re.compile(r"#/agent/chat/[^/?]+"), timeout=30000)
        view.reload()
        expect(page.get_by_role("log")).to_contain_text(marker, timeout=30000)
        draft.fill("wait for cancellation")
        page.get_by_test_id("send-button").click()
        assert entered.wait(30)
        page.get_by_role("button", name=re.compile("^Stop$|^停止$")).click()
        expect(page.get_by_role("alert").filter(has_text="cancelled")).to_contain_text(
            "synced", timeout=45000
        )
        resume.set()
        session.device(
            "revoke", ctx, reference=preview["reference"], grant_id=installed["grant_id"]
        )
        draft.fill("Read note.txt after revocation")
        count = len(calls)
        page.get_by_test_id("send-button").click()
        expect(page.get_by_role("alert").filter(has_text="grant_")).to_be_visible(timeout=30000)
        expect(draft).to_have_value("Read note.txt after revocation")
        assert len(calls) == count
    assert fingerprint(artifacts, ["desktop"]) == frozen
