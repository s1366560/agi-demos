"""Run installed Web/Electron package acceptance against one previously built full host.

Supply a JSON object mapping each package to its private Web and desktop account-file paths.
The development API and npm registry are on localhost:8000 and localhost:4873.
"""

import argparse
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
TESTS = "src/tests/integration/"
PACKAGES = ("workspace", "knowledge", "automation", "billing", "environments", "agent")
API = "http://127.0.0.1:8000"
SIDECAR = ROOT / "agi-stack/target/debug/agistack-desktop-sidecar"
CORE = ROOT / ".cache/avernet-bcs/target/debug/memstack-workspace-core"


CDP_VARIABLES = (
    "MEMSTACK_QA_BUSINESS_MARKET_CDP",
    "MEMSTACK_QA_ORIGINAL_PAGES_CDP",
    "MEMSTACK_INTERACTIVE_SANDBOX_CDP",
    "MEMSTACK_QA_SIGNED_WORKBENCH_CDP",
)


def tests_for(package: str, target: str) -> list[str]:
    desktop = target == "desktop"
    if package in {"workspace", "knowledge"}:
        exercises = {
            (
                "workspace",
                "web",
            ): "write_objective or upload_and_preview_chunks or opens_installed_agent",
            ("workspace", "desktop"): "native_blackboard_post",
            ("knowledge", "web"): "web_editor_reindex or web_graph_loads",
            ("knowledge", "desktop"): "native_memory_create or native_graph_refreshes",
        }
        expression = (
            f"(restore_original_release and {package} and {target}) or {exercises[package, target]}"
        )
        return [TESTS + "test_installed_original_boards.py", "-k", expression]
    if package == "automation":
        tests = [
            TESTS + f"test_fixed_workbench_market.py::test_installed_schedule_lifecycle[{target}]"
        ]
        if desktop:
            tests.append(TESTS + "test_native_signed_workbench_shell.py")
        return tests
    if package == "billing":
        return [
            TESTS
            + (
                "test_fixed_workbench_market.py::test_installed_native_billing_lifecycle"
                if desktop
                else "test_tenant_billing_web.py"
            )
        ]
    if package == "environments":
        renderer = "electron" if desktop else "web"
        return [
            TESTS
            + f"test_signed_sandbox_interactions.py::test_installed_terminal_and_remote_desktop[{renderer}]"
        ]
    return [TESTS + "test_signed_agent_interactions.py"]


def file_digest(path: Path) -> bytes:
    with path.open("rb") as data:
        return hashlib.file_digest(data, "sha256").digest()


def fingerprint(artifacts: Path, targets: list[str]) -> dict[str, str]:
    result = {}
    if "desktop" in targets:
        result.update(sidecar=file_digest(SIDECAR).hex(), workspace_core=file_digest(CORE).hex())
    for target, name, entry in [
        ("web", "web/dist", "index.html"),
        ("desktop", "agi-stack/apps/desktop/out", "main/index.js"),
        ("desktop", "agi-stack/apps/desktop/node_modules/electron/dist", "version"),
    ]:
        if target not in targets:
            continue
        root = artifacts / name
        if not (root / entry).is_file():
            raise RuntimeError(f"Full host is missing {root / entry}")
        tree = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            if path.is_file():
                tree.update(path.relative_to(root).as_posix().encode() + b"\0")
                tree.update(file_digest(path))
        result[name] = tree.hexdigest()
    return result


@contextmanager
def native_window(
    artifacts: Path, log: Path, owner: dict[str, str], marketplace: bool
) -> Iterator[str]:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    cdp = f"http://127.0.0.1:{port}"
    # The native grant launcher checks that these directories are direct children of TMPDIR.
    with (
        tempfile.TemporaryDirectory(prefix="agistack-desktop-qa-fixed-") as profile,
        tempfile.TemporaryDirectory(prefix="agistack-desktop-qa-workspace-fixed-") as workspace,
        log.open("w") as output,
    ):
        env = {
            **os.environ,
            "AGISTACK_DESKTOP_PROFILE": "full",
            "AGISTACK_DESKTOP_FIXED_BUILD": "1",
            "DESKTOP_APP_DIR": str(artifacts / "agi-stack/apps/desktop"),
            "AGISTACK_SIDECAR_PATH": str(SIDECAR),
            "AGISTACK_WORKSPACE_CORE_PATH": str(CORE),
            "AGISTACK_DESKTOP_QA_PROFILE_DIR": profile,
            "AGISTACK_WORKSPACE_ROOT": workspace,
            "AGISTACK_DESKTOP_DEBUG_PORT": str(port),
        }
        process = subprocess.Popen(
            ["make", "-C", "agi-stack", "run-desktop"],
            cwd=ROOT,
            env=env,
            start_new_session=True,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    if httpx.get(cdp + "/json/version", timeout=2).is_success:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.5)
            else:
                raise RuntimeError(f"Electron did not start. See {log}")
            with sync_playwright() as pw:
                context = pw.chromium.connect_over_cdp(cdp).contexts[0]
                page = context.pages[0] if context.pages else context.wait_for_event("page")
                page.set_default_timeout(60000)
                page.locator("input[type=url]").fill(API)
                page.locator("input[type=email]").fill(owner["email"])
                page.locator("input[type=password]").fill(owner["password"])
                page.locator("button[type=submit]").click()
                menu = page.get_by_role("button", name=re.compile("^(全部功能|All features)$"))
                expect(menu).to_be_visible(timeout=60000)
                if marketplace:
                    menu.click()
                    page.locator("[role=dialog] button").filter(
                        has_text=re.compile("插件|Plugins")
                    ).first.click()
                    expect(page.locator(".package-market-scope select")).to_be_visible()
            yield cdp
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=30)


