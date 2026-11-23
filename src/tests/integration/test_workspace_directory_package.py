"""Export real member-visible Workspace Core directories through the production proxy and guest."""

import base64
import csv
import io
import os
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
from plugins.business.workspace.backend.workspace_directory_export import (
    read_directory_operation,
    read_workspace_operation,
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


async def test_directory_exports_only_actual_core_memberships(
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
                        "ui.slot",
                        "tools.execute",
                        "app.workspace.directory.read",
                        "app.workspace.detail.read",
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
