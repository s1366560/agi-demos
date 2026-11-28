"""Exercise the installed Web sidebar against the local QA registry and project authorities."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MEMSTACK_QA_SIDEBAR_ACCOUNTS"), reason="dedicated QA projects required"
    ),
]

BASE = "/platform-plugins/v2/optional-business"


def qa_workspace(client, scope, name="Signed sidebar integration"):
    path = f"/tenants/{scope['tenant_id']}/projects/{scope['project_id']}/workspaces"
    response = client.get(path)
    response.raise_for_status()
    existing = next((item for item in response.json() if item["name"] == name), None)
    if existing:
        return existing["id"]
    created = client.post(path, json={"name": name})
    created.raise_for_status()
    return created.json()["id"]


def installed_sidebar(package):
    accounts = json.loads(Path(os.environ["MEMSTACK_QA_SIDEBAR_ACCOUNTS"]).read_bytes())
    owner = json.loads(Path(accounts[package]["web"]).read_bytes())
    scope = {key: owner[key] for key in ("tenant_id", "project_id")}
    version = json.loads(Path(f"plugins/business/{package}/package.json").read_bytes())["version"]
    plugin = f"memstack-{package}"
    selector = {
        **scope,
        "plugin_id": plugin,
        "package_name": f"@memstack/{package}",
        "version": version,
    }
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=90) as client:
        login = client.post(
            "/auth/token", data={"username": owner["email"], "password": owner["password"]}
        )
        login.raise_for_status()
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        info = client.get(BASE + "/npm/detail", params=selector)
        info.raise_for_status()
        detail = info.json()
        release = detail["release"]
        if (detail.get("installation") or {}).get("actual_digest") != release["digest"]:
            allowed = next(
                row["permissions"]
                for row in json.loads(
                    Path("charts/memstack/files/standard-packages.json").read_bytes()
                )
                if row["plugin_id"] == plugin
            )
            assert detail["can_manage"] and set(release["permissions"]) <= set(allowed)
            result = client.post(
                BASE + "/npm/apply",
                json={
                    **{k: v for k, v in selector.items() if k != "plugin_id"},
                    "expected_revision": detail["desired_revision"],
                    "expected_digest": release["digest"],
                    "approved_permissions": release["permissions"],
                },
            )
            result.raise_for_status()
        listing = client.get(BASE + "/", params=scope)
        listing.raise_for_status()
        active = next(item for item in listing.json()["items"] if item["plugin_id"] == plugin)
        assert active["status"] == "enabled" and active["actual_digest"] == release["digest"]
        page = next(
            item for item in active["pages"] if "web" in item["targets"] and item.get("sidebar")
        )
        workspace = qa_workspace(client, scope) if package == "agent" else None
    return owner, scope, plugin, release["digest"], page["sidebar"], workspace


def login(view, origin, owner):
    view.goto(origin + "/login")
    view.get_by_test_id("email-input").fill(owner["email"])
    view.get_by_test_id("password-input").fill(owner["password"])
    view.get_by_test_id("login-submit-button").click()
    expect(view.get_by_test_id("login-submit-button")).to_have_count(0, timeout=60000)


@pytest.mark.parametrize("package", ["agent", "workspace"])
def test_installed_sidebar(package):
    owner, scope, plugin, digest, bindings, workspace = installed_sidebar(package)
    origin = os.environ.get("MEMSTACK_QA_SIDEBAR_ORIGIN", "http://127.0.0.1:3000")
    assert re.fullmatch(r"http://(?:localhost|127\.0\.0\.1):[0-9]+", origin)
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        view = browser.new_page(locale="en-US", viewport={"width": 1440, "height": 950})
        login(view, origin, owner)

        def command(name):
            return (
                lambda r: r.url.endswith(f"/{plugin}/commands")
                and r.request.post_data_json.get("command_id") == name
            )

        def check(response):
            assert response.ok, response.status
            body = response.request.post_data_json
            assert body["expected_digest"] == digest
            assert all(body[k] == v for k, v in scope.items())

        query = urlencode({"projectId": owner["project_id"], "businessPackage": plugin})
        if package == "workspace":
            with view.expect_response(command(bindings["groups"]["command"])) as read:
                view.goto(f"{origin}/tenant/{owner['tenant_id']}/projects?{query}")
            check(read.value)
            assert isinstance(read.value.json()["rows"], list)
            return
        query += "&" + urlencode({"workspaceId": workspace})
        route = bindings["rows"]["route"].replace(":tenantId", owner["tenant_id"])
        with view.expect_response(command(bindings["rows"]["command"])) as read:
            view.goto(f"{origin}{route}?{query}")
        check(read.value)
        create = view.get_by_role("button", name=re.compile("New Chat|新建对话|新对话", re.I)).first
        with view.expect_response(command(bindings["create"]["command"])) as created:
            create.click()
        check(created.value)
        assert created.value.request.post_data_json["payload"]["workspace_id"] == workspace
        row = view.locator(f'a[href*="/{created.value.json()["id"]}?"]').first
        expect(row).to_be_visible()
        row.hover()
        row.get_by_role("button", name=re.compile("Rename|重命名", re.I)).click()
        dialog = view.get_by_role("dialog")
        title = f"Sidebar QA {uuid4().hex[:8]}"
        dialog.get_by_role("textbox").fill(title)
        with view.expect_response(command(bindings["rename"]["command"])) as renamed:
            dialog.get_by_role("textbox").press("Enter")
        check(renamed.value)
        expect(row).to_contain_text(title)
        view.reload()
        expect(view.get_by_text(title, exact=True).first).to_be_visible(timeout=30000)
        guest = view.frame_locator("iframe[data-page-ready=true]").first.frame_locator("iframe")
        expect(
            guest.get_by_role("textbox", name=re.compile("Conversation title|会话标题"))
        ).to_have_value(title)
        with view.expect_response(command(bindings["create"]["command"])) as inside:
            guest.locator("aside button").first.click()
        check(inside.value)
        assert inside.value.request.post_data_json["payload"]["workspace_id"] == workspace
