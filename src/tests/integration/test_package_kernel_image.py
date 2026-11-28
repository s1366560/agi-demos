"""A fixed deployment image admits externally produced releases on two real API replicas."""

import json
import os
import secrets
import subprocess
import time
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import docker
from src.tests.unit.routers import test_optional_business_http_v2 as project_fixtures

publisher = project_fixtures.publisher
_IMAGE = os.getenv("MEMSTACK_KERNEL_TEST_IMAGE")
_WEB_IMAGE = os.getenv("MEMSTACK_PACKAGE_WEB_TEST_IMAGE")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _IMAGE, reason="requires a locally built kernel image"),
]


def _wait_ready(api, container):
    for _ in range(160):
        try:
            if api.get("/health/ready").is_success:
                return
        except httpx.TransportError:
            pass
        container.reload()
        if container.status == "exited":
            # Report the startup exception, without emitting configuration or credentials.
            messages = container.logs(tail=150).decode(errors="replace").splitlines()
            errors = [line for line in messages if "Error:" in line or "Exception:" in line]
            pytest.fail(
                "kernel startup failed: " + (errors[-1].split(":")[0] if errors else "exited")
            )
        time.sleep(0.25)
    pytest.fail("kernel did not become ready")


@pytest.fixture
def business_signer():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def billing(tmp_path, business_signer):
    from plugins.business.billing.build import ROOT, build_release

    signer = business_signer
    key = tmp_path / "billing.pem"
    key.write_bytes(
        signer.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    package = tmp_path / "billing.mspkg"
    package.write_bytes(
        build_release(json.loads((ROOT / "plans.json").read_text()), version="3.1.0", signer=signer)
    )
    return key, package


@pytest.fixture
def replicas(request, publisher, billing, tmp_path):
    standalone = getattr(request, "param", "shared") == "standalone"
    identity = "kernelqa-" + uuid4().hex[:12]
    deployment_key = secrets.token_urlsafe(48)
    with ExitStack() as stack:
        engine = docker.from_env(timeout=60)
        stack.callback(engine.close)
        network = engine.networks.create(identity)
        stack.callback(network.remove)
        image = engine.images.get(_IMAGE).id

        def start(image_id, name, **kwargs):
            container = engine.containers.run(
                image_id, name=identity + name, network=network.name, detach=True, **kwargs
            )
            stack.callback(container.remove, force=True, v=True)
            return container

        pg = start(
            "postgres:16-alpine" if standalone else "pgvector/pgvector:pg16",
            "-pg",
            environment={"POSTGRES_HOST_AUTH_METHOD": "trust", "POSTGRES_DB": "kernelqa"},
        )
        cache = start("redis:7-alpine", "-redis")
        for _ in range(100):
            if (
                pg.exec_run(
                    ["pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", "kernelqa"]
                ).exit_code
                == 0
            ):
                break
            time.sleep(0.15)
        else:
            pytest.fail("isolated database did not start")
        database = tmp_path / "database.env"
        database.write_text(f"DATABASE_URL=postgresql+asyncpg://postgres@{pg.name}/kernelqa\n")
        pub = tmp_path / "publisher.pem"
        pub.write_text(publisher[0])
        other = tmp_path / "other.pem"
        other.write_bytes(
            Ed25519PrivateKey.generate()
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )

        owner = (
            ("owner@example.org", secrets.token_urlsafe(32))
            if standalone
            else ("admin@memstack.ai", "adminpassword")
        )
        initial_password = tmp_path / "initial-owner-password"
        initial_password.write_text(owner[1])
        initial_password.chmod(0o600)
        owner_mount = (
            {str(initial_password): {"bind": "/run/qa/initial-owner", "mode": "ro"}}
            if standalone
            else {}
        )

        def replica(label, key):
            container = start(
                image,
                label,
                ports={"8000/tcp": ("127.0.0.1", None)},
                networking_config={
                    network.name: engine.api.create_endpoint_config(
                        aliases=["api"] if label == "-one" else []
                    )
                },
                volumes={
                    **(owner_mount if label == "-one" else {}),
                    str(database): {"bind": "/app/.env", "mode": "ro"},
                    str(key): {"bind": "/run/qa/publisher.pem", "mode": "ro"},
                    str(billing[0]): {"bind": "/run/qa/billing.pem", "mode": "ro"},
                },
                environment={
                    "REDIS_HOST": cache.name,
                    "SECRET_KEY": deployment_key,
                    "ENVIRONMENT": "production" if standalone else "development",
                    "PACKAGE_KERNEL_DATABASE_MODE": "standalone" if standalone else "shared",
                    "PLUGIN_MARKETPLACE_TRUSTED_KEY_FILES": json.dumps(
                        ["/run/qa/publisher.pem", "/run/qa/billing.pem"]
                        if label == "-one"
                        else ["/run/qa/publisher.pem"]
                    ),
                },
            )
            container.reload()
            port = container.attrs["NetworkSettings"]["Ports"]["8000/tcp"][0]["HostPort"]
            api = stack.enter_context(httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5))
            _wait_ready(api, container)
            return api, container

        one, host = replica("-one", pub)
        two, _ = replica("-two", other)
        if standalone:
            provision = host.exec_run(
                [
                    "python",
                    "-m",
                    "src.cli.package_kernel_owner",
                    "--email",
                    owner[0],
                    "--tenant",
                    "QA",
                    "--project",
                    "Billing",
                    "--password-file",
                    "/run/qa/initial-owner",
                ]
            )
            assert provision.exit_code == 0
        probe = host.exec_run(
            [
                "python",
                "-c",
                "import importlib.util as u; assert all(u.find_spec(x) is None for x in ('ray','litellm','dashscope','playwright','lark_oapi','neo4j'))",
            ]
        )
        assert probe.exit_code == 0

        def web_origin():
            container = start(
                engine.images.get(_WEB_IMAGE).id, "-web", ports={"80/tcp": ("127.0.0.1", None)}
            )
            container.reload()
            port = container.attrs["NetworkSettings"]["Ports"]["80/tcp"][0]["HostPort"]
            return f"http://127.0.0.1:{port}"

        yield one, two, web_origin, owner


