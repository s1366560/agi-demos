"""Exercise the signed pages in a fresh, loopback-only standard development project."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

import docker
from scripts.dev.standard_project import compose_project_name

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_QA_STANDARD_DIRECTORY"),
        reason="requires a running disposable standard project",
    ),
]


def _sign_in(browser, url, owner):
    page = browser.new_page(locale="en-US")
    page.goto(url)
    page.get_by_label("Email", exact=True).fill(owner["email"])
    page.get_by_label("Password", exact=True).fill(owner["password"])
    page.get_by_role("button", name="Sign In", exact=True).click()
    guest = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
    expect(guest.get_by_role("heading", name="Agent chat", exact=True)).to_be_visible(timeout=15000)
    expect(page.get_by_test_id("optional-business-panel")).to_have_count(0)
    return page


def test_mobile_package_host_and_guests_fit_viewport():
    state = Path(os.environ["MEMSTACK_QA_STANDARD_DIRECTORY"])
    url = os.environ.get("MEMSTACK_QA_STANDARD_ORIGIN", "http://127.0.0.1:3000")
    assert urlsplit(url).hostname in {"localhost", "127.0.0.1", "::1"}
    owner = json.loads((state / "owner.json").read_bytes())
    fits = "element => element.scrollWidth <= element.clientWidth + 1"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _sign_in(browser, url, owner)
        page.set_viewport_size({"width": 390, "height": 844})
        for route, title in [("/agent/chat", "Agent chat"), ("/workspaces", "Workspace directory")]:
            page.goto(url + route)
            guest = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
            expect(guest.get_by_role("heading", name=title)).to_be_visible()
            if route == "/agent/chat":
                # Conversation titles are user content and can exceed a phone's width.
                guest.get_by_label("Conversation", exact=True).evaluate(
                    "select => select.add(new Option('Conversation '.repeat(12)))"
                )
            else:
                editor = guest.get_by_role("region", name="Workspace rows")
                expect(editor).to_be_visible()
                guest.get_by_label("Archived", exact=True).check()
                assert editor.evaluate("element => element.scrollLeft > 0")
            assert page.locator("html").evaluate(fits), route
            assert guest.locator("html").evaluate(fits), route
        browser.close()


def test_six_pages_execute_the_declared_operations():
    state = Path(os.environ["MEMSTACK_QA_STANDARD_DIRECTORY"])
    url = os.environ.get("MEMSTACK_QA_STANDARD_ORIGIN", "http://127.0.0.1:3000")
    assert urlsplit(url).hostname in {"localhost", "127.0.0.1", "::1"}
    owner = json.loads((state / "owner.json").read_bytes())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _sign_in(browser, url, owner)

        def open_page(route, title):
            page.goto(url + route)
            frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
            expect(frame.get_by_role("heading", name=title, exact=True)).to_be_visible(
                timeout=15000
            )
            return frame

        f = open_page("/workspaces", "Workspace directory")
        f.get_by_label("ID", exact=True).fill("office")
        f.get_by_label("Name", exact=True).fill("North")
        f.get_by_role("button", name="Export CSV").click()
        expect(f.locator("pre")).to_contain_text("North")
        f = open_page("/knowledge", "Knowledge")
        f.get_by_label("Entity").fill("South")
        f.get_by_label("Type").fill("office")
        f.get_by_role("button", name="Project graph").click()
        expect(f.locator("pre")).to_contain_text("South")
        f = open_page("/automation", "Schedule workflow")
        f.get_by_role("button", name="Run workflow").click()
        expect(f.locator("ol[aria-live] li")).to_have_count(1, timeout=30000)
        f = open_page("/agent/skills", "Agent skills")
        f.get_by_label("SKILL.md").fill(
            "---\nname: check\ndescription: Check a file\n---\n# Check\n"
        )
        f.get_by_role("button", name="Validate skill").click()
        expect(f.locator("pre")).to_contain_text("valid")
        f = open_page("/environments/patch", "Sandbox patch preview")
        f.get_by_label("Original content").fill("a\n")
        f.get_by_label("Unified diff").fill("--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-a\n+b\n")
        f.get_by_role("button", name="Apply to preview").click()
        expect(f.locator("pre")).to_have_text("b")
        f = open_page("/billing", "Plans and invoices")
        f.get_by_role("button", name="pro", exact=True).click()
        expect(f.locator("output").nth(1)).to_contain_text("107,374,182,400")
        f.get_by_role("button", name="Project invoices").click()
        _check_invoice_creation(f)
        browser.close()


def _check_invoice_creation(frame):
    frame.get_by_label("Invoice reference").fill("browser-quarterly-invoice")
    frame.get_by_label("Amount in minor units").fill("12500")
    frame.get_by_label("Period start (UTC)").fill("2026-04-01")
    frame.get_by_label("Period end (UTC)").fill("2026-07-01")
    for _ in range(2):
        frame.get_by_role("button", name="Save invoice").click()
        expect(frame.get_by_text("Invoice saved", exact=True)).to_be_visible()
    frame.get_by_role("button", name="Project invoices").click()
    expect(frame.get_by_role("row").filter(has_text="USD 12500")).to_have_count(1)


def _initial_project(client, owner):
    token = client.post(
        "/api/v1/auth/token", data={"username": owner["email"], "password": owner["password"]}
    )
    token.raise_for_status()
    client.headers["Authorization"] = "Bearer " + token.json()["access_token"]
    available = client.get("/api/v1/project-packages/projects/").json()
    (scope,) = [
        {key: project[key] for key in ("tenant_id", "project_id")}
        for project in available
        if project["project_name"] == owner["project_name"]
        and project["tenant_name"] == owner["tenant_name"]
    ]
    return scope


def _running_hosts(directory):
    engine = docker.from_env(timeout=10)
    try:
        project = compose_project_name(directory)
        running = engine.containers.list(filters={"label": f"com.docker.compose.project={project}"})
        hosts = {
            container.labels["com.docker.compose.service"]: (container.id, container.attrs["Image"])
            for container in running
            if container.labels["com.docker.compose.service"] in {"api", "web"}
        }
        assert set(hosts) == {"api", "web"}
        return hosts
    finally:
        engine.close()


def test_independent_official_page_upgrade_and_rollback(tmp_path):
    import base64
    from uuid import uuid4

    import httpx
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    from src.tests.integration.official_page_revision import publish_page_revision

    state = Path(os.environ["MEMSTACK_QA_STANDARD_DIRECTORY"])
    url = os.environ.get("MEMSTACK_QA_STANDARD_ORIGIN", "http://127.0.0.1:3000")
    assert urlsplit(url).hostname in {"localhost", "127.0.0.1", "::1"}
    owner = json.loads((state / "owner.json").read_bytes())
    signer = load_pem_private_key((state / "publisher.key").read_bytes(), password=None)
    version = f"1.2.{uuid4().int % 1_000_000_000}"
    base = "/api/v1/platform-plugins/v2/optional-business"

    with httpx.Client(base_url=url, timeout=60) as client, sync_playwright() as playwright:
        scope = _initial_project(client, owner)
        browser = playwright.chromium.launch()
        page = _sign_in(browser, url, owner)

        def post(path, **body):
            response = client.post(base + path, json={**scope, **body})
            response.raise_for_status()
            return response.json()

        archive_dir = Path(os.environ.get("MEMSTACK_QA_PACKAGE_ARCHIVES", state / "archives"))
        archives = sorted(archive_dir.glob("*.mspkg"))
        official = {archive.stem for archive in archives}

        def active():
            response = client.get(base + "/", params=scope)
            response.raise_for_status()
            return {
                r["plugin_id"]: r["actual_digest"]
                for r in response.json()["items"]
                if r["plugin_id"] in official
            }

        before = active()
        frozen_hosts = _running_hosts(state)
        assert len(archives) == len(before) == 6
        for archive in archives:
            plugin = archive.stem
            raw = publish_page_revision(archive, tmp_path / plugin, version, signer)
            info = post("/inspect", archive_base64=base64.b64encode(raw).decode())
            post(
                "/install",
                archive_base64=base64.b64encode(raw).decode(),
                approved_permissions=info["permissions"],
            )
            post("/" + plugin + "/enable")
            try:
                assert active() == {**before, plugin: info["digest"]}
                check_other_package(post, plugin)
                selection = client.get(base + "/" + plugin, params=scope).json()
                route = selection["pages"][0]["routes"][0]
                page.goto(url + route)
                frame = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
                expect(frame.get_by_text("Publisher edition " + version)).to_be_visible(
                    timeout=15000
                )
            finally:
                post("/" + plugin + "/rollback")
            assert active() == before
            assert _running_hosts(state) == frozen_hosts
            page.reload()
            expect(frame.get_by_role("heading").first).to_be_visible(timeout=15000)
            expect(frame.get_by_text("Publisher edition " + version)).to_have_count(0)
        browser.close()


def check_other_package(post, plugin):
    if plugin == "memstack-environments":
        quote = post("/memstack-billing/commands", command_id="quote-pro")
        assert quote["storage_limit"] > 0
    else:
        health = post(
            "/memstack-environments/commands",
            command_id="cluster-health",
            payload={"total_nodes": 2, "used_cpu": 1, "total_cpu": 4},
        )
        assert health["cpu_usage"] == 25
