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

from .test_native_history_retirement import native_page
from .test_native_package_pages import PackageSession, host_hashes, sign_in

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
                resume.wait(20)
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


def approve_workspace(session, workspace, archive, model):
    ctx = session.device("list")["context_token"]
    preview = session.device("inspect", ctx, archive_base64=archive)
    assert preview["workspace"]["label"] == workspace.name
    assert preview["declared_permissions"] == ["device.local-chat"]
    args = {
        "archive_base64": archive,
        "reference": preview["reference"],
        "approved_permissions": preview["declared_permissions"],
        "approve_for_day": True,
        "local_model": model,
    }
    with pytest.raises(BrowserError, match="device_local_workspace_review_required"):
        session.device("install", ctx, **args)
    installed = session.device(
        "install", ctx, **args, workspace_token=preview["workspace"]["token"]
    )
    assert str(workspace) not in json.dumps(installed)
    return ctx, preview, installed


def test_native_package_local_chat_and_cancel(tmp_path):
    api = os.environ["MEMSTACK_QA_NATIVE_API"]
    assert urlsplit(api).hostname in {"127.0.0.1", "localhost", "::1"}
    standard = Path(os.environ["MEMSTACK_QA_STANDARD_DIRECTORY"])
    owner = json.loads((standard / "owner.json").read_bytes())
    raw = Path(os.environ["MEMSTACK_QA_NATIVE_AGENT_ARCHIVE"]).read_bytes()
    archive = base64.b64encode(raw).decode()
    trust = tmp_path / "trusted.json"
    trust.write_text(
        json.dumps(
            {"schema_version": 1, "public_keys_pem": [(standard / "publisher.pem").read_text()]}
        )
    )
    marker = uuid4().hex
    frozen = host_hashes()
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
        sign_in(view, api, owner)
        expect(view.locator("header")).to_contain_text(owner["email"])
        projection = view.evaluate(
            "() => window.__MEMSTACK_DESKTOP__.core.invoke('cloud_session_projection',{requestId:crypto.randomUUID()})"
        )
        scope = {
            key: projection["workspace_context"]["context"][key]
            for key in ("tenant_id", "project_id")
        }
        session = PackageSession(view, scope, "memstack-agent")
        ctx, preview, installed = approve_workspace(session, workspace, archive, model)
        view.evaluate("() => { location.hash='/agent/chat'; }")
        page = view.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
        expect(
            page.get_by_label(re.compile("^New conversation location$|^新会话执行位置$"))
        ).to_have_value("local", timeout=15000)
        page.get_by_role("button", name=re.compile("^New conversation$|^新会话$")).click()
        draft = page.get_by_label(re.compile("^Message$|^消息$"))
        expect(draft).to_be_editable()
        draft.fill("Read note.txt")
        page.get_by_role("button", name=re.compile("^Send to device$|^发送到本机$")).click()
        expect(page.get_by_role("status")).to_contain_text("completed · synced", timeout=45000)
        expect(page.locator("ol")).to_contain_text(marker, timeout=12000)
        assert len(calls) >= 2
        view.reload()
        expect(page.locator("ol")).to_contain_text(marker, timeout=15000)
        draft.fill("wait for cancellation")
        page.get_by_role("button", name=re.compile("^Send to device$|^发送到本机$")).click()
        assert entered.wait(15)
        page.get_by_role("button", name=re.compile("^Cancel run$|^取消运行$")).click()
        expect(page.get_by_role("status")).to_contain_text(re.compile("cancel"), timeout=15000)
        resume.set()
        expect(page.get_by_role("status")).to_contain_text("cancelled · synced", timeout=25000)
        session.device(
            "revoke", ctx, reference=preview["reference"], grant_id=installed["grant_id"]
        )
        draft.fill("Read note.txt after revocation")
        count = len(calls)
        page.get_by_role("button", name=re.compile("^Send to device$|^发送到本机$")).click()
        expect(page.get_by_role("status")).to_contain_text("grant_", timeout=12000)
        assert len(calls) == count
    assert host_hashes() == frozen