def test_image_uses_cloud_login_and_serves_only_prepared_releases(replicas, publisher):
    one, two, _, owner = replicas
    login = one.post(
        "/api/v1/auth/token",
        data={"username": owner[0], "password": owner[1]},
    )
    assert login.is_success, login.status_code
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    projects = one.get("/api/v1/project-packages/projects/", headers=headers)
    assert projects.is_success and projects.json()[0]["can_manage"]
    scope = {key: projects.json()[0][key] for key in ("tenant_id", "project_id")}
    root = "/api/v1/platform-plugins/v2/optional-business"
    plugin = root + "/sample.notes"
    for version, expected in (("1.0.0", "ping"), ("1.1.0", "pong")):
        release, digest = publisher[1](version, result=expected)
        staged = one.post(root + "/install", json={**release, **scope}, headers=headers)
        assert staged.is_success, staged.text
        assert one.post(plugin + "/enable", json=scope, headers=headers).is_success
        assert one.get("/health/ready").status_code == 200
        assert two.get("/health/ready").status_code == 503
        body = {**scope, "expected_digest": digest, "command_id": "ping"}
        result = one.post(plugin + "/commands", headers=headers, json=body)
        assert result.json()["op"] == expected
        assert two.post(plugin + "/commands", headers=headers, json=body).is_error
    assert one.post(plugin + "/rollback", headers=headers, json=scope).is_success
    assert (
        one.post(
            plugin + "/commands", headers=headers, json={**scope, "command_id": "ping"}
        ).json()["op"]
        == "ping"
    )
    assert one.post(plugin + "/disable", headers=headers, json=scope).is_success
    assert two.get("/health/ready").status_code == 200