@contextmanager
def qa_sandbox(owner: dict[str, str]) -> Iterator[None]:
    if owner.get("project_name") != "Signed interactive sandbox QA":
        raise ValueError("The terminal test requires its dedicated interactive sandbox project")
    with httpx.Client(base_url=API + "/api/v1", timeout=180) as client:
        auth = client.post(
            "/auth/token",
            data={"username": owner["email"], "password": owner["password"]},
        )
        auth.raise_for_status()
        client.headers["Authorization"] = "Bearer " + auth.json()["access_token"]
        path = f"/projects/{owner['project_id']}/sandbox"
        before = client.get(path)
        if before.status_code != 404:
            before.raise_for_status()
        ready = client.post(path, json={"profile": "standard"})
        ready.raise_for_status()
        owned = ready.json()["sandbox_id"] if before.status_code == 404 else None
        try:
            yield
        finally:
            if owned:
                current = client.get(path)
                if current.is_success and current.json()["sandbox_id"] == owned:
                    client.delete(path).raise_for_status()


def run(
    package: str, target: str, args: argparse.Namespace, accounts: dict[str, dict[str, str]]
) -> None:
    path = Path(accounts[package][target]).resolve()
    owner: dict[str, str] = json.loads(path.read_bytes())
    scope = owner["tenant_id"] if package == "billing" else owner["project_id"]
    web = args.origin.rstrip("/")
    env = {
        **os.environ,
        "MEMSTACK_QA_MARKET_FULL_ORIGIN": web,
        "MEMSTACK_QA_VERTICAL_ORIGIN": web,
        "MEMSTACK_QA_MARKET_FULL_OWNER": str(path),
        "MEMSTACK_QA_EXPECT_MARKET_SCOPE": scope,
        "MEMSTACK_QA_SCHEDULE_OWNER": str(path),
        "MEMSTACK_QA_EMPTY_TENANT_OWNER": str(path),
        "MEMSTACK_QA_FIXED_BILLING_OWNER": str(path),
        "MEMSTACK_QA_INTERACTION_OWNER": str(path),
        "MEMSTACK_INTERACTIVE_SANDBOX_OWNER": str(path),
    }
    for key in CDP_VARIABLES:
        env.pop(key, None)
    log = args.logs / f"{package}-{target}.log"
    display = (
        native_window(args.artifacts, log.with_suffix(".electron.log"), owner, package == "agent")
        if target == "desktop"
        else nullcontext()
    )
    sandbox = qa_sandbox(owner) if package == "environments" else nullcontext()
    print(f"Running {package} {target}", flush=True)
    with sandbox, display as cdp, log.open("w") as output:
        if cdp:
            for key in CDP_VARIABLES:
                env[key] = cdp
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-rA", *tests_for(package, target)],
            cwd=ROOT,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    report = log.read_text()
    if completed.returncode or re.search(r"\b\d+ skipped\b", report) or " passed" not in report:
        raise RuntimeError(f"{package} {target} acceptance failed. See {log}")
    print(f"Passed {package} {target}", flush=True)


def main() -> bool:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--accounts", type=Path, required=True)
    parser.add_argument("--logs", type=Path, required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--package", choices=PACKAGES, action="append")
    parser.add_argument("--target", choices=["web", "desktop"], action="append")
    args = parser.parse_args()
    if urlsplit(args.origin).hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Use a local static Web host")
    args.artifacts = args.artifacts.resolve()
    args.logs.mkdir(parents=True, exist_ok=True)
    targets = args.target or ["web", "desktop"]
    if "desktop" in targets:
        desktop = args.artifacts / "agi-stack/apps/desktop"
        if not (desktop / "node_modules/electron/dist/version").is_file():
            subprocess.run(
                ["corepack", "pnpm", "exec", "install-electron", "--no"], cwd=desktop, check=True
            )
    if "web" in targets:
        index = (args.artifacts / "web/dist/index.html").read_bytes()
        served = httpx.get(args.origin.rstrip("/") + "/index.html")
        served.raise_for_status()
        if served.content != index:
            raise RuntimeError("The Web server must serve the supplied static build")
    initial = fingerprint(args.artifacts, targets)
    accounts = json.loads(args.accounts.read_bytes())
    failures = []
    for package in args.package or PACKAGES:
        for target in targets:
            try:
                run(package, target, args, accounts)
            except Exception as exc:
                print(f"{package} {target}: {type(exc).__name__}: {exc}", flush=True)
                failures.append((package, target))
    if fingerprint(args.artifacts, targets) != initial:
        raise RuntimeError("Host binaries changed during acceptance")
    print("Fixed hosts SHA-256", json.dumps(initial, sort_keys=True), flush=True)
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
