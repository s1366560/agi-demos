"""Export real member-visible Workspace Core directories through the production proxy and guest."""

import base64
import csv
import io
import os
import re
import secrets
import time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from alembic.config import Config
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker

import docker
from alembic import command
from plugins.business.workspace.backend.blackboard_surface import change_surface, read_surface
from plugins.business.workspace.backend.collaboration import WORKSPACE_COLLABORATION_OPERATIONS
from plugins.business.workspace.backend.group_chat import read_chat, send_chat
from plugins.business.workspace.backend.workspace_directory_export import (
    create_workspace_operation,
    read_directory_operation,
    read_workspace_operation,
    update_workspace_operation,
)
from src.configuration.workspace_core import WorkspaceCoreSettings
from src.infrastructure.adapters.primary.web import workspace_core_routes as routes
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2.builtin_workspace_core_http_routes import (
    workspace_core_route_definitions_v2,
)
from src.infrastructure.plugins.v2.http_routes import install_route_definitions_v2
from src.infrastructure.workspace_core.client import WorkspaceCoreClient
from src.tests.integration.package_http_server import serve_project_api
from src.tests.integration.signed_wasm_releases import build_upgrade_pair
from src.tests.unit.infrastructure.plugins.v2.test_feature_operations_v2 import _runtime
from src.tests.unit.routers import test_optional_business_http_v2 as package_api

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("WORKSPACE_DIRECTORY_DOCKER_TESTS") != "1",
        reason="requires Workspace Core image and Docker",
    ),
]
http = package_api.http
publisher = package_api.publisher
ROOT = Path(__file__).resolve().parents[3]
PACKAGE = "memstack-workspace"


@pytest.fixture(scope="module")
def releases(tmp_path_factory):
    return build_upgrade_pair(
        ROOT / "plugins/business/workspace",
        tmp_path_factory.mktemp("directory-publisher"),
        '("archived", "true", "false")',
        '("lifecycle", "archived", "current")',
    )