@pytest.mark.skipif(not _WEB_IMAGE, reason="requires the built package Web image")
@pytest.mark.parametrize("replicas", ["standalone"], indirect=True)
def test_web_image_installs_billing_via_the_kernel(replicas, billing):
    from playwright.sync_api import expect, sync_playwright

    one, _, web_origin, owner = replicas
    origin = web_origin()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(locale="en-US")
        page.goto(origin + "/plugins")
        page.get_by_label("Email", exact=True).fill(owner[0])
        page.get_by_label("Password", exact=True).fill(owner[1])
        page.get_by_role("button", name="Sign In", exact=True).click()
        panel = page.get_by_test_id("plugin-market")
        expect(panel.get_by_text("More actions", exact=True)).to_be_visible()
        panel.get_by_label("Choose signed package").set_input_files(billing[1])
        page.get_by_role("dialog").get_by_role("button", name="Approve and enable").click()
        page.frame_locator('[data-testid="signed-business-slot"]').get_by_role(
            "button", name="Pro storage allowance"
        ).click()
        expect(panel.locator("pre")).to_contain_text("107374182400")
        assert one.get("/health/ready").status_code == 200
        browser.close()


@pytest.mark.skipif(not _WEB_IMAGE, reason="requires the built package Web image")
@pytest.mark.parametrize("replicas", ["standalone"], indirect=True)
def test_workspace_web_and_desktop_pages_upgrade_and_rollback(replicas, business_signer, tmp_path):
    from playwright.sync_api import expect, sync_playwright

    from src.tests.integration.signed_wasm_releases import build_upgrade_pair

    repo = Path(__file__).resolve().parents[3]
    desktop = repo / "agi-stack/apps/desktop"
    # Compile the actual desktop settings component and client once, before producing the releases.
    bundle = tmp_path / "renderer.js"
    subprocess.run(
        [
            "node",
            "-e",
            """
                const {createRequire} = require('node:module');
                createRequire(require.resolve('vite'))('esbuild').buildSync({
                  entryPoints: ['tests/package-page-browser-entry.tsx'], bundle: true,
                  outfile: process.argv[1], format: 'iife', globalName: 'desktopPages',
                  jsx: 'automatic', define: {'process.env.NODE_ENV': '"production"'},
                  alias: {react: require.resolve('react'), 'react/jsx-runtime': require.resolve('react/jsx-runtime')},
                });
            """,
            str(bundle),
        ],
        cwd=desktop,
        check=True,
    )
    _, first, upgrade = build_upgrade_pair(
        repo / "plugins/business/workspace",
        tmp_path,
        '("archived", "true", "false")',
        '("lifecycle", "archived", "current")',
        signer=business_signer,
        page_title="Workspace lifecycle directory",
    )
    one, _, web_origin, owner = replicas
    origin = web_origin()
    login = one.post("/api/v1/auth/token", data={"username": owner[0], "password": owner[1]})
    login.raise_for_status()
    token = login.json()["access_token"]
    project = one.get(
        "/api/v1/project-packages/projects/", headers={"Authorization": "Bearer " + token}
    )
    project.raise_for_status()
    scope = {key: project.json()[0][key] for key in ("tenant_id", "project_id")}
    row = {"id": "w", "name": "Browser export", "office_status": "active", "is_archived": False}
    form = json.dumps({"header": True, "rows": [row]})
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        web = browser.new_page(locale="en-US")
        renderer = browser.new_page(locale="en-US")
        renderer.route(
            "**/renderer-harness",
            lambda route: route.fulfill(
                body='<div id="root"></div>',
                content_type="text/html",
            ),
        )
        web.goto(origin + "/plugins")
        web.get_by_label("Email", exact=True).fill(owner[0])
        web.get_by_label("Password", exact=True).fill(owner[1])
        web.get_by_role("button", name="Sign In", exact=True).click()
        panel = web.get_by_test_id("plugin-market")
        for release, title, column in (
            (first, "Workspace directory", "archived"),
            (upgrade, "Workspace lifecycle directory", "lifecycle"),
            (None, "Workspace directory", "archived"),
        ):
            if release:
                expect(panel.get_by_text("More actions", exact=True)).to_be_visible()
                panel.get_by_label("Choose signed package").set_input_files(
                    {
                        "name": "workspace.mspkg",
                        "mimeType": "application/octet-stream",
                        "buffer": release,
                    }
                )
                web.get_by_role("dialog").get_by_role("button", name="Approve and enable").click()
            else:
                panel.get_by_text("More actions", exact=True).click()
                panel.get_by_role("button", name="Roll back to").click()
                web.get_by_role("dialog").get_by_role("button", name="Confirm").click()
            web_frame = web.frame_locator('[data-testid="signed-business-slot"]')
            expect(web_frame.get_by_role("heading", name=title, exact=True)).to_be_visible()
            renderer.goto(origin + "/renderer-harness")
            renderer.add_script_tag(path=bundle)
            renderer.evaluate("args => desktopPages.mountWorkspace(...args)", [token, scope])
            renderer.get_by_role("button", name="Open workspace").click()
            for frame, area in [(web_frame, panel), (renderer.frame_locator("iframe"), renderer)]:
                expect(frame.get_by_role("heading", name=title, exact=True)).to_be_visible()
                frame.get_by_label("Authorized directory rows (JSON)").fill(form)
                frame.get_by_role("button", name="Export CSV").click()
                expect(area.locator("pre")).to_contain_text(
                    "workspace_id,name,office_status," + column
                )
                expect(area.locator("pre")).to_contain_text("Browser export")
        browser.close()


