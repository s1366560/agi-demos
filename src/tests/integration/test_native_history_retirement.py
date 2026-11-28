"""Exercise the native history cutover through a disconnectable proxy to the real project history API."""

import base64
import hashlib
import json
import os
import signal
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
from contextlib import ExitStack, closing, contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import Error as BrowserError, expect, sync_playwright
from sqlalchemy import create_engine, text

from src.tests.integration.rich_page_publisher import publish_page
from src.tests.integration.test_native_package_pages import BASE, PackageSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("MEMSTACK_QA_NATIVE_HISTORY") != "1",
        reason="needs a disposable standard project, built native app and GUI",
    ),
]
ROOT = Path(__file__).resolve().parents[3]


@contextmanager
def history_service(api):
    offline = threading.Event()
    offline.set()

    class Gateway(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def proxy(self):
            path = urlsplit(self.path)
            headers = {
                k: self.headers[k] for k in ("Authorization", "Content-Type") if k in self.headers
            }
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if path.path == "/api/v1/agent/conversations" and offline.is_set():
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            response = httpx.request(
                self.command, api + self.path, headers=headers, content=data, timeout=20
            )
            self.send_response(response.status_code)
            for name in ("content-type", "cache-control"):
                if name in response.headers:
                    self.send_header(name, response.headers[name])
            self.send_header("content-length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = do_POST = do_DELETE = proxy

    with ThreadingHTTPServer(("127.0.0.1", 0), Gateway) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", offline
        finally:
            server.shutdown()
            thread.join(5)


@contextmanager
def native_page(pw, profile, workspace, key_file):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        **os.environ,
        "AGISTACK_WORKSPACE_ROOT": str(workspace),
        "AGISTACK_DESKTOP_QA_PROFILE_DIR": str(profile),
        "AGISTACK_DESKTOP_DEBUG_PORT": str(port),
        "AGISTACK_LOCAL_PLUGIN_TRUSTED_KEYS_FILE": str(key_file),
        "AGISTACK_DESKTOP_GRANTS_LOCAL_ONLY": "1",
        "AGISTACK_DESKTOP_FIXED_BUILD": "1",
    }
    browser = None
    with (key_file.parent / ("native-" + uuid4().hex + ".log")).open("wb") as log:
        host = subprocess.Popen(
            ["make", "-C", "agi-stack", "run-desktop"],
            cwd=ROOT,
            env=env,
            start_new_session=True,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 50
            while True:
                assert host.poll() is None, "Native client exited during startup"
                try:
                    ready = httpx.get(f"http://127.0.0.1:{port}/json", timeout=0.3).json()
                except httpx.HTTPError:
                    ready = []
                if any(row.get("url", "").startswith("agistack://app/index.html") for row in ready):
                    break
                assert time.monotonic() < deadline
                time.sleep(0.15)
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            page = browser.contexts[0].pages[0]
            page.locator("header button,form button:enabled").first.wait_for()
            yield page
        finally:
            if browser and host.poll() is None:
                with suppress(BrowserError):
                    browser.new_browser_cdp_session().send("Browser.close")
                with suppress(subprocess.TimeoutExpired):
                    host.wait(timeout=4)
            if host.poll() is None:
                os.killpg(host.pid, signal.SIGTERM)
                host.wait(timeout=10)
            deadline = time.monotonic() + 12
            while (profile / "SingletonLock").is_symlink() and time.monotonic() < deadline:
                try:
                    owner = int(os.readlink(profile / "SingletonLock").split("-")[-1])
                    os.kill(owner, 0)
                except (ProcessLookupError, FileNotFoundError):
                    break
                time.sleep(0.05)


def migrate_fixture(path, *sql):
    # Seed and transition only the synthetic old profile while its host is stopped.
    engine = create_engine("sqlite:///" + str(path))
    with engine.begin() as conn:
        migrations = Operations(MigrationContext.configure(conn))
        for statement in sql:
            migrations.execute(text(statement))
    engine.dispose()


def read_only(path, sql):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        return db.execute(sql).fetchall()


def seed_legacy(runtime):
    sessions = runtime / "agistack-desktop-sessions.db"
    run = json.dumps(
        {
            "id": "p5",
            "conversation_id": "p5",
            "project_id": "project",
            "plan_version_id": "plan",
            "idempotency_key": "p5",
            "message_id": "p5",
            "request_message": "await approval",
            "status": "needs_approval",
            "revision": 1,
            "created_at": "2026-01-01",
            "updated_at": "2026-01-01",
            "authorization_snapshot": {},
        }
    )
    migrate_fixture(
        sessions,
        "INSERT INTO desktop_conversations(id,project_id,updated_at,value_json) VALUES ('p5','project','2026-01-01','{}')",
        "INSERT INTO desktop_timeline(id,conversation_id,position,value_json) VALUES ('p5','p5',1,'{}')",
        f"INSERT INTO desktop_runs(id,conversation_id,project_id,plan_version_id,idempotency_key,status,revision,created_at,updated_at,value_json) VALUES ('p5','p5','project','plan','p5','needs_approval',1,'2026-01-01','2026-01-01','{run}')",
    )
    queue = runtime / "local-run-upload.db"
    # An old upload queue may exist before its current uploader has started.
    migrate_fixture(
        queue,
        "CREATE TABLE upload_outbox (id INTEGER PRIMARY KEY, user_id TEXT, state TEXT, body TEXT)",
        "INSERT INTO upload_outbox(id,user_id,state,body) VALUES (1,'another-account','pending','preserved event')",
    )
    return sessions, queue


def prepare_account(open_page, proxy, owner, plugin, tmp_path, signing_key):
    with open_page() as page:
        page.locator('[name="origin"]').fill(proxy)
        page.locator('[name="email"]').fill(owner["email"])
        page.locator('[name="password"]').fill(owner["password"])
        page.locator("form button").click()
        expect(page.locator("header")).to_contain_text(owner["email"])
        projection = page.evaluate(
            "() => window.__MEMSTACK_DESKTOP__.core.invoke('cloud_session_projection',{requestId:crypto.randomUUID()})"
        )
        scope = {
            k: projection["workspace_context"]["context"][k] for k in ("tenant_id", "project_id")
        }
        native = PackageSession(page, scope, plugin)
        archive = base64.b64encode(
            publish_page(tmp_path / "release", plugin, 1, signing_key)
        ).decode()
        native.install(archive)
        native.approve(archive)
        agent = PackageSession(page, scope, "memstack-agent")
        conversation = agent.cloud(
            BASE + "/memstack-agent/commands",
            {
                "expected_digest": agent.record()["actual_digest"],
                "command_id": "chat-create",
                "payload": {"title": "P5 history " + uuid4().hex},
            },
        )
    return scope, conversation["id"]


def test_native_history_retirement_and_private_state(tmp_path):
    standard = Path(os.environ["MEMSTACK_QA_STANDARD_DIRECTORY"])
    api = os.environ["MEMSTACK_QA_NATIVE_API"]
    assert urlsplit(api).hostname in {"localhost", "127.0.0.1", "::1"}
    owner = json.loads((standard / "owner.json").read_bytes())
    trust = tmp_path / "trust.json"
    trust.write_text(
        json.dumps(
            {"schema_version": 1, "public_keys_pem": [(standard / "publisher.pem").read_text()]}
        )
    )
    signing_key = serialization.load_pem_private_key(
        (standard / "publisher.key").read_bytes(), password=None
    )
    plugin = "qa-" + uuid4().hex
    with ExitStack() as stack:

        def directory():
            return Path(
                stack.enter_context(
                    tempfile.TemporaryDirectory(
                        dir=os.environ.get("TMPDIR"), prefix="agistack-desktop-qa-p5-"
                    )
                )
            )

        profile, workspace = directory(), directory()
        runtime = profile / "runtime"
        proxy, offline = stack.enter_context(history_service(api))
        pw = stack.enter_context(sync_playwright())

        def open_page():
            return native_page(pw, profile, workspace, trust)

        scope, conversation_id = prepare_account(
            open_page, proxy, owner, plugin, tmp_path, signing_key
        )
        sessions, queue = seed_legacy(runtime)
        history = "/api/v1/agent/conversations?" + urlencode(
            {"project_id": scope["project_id"], "status": "active", "offset": 0, "limit": 100}
        )

        def observe(*, offline_read=False):
            with open_page() as view:
                expect(view.locator("header")).to_contain_text(owner["email"])
                logged_in = PackageSession(view, scope, plugin)
                if offline_read:
                    with pytest.raises((BrowserError, AssertionError)):
                        logged_in.cloud(history)
                else:
                    rows = logged_in.cloud(history)["items"]
                    assert any(row["id"] == conversation_id for row in rows)
                for _ in range(2):
                    projected = logged_in.bridge(
                        "cloud_session_projection", {"requestId": str(uuid4())}
                    )
                    assert projected["status"] == "authenticated"

        def counts():
            return [
                read_only(sessions, "SELECT COUNT(*) FROM " + table + " WHERE id='p5'")[0][0]
                for table in ("desktop_timeline", "desktop_conversations")
            ]

        def preserved():
            return (
                hashlib.sha256((runtime / "credential-vault/master.key").read_bytes()).digest(),
                read_only(
                    sessions,
                    "SELECT owner,bundle_id,selection FROM desktop_cloud_device_plugins_v2 ORDER BY owner,bundle_id",
                ),
                read_only(queue, "SELECT id,user_id,body FROM upload_outbox"),
            )

        before = preserved()
        observe(offline_read=True)
        assert counts() == [1, 1]
        offline.clear()
        observe()
        assert counts() == [1, 1]
        migrate_fixture(queue, "UPDATE upload_outbox SET state='acked' WHERE id=1")
        observe()
        assert counts() == [1, 1]
        migrate_fixture(
            sessions,
            "UPDATE desktop_runs SET status='completed' WHERE id='p5'",
            "CREATE TRIGGER deny_retirement BEFORE DELETE ON desktop_conversations BEGIN SELECT RAISE(ABORT,'rollback');END",
        )
        observe()
        assert counts() == [1, 1]
        migrate_fixture(sessions, "DROP TRIGGER deny_retirement")
        observe()
        assert counts() == [0, 0] and preserved() == before
        with open_page() as page:
            PackageSession(page, scope, plugin).page_results(1)