@pytest.fixture
def core():
    identity = "directory-test-" + uuid4().hex[:14]
    with ExitStack() as stack:
        engine = docker.from_env(timeout=60)
        stack.callback(engine.close)
        network = engine.networks.create(identity)
        stack.callback(network.remove)

        def start(image, name, **options):
            container = engine.containers.run(
                image, name=identity + "-" + name, network=network.name, detach=True, **options
            )
            stack.callback(container.remove, force=True, v=True)
            container.reload()
            return container

        start(
            "redis:7-alpine",
            "redis",
            networking_config={network.name: engine.api.create_endpoint_config(aliases=["redis"])},
        )
        password = secrets.token_hex(20)
        pg = start(
            "pgvector/pgvector:pg16",
            "pg",
            environment={"POSTGRES_PASSWORD": password, "POSTGRES_DB": "directory"},
            ports={"5432/tcp": ("127.0.0.1", None)},
        )
        for _ in range(80):
            if (
                pg.exec_run(
                    ["pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", "directory"]
                ).exit_code
                == 0
            ):
                break
            time.sleep(0.15)
        else:
            pytest.fail("isolated workspace database did not start")
        pg_port = pg.attrs["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        migration = Config(str(ROOT / "alembic.ini"))
        migration.attributes["configure_logger"] = False
        migration.attributes["database_url"] = URL.create(
            "postgresql+asyncpg",
            username="postgres",
            password=password,
            host="127.0.0.1",
            port=int(pg_port),
            database="directory",
        )
        command.upgrade(migration, "head")
        # Core resolves the postgres search path itself. Creation and membership are exercised via its API.
        token = secrets.token_hex(32)
        env = {
            k: secrets.token_hex(32)
            for k in [
                "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN",
                "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN",
                "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN",
                "AVERNET_SECRET_PRINCIPAL_SIGNING_KEY_VALUE",
                "BCS_SECRET_WORKSPACE_CORE_GROUP_SESSION_WS_JWT",
            ]
        }
        env.update(
            {
                "WORKSPACE_CORE_SERVICE_TOKEN": token,
                "WORKSPACE_CORE_MODE": "cloud",
                "WORKSPACE_CORE_DATABASE_URL": f"postgresql://postgres:{password}@{pg.name}/directory",
                "WORKSPACE_CORE_AGENT_REGISTRY_URL": "http://127.0.0.1:1",
                "WORKSPACE_CORE_PROVIDER_WEBHOOK_URL": "http://127.0.0.1:1/provider",
                "WORKSPACE_CORE_PLAN_DISPATCH_URL": "http://127.0.0.1:1/dispatch",
            }
        )
        server = start(
            os.getenv("WORKSPACE_DIRECTORY_CORE_IMAGE", "agi-demos-memstack-workspace-core:latest"),
            "core",
            environment=env,
            ports={"4319/tcp": ("127.0.0.1", None)},
        )
        port = server.attrs["NetworkSettings"]["Ports"]["4319/tcp"][0]["HostPort"]
        origin = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if httpx.get(origin + "/health", timeout=0.5).is_success:
                    break
            except httpx.TransportError:
                pass
            server.reload()
            if server.status == "exited":
                pytest.fail(
                    "Workspace Core exited: "
                    + server.logs(tail=6).decode().replace(password, "***")[-1200:]
                )
            time.sleep(0.15)
        else:
            pytest.fail("isolated Workspace Core did not become healthy")
        yield WorkspaceCoreClient(
            WorkspaceCoreSettings(
                WORKSPACE_CORE_BASE_URL=origin, WORKSPACE_CORE_SERVICE_TOKEN=token
            )
        )


async def _project_host(http, db_session, core, public, monkeypatch):
    local, keys = http
    app = local._transport.app
    app.state.plugin_marketplace_trusted_public_keys_v2 = (public.decode(),)
    # Test fixture owns its SQL database and the catalog snapshot. Production authorization runs.
    app.state.scoped_profile_runtime_v2 = _runtime(
        entries=(SimpleNamespace(entry_id="builtin-web-default-routes", enabled=True),)
    )[0]
    app.state.workspace_core_client = core
    app.state.package_operations_v1 = {
        **WORKSPACE_COLLABORATION_OPERATIONS,
        "app.workspace.chat.read": read_chat,
        "app.workspace.chat.send": send_chat,
        "app.workspace.blackboard.read": read_surface,
        "app.workspace.blackboard.write": change_surface,
        "app.workspace.create": create_workspace_operation,
        "app.workspace.settings.update": update_workspace_operation,
        "app.workspace.directory.read": read_directory_operation,
        "app.workspace.detail.read": read_workspace_operation,
    }
    install_route_definitions_v2(app, workspace_core_route_definitions_v2())
    monkeypatch.setattr(
        routes, "async_session_factory", async_sessionmaker(db_session.bind, expire_on_commit=False)
    )
    db_session.add(Project(id="q", tenant_id="t", owner_id="owner", name="Other project"))
    await db_session.flush()
    db_session.add(UserProject(id="scope-q", project_id="q", user_id="owner", role="owner"))
    db_session.add(Tenant(id="z", name="Other tenant", slug="separate-tenant", owner_id="owner"))
    await db_session.flush()
    db_session.add(Project(id="r", tenant_id="z", owner_id="owner", name="Other tenant project"))
    await db_session.flush()
    db_session.add_all(
        [
            UserTenant(id="t-z", tenant_id="z", user_id="owner", role="owner"),
            UserProject(id="p-r", project_id="r", user_id="owner", role="owner"),
        ]
    )
    await db_session.commit()
    return app, keys


async def test_directory_exports_only_actual_core_memberships(  # noqa: PLR0915
    http, db_session, core, releases, monkeypatch
):
    public, first, second = releases
    app, keys = await _project_host(http, db_session, core, public, monkeypatch)
    actor = {"Authorization": "Bearer " + keys["owner"]}
    viewer = {"Authorization": "Bearer " + keys["viewer"]}
    base = "/api/v1/platform-plugins/v2/optional-business"
    list_path = "/api/v1/tenants/t/projects/p/workspaces"
    other_path = "/api/v1/tenants/t/projects/q/workspaces"
    async with serve_project_api(app) as origin, httpx.AsyncClient(base_url=origin) as api:
        title = '=1, "分析"'

        async def create(path, name, headers):
            result = await api.post(
                path,
                headers={**headers, "Idempotency-Key": uuid4().hex},
                json={"name": name, "metadata": {"private": "metadata-is-not-an-export-column"}},
            )
            assert result.status_code == 201, result.text
            return result.json()["id"]

        visible = await create(list_path, title, actor)
        other = await create(other_path, "other project", actor)
        tenant_path = "/api/v1/tenants/z/projects/r/workspaces"
        await create(tenant_path, "other tenant", actor)

        async def report(path, headers):
            return await api.get(path, headers=headers, params={"export_package": PACKAGE})

        for raw, column, state in ((first, "archived", "false"), (second, "lifecycle", "current")):
            installed = await api.post(
                base + "/install",
                headers=actor,
                json={
                    "tenant_id": "t",
                    "project_id": "p",
                    "approved_permissions": [
                        *WORKSPACE_COLLABORATION_OPERATIONS,
                        "app.workspace.chat.read",
                        "app.workspace.chat.send",
                        "app.workspace.blackboard.read",
                        "app.workspace.blackboard.write",
                        "ui.slot",
                        "tools.execute",
                        "app.workspace.directory.read",
                        "app.workspace.overview.read",
                        "app.workspace.detail.read",
                        "app.workspace.create",
                        "app.workspace.settings.update",
                    ],
                    "archive_base64": base64.b64encode(raw).decode(),
                },
            )
            assert installed.is_success, installed.text
            enabled = await api.post(
                f"{base}/{PACKAGE}/enable",
                headers=actor,
                json={"tenant_id": "t", "project_id": "p"},
            )
            assert enabled.is_success, enabled.text
            await _verify_directory_command(api, base, actor, visible)
            await _verify_group_chat(api, base, actor, visible, other)

            await _verify_detail_command(api, base, actor, viewer, visible, other, title)
            response = await report(list_path, actor)
            assert response.is_success, response.text
            assert response.headers["content-type"].startswith("text/csv")
            assert "attachment" in response.headers["content-disposition"]
            result = list(csv.DictReader(io.StringIO(response.text, newline="")))
            assert [(r["workspace_id"], r["name"], r[column]) for r in result] == [
                (visible, "'" + title, state)
            ]
            assert "metadata-is-not" not in response.text
        restored = await api.post(
            f"{base}/{PACKAGE}/rollback", headers=actor, json={"tenant_id": "t", "project_id": "p"}
        )
        assert restored.is_success
        assert (
            next(csv.DictReader(io.StringIO((await report(list_path, actor)).text)))["name"]
            == "'" + title
        )
        assert [r["name"] for r in (await api.get(other_path, headers=actor)).json()] == [
            "other project"
        ]
        assert (await report(other_path, actor)).status_code == 409
        assert (await report(tenant_path, actor)).status_code == 409
        assert (await report(tenant_path, viewer)).status_code in (403, 404)
        assert [r["name"] for r in (await api.get(tenant_path, headers=actor)).json()] == [
            "other tenant"
        ]
        assert (await api.get(list_path, headers=viewer)).json() == []
        assert (await report(list_path, viewer)).status_code == 403
        other_member = await db_session.get(UserProject, "up-viewer")
        other_member.role = "admin"
        await db_session.commit()
        member_export = await report(list_path, viewer)
        assert member_export.is_success and len(member_export.text.splitlines()) == 1
        private = await create(list_path, "Second member workspace", viewer)
        my_rows = list(csv.DictReader(io.StringIO((await report(list_path, viewer)).text)))
        assert [r["workspace_id"] for r in my_rows] == [private]
        assert private not in (await report(list_path, actor)).text

        await _verify_exported_pages(api, list_path, actor, create, report)
        await _verify_workspace_writes(api, base, actor, viewer, other)


async def _verify_directory_command(api, base, actor, visible):
    async def directory(headers, payload):
        return await api.post(
            f"{base}/{PACKAGE}/commands",
            headers=headers,
            json={
                "tenant_id": "t",
                "project_id": "p",
                "command_id": "list-directory",
                "payload": payload,
            },
        )

    directory_result = await directory(actor, {"limit": 1})
    assert directory_result.is_success, directory_result.text
    assert directory_result.json()["rows"][0]["id"] == visible
    cards = await directory(actor, {"cards": True, "limit": 100})
    assert cards.is_success, cards.text
    assert cards.json()["rows"][0]["id"] == visible
    assert "metadata-is-not" not in cards.text
    sources = await directory(actor, {"summary_for": visible})
    assert sources.is_success, sources.text
    assert set(sources.json()) == {"tasks", "plan", "objectives"}
    assert "metadata-is-not" not in directory_result.text
    assert (await directory(actor, {"user_id": "viewer"})).status_code == 422


async def _verify_exported_pages(api, list_path, actor, create, report):
    # A page spanning multiple bounded Wasm invocations still has exactly one header.
    for i in range(8):
        await create(list_path, f"批次-{i}-" + "中" * 240, actor)
    paged = {"limit": 8, "offset": 1}
    original = (await api.get(list_path, headers=actor, params=paged)).json()
    exported = await api.get(list_path, headers=actor, params={**paged, "export_package": PACKAGE})
    assert exported.is_success, exported.text
    assert [r["workspace_id"] for r in csv.DictReader(io.StringIO(exported.text))] == [
        r["id"] for r in original
    ]
    whole = await report(list_path, actor)
    assert whole.is_success and whole.text.count("workspace_id,name,office_status,archived") == 1
    assert len(list(csv.DictReader(io.StringIO(whole.text)))) == 9


async def _verify_detail_command(api, base, actor, viewer, visible, other, title):
    async def detail(workspace, headers):
        return await api.post(
            f"{base}/{PACKAGE}/commands",
            headers=headers,
            json={
                "tenant_id": "t",
                "project_id": "p",
                "command_id": "read-workspace",
                "payload": {"workspace_id": workspace},
            },
        )

    own_detail = await detail(visible, actor)
    assert own_detail.status_code == 200, own_detail.text
    assert own_detail.json()["name"] == title and set(own_detail.json()) == {
        "id",
        "name",
        "description",
        "office_status",
        "is_archived",
    }
    assert (await detail(other, actor)).status_code in (403, 404)
    assert (await detail(visible, viewer)).status_code in (403, 404)
    assert (await detail("../other", actor)).status_code == 422

    async def surface(workspace, resource):
        return await api.post(
            f"{base}/{PACKAGE}/commands",
            headers=actor,
            json={
                "tenant_id": "t",
                "project_id": "p",
                "command_id": "blackboard-read",
                "payload": {"workspace_id": workspace, "resource": resource},
            },
        )

    projected = await surface(visible, "objectives")
    assert projected.is_success, projected.text
    assert "items" in projected.json()["data"]
    assert (await surface(other, "objectives")).status_code in (403, 404)
    assert (await surface(visible, "../credentials")).status_code == 422


async def _verify_workspace_writes(api, base, actor, viewer, other):
    async def invoke(command, payload, headers=actor):
        return await api.post(
            f"{base}/{PACKAGE}/commands",
            headers=headers,
            json={"tenant_id": "t", "project_id": "p", "command_id": command, "payload": payload},
        )

    payload = {
        "request_id": str(uuid4()),
        "name": "Release planning",
        "description": "Release milestones",
    }
    created = await invoke("create-workspace", payload)
    assert created.is_success, created.text
    identity = created.json()["id"]
    retry = await invoke("create-workspace", payload)
    assert retry.is_success and retry.json()["id"] == identity
    assert (await invoke("create-workspace", {**payload, "tenant_id": "spoof"})).status_code == 422
    detail = await invoke("read-workspace", {"workspace_id": identity, "include_revision": True})
    assert detail.is_success
    change = {
        "workspace_id": identity,
        "expected_revision": detail.json()["revision"],
        "request_id": str(uuid4()),
        "name": "Next release",
        "is_archived": True,
    }
    assert (await invoke("update-workspace", change, viewer)).status_code in (403, 404)
    assert (await invoke("update-workspace", {**change, "workspace_id": other})).status_code in (
        403,
        404,
    )
    for topic in ("members", "posts", "tasks"):
        wrong_scope = await invoke("list-" + topic, {"workspace_id": other})
        assert wrong_scope.status_code in (403, 404)
        forbidden = await invoke(
            "change-" + topic,
            {
                "workspace_id": identity,
                "action": "delete",
                "id": "any",
                "request_id": str(uuid4()),
                "expected_revision": 0,
            },
            viewer,
        )
        assert forbidden.status_code in (403, 404)
    updated = await invoke("update-workspace", change)
    assert updated.is_success, updated.text
    stale = await invoke(
        "update-workspace", {**change, "name": "Stale", "request_id": str(uuid4())}
    )
    assert stale.status_code == 409
    saved = await invoke("read-workspace", {"workspace_id": identity})
    assert saved.json()["name"] == "Next release" and saved.json()["is_archived"] is True


@pytest.mark.parametrize("http", ["package-kernel"], indirect=True)
@pytest.mark.skipif(
    os.getenv("WEB_PACKAGE_CHROMIUM_TESTS") != "1",
    reason="requires Chromium and the package client",
)
async def test_signed_workspace_forms_persist_in_workspace_core(
    http, db_session, core, releases, monkeypatch, tmp_path
):
    import asyncio

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from playwright.async_api import async_playwright, expect

    from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
        get_password_hash,
    )
    from src.infrastructure.adapters.secondary.persistence.models import User

    public, archive, _ = releases
    app, keys = await _project_host(http, db_session, core, public, monkeypatch)
    api, _ = http
    base = "/api/v1/platform-plugins/v2/optional-business"
    actor = {"Authorization": f"Bearer {keys['owner']}"}
    scope = {"tenant_id": "t", "project_id": "p"}
    body = {**scope, "archive_base64": base64.b64encode(archive).decode()}
    inspect = await api.post(base + "/inspect", json=body, headers=actor)
    inspect.raise_for_status()
    installed = await api.post(
        base + "/install",
        json={**body, "approved_permissions": inspect.json()["permissions"]},
        headers=actor,
    )
    installed.raise_for_status()
    (await api.post(f"{base}/{PACKAGE}/enable", json=scope, headers=actor)).raise_for_status()

    # Visiting Workspace Core as this project principal populates its membership projection.
    # Member administration below still runs as the workspace owner.
    viewer_context = await api.post(
        "/api/v1/tenants/t/projects/p/workspaces",
        headers={"Authorization": "Bearer " + keys["viewer"], "X-Tenant-Id": "t"},
        json={"name": "Viewer onboarding"},
    )
    assert viewer_context.status_code in (201, 403), viewer_context.text

    password = secrets.token_urlsafe(24)
    owner = await db_session.get(User, "owner")
    owner.hashed_password = get_password_hash(password)
    await db_session.commit()
    output = tmp_path / "web"
    build = await asyncio.create_subprocess_exec(
        "pnpm",
        "exec",
        "vite",
        "build",
        "--mode",
        "project-packages",
        "--outDir",
        str(output),
        cwd=ROOT / "web",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    log, _ = await build.communicate()
    assert build.returncode == 0, log.decode()[-2000:]

    async def shell():
        return FileResponse(output / "project-packages.html")

    app.add_api_route("/tenant/t/project/p/workspaces/{path:path}", shell)
    app.add_api_route("/tenant/t/project/p/blackboard", shell)
    app.mount("/", StaticFiles(directory=output), name="workspace-package-shell")
    async with serve_project_api(app) as origin, async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(locale="en-US")
        await page.goto(origin + "/tenant/t/project/p/workspaces/new?tenant=t&project=p")
        await page.get_by_label("Email", exact=True).fill(owner.email)
        await page.get_by_label("Password", exact=True).fill(password)
        await page.get_by_role("button", name="Sign In", exact=True).click()
        await _edit_workspace_in_browser(page, expect)
        await browser.close()


async def _edit_workspace_in_browser(page, expect):
    guest = page.frame_locator("iframe[data-page-ready=true]").frame_locator("iframe")
    await guest.get_by_label("Workspace name").fill("Shared planning")
    await guest.locator("#workspace-description-input").fill("Coordinate the release milestones")
    await guest.get_by_role("radio", name="Research", exact=False).click()
    await guest.get_by_role("radio", name="Shared team", exact=False).click()
    async with page.expect_response(lambda r: "/commands" in r.url) as pending:
        await guest.locator('button[form="workspace-create-form"]').click()
    response = await pending.value
    assert response.ok, (response.status, await response.text())
    await _post_in_workspace(page, guest, expect)
    await _create_workspace_task(page, guest, expect)
    await _update_workspace_settings(page, guest, expect)


async def _post_in_workspace(page, guest, expect):
    discussion = guest.get_by_role("tab", name=re.compile("Discussion"))
    await discussion.click()
    await guest.get_by_role("button", name="+ Create Post", exact=True).click()
    await guest.locator("#blackboard-post-title").fill("First announcement")
    await guest.locator("#blackboard-post-content").fill("Shared release notes")
    await guest.get_by_role("button", name="Create Post", exact=True).click()
    await expect(guest.get_by_text("First announcement", exact=True).first).to_be_visible()
    await page.reload()
    await discussion.click()
    await guest.get_by_text("First announcement", exact=True).first.click()
    await expect(guest.get_by_text("Shared release notes", exact=True)).to_be_visible()
    await guest.get_by_role("button", name="Edit", exact=True).click()
    await guest.get_by_label("Title", exact=True).fill("Updated announcement")
    await guest.get_by_role("button", name="Save", exact=True).click()
    await expect(guest.get_by_role("heading", name="Updated announcement")).to_be_visible()
    await guest.get_by_role("button", name="Pin", exact=True).click()
    await expect(guest.get_by_role("button", name="Unpin", exact=True)).to_be_visible()
    await guest.get_by_role("button", name="Delete", exact=True).click()
    await guest.locator(".ant-popconfirm-buttons .ant-btn-primary").click()
    await expect(guest.get_by_role("button", name="+ Create Post", exact=True)).to_be_visible()
    await expect(guest.get_by_text("Updated announcement", exact=True)).to_have_count(0)


async def _create_workspace_task(page, guest, expect):
    await guest.get_by_role("tab", name=re.compile("Goals")).click()
    await guest.get_by_role("button", name="Add", exact=True).first.click()
    task = guest.get_by_label("Task title")
    await task.fill("Follow up")
    async with page.expect_response(
        lambda r: r.url.endswith("/commands")
        and r.request.post_data_json.get("command_id") == "blackboard-change"
    ) as submitted:
        await task.press("Enter")
    created = await submitted.value
    assert created.ok, await created.text()
    await expect(guest.get_by_text("Follow up", exact=True).first).to_be_visible(timeout=30000)
    await page.reload()
    await guest.get_by_role("tab", name=re.compile("Goals")).click()
    await expect(guest.get_by_text("Follow up", exact=True).first).to_be_visible(timeout=30000)
    await guest.get_by_role("button", name="Open task details").first.click()
    close_task = guest.get_by_role("button", name="Close task details")
    await expect(close_task).to_be_visible()
    await expect(page).to_have_url(re.compile(r"(?:/tasks/|[?&]taskId=)[^&#?]+"))
    await page.reload()
    await expect(close_task).to_be_visible()
    await close_task.click()
    await expect(close_task).to_have_count(0)


async def _update_workspace_settings(page, guest, expect):
    await guest.get_by_role("tab", name=re.compile("Settings")).click()
    await guest.get_by_placeholder("Enter user email or ID").fill("viewer")
    await guest.get_by_role("button", name="Add Member", exact=True).click()
    member = guest.get_by_role("row").filter(has_text="viewer").first
    await expect(member).to_be_visible()
    await member.locator(".ant-select").click()
    await guest.locator(".ant-select-item-option").filter(has_text="Editor").click()
    await expect(member).to_contain_text("Editor")
    await member.get_by_role("button", name="Remove member").click()
    await guest.locator(".ant-popconfirm-buttons .ant-btn-primary").click()
    await expect(member).to_have_count(0)
    await guest.locator("#workspace-name").fill("Release council")
    await guest.locator("#workspace-archive").click()
    async with page.expect_response(
        lambda r: r.url.endswith("/commands")
        and r.request.post_data_json.get("command_id") == "blackboard-change"
    ) as submitted:
        await guest.get_by_role("button", name=re.compile(r"^(Save|common\.save)$")).click()
    saved = await submitted.value
    assert saved.ok, await saved.text()
    await expect(
        guest.get_by_role("button", name=re.compile(r"^(Save|common\.save)$"))
    ).to_be_disabled()
    await page.reload()
    await guest.get_by_role("tab", name=re.compile("Settings")).click()
    await expect(guest.locator("#workspace-name")).to_have_value("Release council")
    await expect(guest.locator("#workspace-archive")).to_have_attribute("aria-checked", "true")


async def _verify_group_chat(api, base, actor, workspace, other):
    async def invoke(command_id, payload):
        return await api.post(
            f"{base}/{PACKAGE}/commands",
            headers=actor,
            json={
                "tenant_id": "t",
                "project_id": "p",
                "command_id": command_id,
                "payload": payload,
            },
        )

    roster = await invoke("read-group-chat", {"workspace_id": workspace, "view": "roster"})
    assert roster.is_success and isinstance(roster.json()["members"], list), roster.text
    text = "Group message " + uuid4().hex
    fields = {
        "workspace_id": workspace,
        "content": text,
        "mentions": [],
        "request_id": str(uuid4()),
    }
    message = await invoke("send-group-message", fields)
    assert message.is_success, message.text
    replay = await invoke("send-group-message", fields)
    assert replay.json()["message"]["id"] == message.json()["message"]["id"]
    history = await invoke("read-group-chat", {"workspace_id": workspace, "view": "messages"})
    assert history.is_success
    assert len([msg for msg in history.json()["messages"] if msg["content"] == text]) == 1
    foreign = await invoke("read-group-chat", {"workspace_id": other, "view": "messages"})
    assert foreign.status_code in (403, 404)
    assert message.json()["message"]["sender_id"] == history.json()["principal_id"]
    denied = await invoke("send-group-message", {**fields, "workspace_id": other})
    assert denied.status_code in (403, 404)
    invalid = await invoke("send-group-message", {**fields, "sender_id": "someone-else"})
    assert invalid.status_code == 400