@pytest.mark.skipif(not _WEB_IMAGE, reason="requires the built package Web image")
@pytest.mark.parametrize("replicas", ["standalone"], indirect=True)
def test_unknown_rich_page_deep_link_follows_release_while_hosts_stay_up(
    replicas, business_signer, tmp_path
):
    import base64

    from playwright.sync_api import expect, sync_playwright

    from src.tests.integration.rich_page_publisher import publish_page

    one, _, web_origin, owner = replicas
    login = one.post("/api/v1/auth/token", data={"username": owner[0], "password": owner[1]})
    login.raise_for_status()
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    project = one.get("/api/v1/project-packages/projects/", headers=headers).json()[0]
    scope = {key: project[key] for key in ("tenant_id", "project_id")}
    base = "/api/v1/platform-plugins/v2/optional-business"
    plugin = "qa-" + uuid4().hex
    route = "/" + plugin + "/labels"
    origin = web_origin()

    def activate(revision):
        archive = publish_page(tmp_path / str(revision), plugin, revision, business_signer)
        body = {**scope, "archive_base64": base64.b64encode(archive).decode()}
        preview = one.post(base + "/inspect", json=body, headers=headers)
        preview.raise_for_status()
        body["approved_permissions"] = preview.json()["permissions"]
        one.post(base + "/install", json=body, headers=headers).raise_for_status()
        one.post(base + "/" + plugin + "/enable", json=scope, headers=headers).raise_for_status()
        return preview.json()["digest"]

    first = activate(1)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        web = browser.new_page(locale="en-US")
        web.goto(origin + route)
        web.get_by_label("Email", exact=True).fill(owner[0])
        web.get_by_label("Password", exact=True).fill(owner[1])
        web.get_by_role("button", name="Sign In", exact=True).click()

        def verify(digest, revision):
            shell = web.frame_locator(
                f'iframe[data-page-ready="true"][data-release-digest="{digest}"]'
            )
            guest = shell.frame_locator("iframe")
            expect(guest.get_by_role("heading")).to_have_text(
                f"Inventory labels {revision}", timeout=20000
            )
            guest.get_by_role("button", name="Cloud label").click()
            expect(guest.locator("output")).to_contain_text(f"python-{revision}")
            frame = guest.locator("html")
            assert (
                frame.evaluate("memstack.device('device_label', {}).catch(e => e.message)")
                == "page_capability_unavailable"
            )
            assert frame.evaluate("memstack.invoke('get-label', undefined, {onEvent() {}})") == {
                "label": f"python-{revision}"
            }
            assert web.url == origin + route

        verify(first, 1)
        verify(activate(2), 2)
        one.post(base + "/" + plugin + "/rollback", headers=headers, json=scope).raise_for_status()
        web.reload()
        verify(first, 1)
        browser.close()
