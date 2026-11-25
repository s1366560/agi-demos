"""Mount and switch real signed renderer code on either HTTP host."""

import base64
import hashlib
import json

import pytest
from memstack_plugin_sdk.rich_pages import parse_rich_pages

from src.tests.unit.routers.test_optional_business_http_v2 import http, publisher  # noqa: F401

pytestmark = pytest.mark.unit
BASE = "/api/v1/platform-plugins/v2/optional-business"


def asset(name, data):
    return {"path": name, "digest": "sha256:" + hashlib.sha256(data).hexdigest()}


def page(script=b"app.mount(1)"):
    return {
        "id": "notes",
        "title": "Project notes",
        "targets": ["web", "desktop-renderer"],
        "routes": ["/notes/:project"],
        "commands": ["ping"],
        "entry": asset("app.js", script),
        "style": asset("app.css", b"main{padding:1em}"),
    }


@pytest.mark.parametrize(
    "modify",
    [
        {"entry": asset("../app.js", b"bad")},
        {"routes": ["//elsewhere"]},
        {"routes": ["/LOGIN/callback/:who"]},
        {"routes": ["/tenant/:tenantId/plugins/manage"]},
        {"routes": ["/tenant/:tenantId/org-settings/info"]},
        {"routes": ["/tenant/:tenantId/org-settings/:tab"]},
        {"routes": ["/tenant/:wrong/project/:projectId/ok"]},
        {"routes": ["/:unbounded"]},
        {"commands": ["undeclared"]},
        {"voice_authorization": "unlisted"},
        {"commands": None, "voice_authorization": "ping"},
        {"commands": [], "voice_authorization": "ping"},
        {"scope": "tenant", "routes": ["/tenant/:tenantId/account"], "voice_authorization": "ping"},
        {"routes": ["/:id/:id"]},
        {"targets": []},
        {"home": "true"},
        {"workbench": "true"},
        {"navigation_actions": ["undefined"]},
        {"navigation_actions": ["primary-create", "primary-create"]},
        {"sidebar": {"rename": {"command": "unlisted"}}},
        {"sidebar": {"rows": {"command": "ping", "row_route": "/login"}}},
        {"sidebar": {"rows": {"command": "ping", "inputs": {"token": []}}}},
        {"page_links": ["other/../page"]},
        {"page_links": ["other/page", "other/page"]},
        {"anchored_slots": {"bad": "child/pane"}},
        {"anchored_slots": {"pane@1": "child/../pane"}},
        {"slots": ["pane@1"], "anchored_slots": {"pane@1": "child/pane"}},
        {"contributes_to": "unversioned"},
        {"routes": [], "contributes_to": "pkg/status@1", "slots": ["nested@1"]},
        {"routes": [], "contributes_to": "pkg/status@1", "home": True},
        {"slots": ["status@1", "status@1"]},
    ],
)
def test_invalid_rich_declarations(modify):
    with pytest.raises(ValueError):
        parse_rich_pages([{**page(), **modify}], {"ping"})


def test_signed_embedded_views_use_versioned_slots_and_have_no_navigation_route():
    owner, widget = parse_rich_pages(
        [
            {**page(), "slots": ["recent@1"]},
            {
                **page(),
                "id": "summary",
                "routes": [],
                "contributes_to": "memstack-workspace/recent@1",
            },
        ],
        {"ping"},
    )
    assert owner.descriptor()["slots"] == ("recent@1",)
    assert widget.descriptor()["contributes_to"] == "memstack-workspace/recent@1"
    assert not widget.routes


def test_voice_is_exposed_only_by_a_declared_project_authorization_command():
    (entry,) = parse_rich_pages([{**page(), "voice_authorization": "ping"}], {"ping"})
    assert entry.descriptor()["voice_authorization"] == "ping"


def test_anchored_slot_binds_versioned_position_to_specific_child():
    (owner,) = parse_rich_pages([{**page(), "anchored_slots": {"side@1": "child/panel"}}], {"ping"})
    assert owner.descriptor()["anchored_slots"] == {"side@1": "child/panel"}


def test_workbench_layout_is_opt_in_per_target():
    web, desktop = parse_rich_pages(
        [
            {**page(), "targets": ["web"], "workbench": True},
            {**page(), "targets": ["desktop-renderer"]},
        ],
        {"ping"},
    )
    assert web.descriptor()["workbench"] is True
    assert "workbench" not in desktop.descriptor()


def test_shell_actions_do_not_require_specific_command_or_route_names():
    (entry,) = parse_rich_pages([{**page(), "navigation_actions": ["group-create"]}], {"ping"})
    assert entry.descriptor()["navigation_actions"] == ("group-create",)


def test_link_destination_is_bound_to_a_package_and_page():
    (declared,) = parse_rich_pages([{**page(), "page_links": ["other/page"]}], {"ping"})
    assert declared.descriptor()["page_links"] == ("other/page",)


def test_home_is_declared_by_the_signed_page():
    (declared,) = parse_rich_pages([{**page(), "home": True}], {"ping"})
    (existing,) = parse_rich_pages([page()], {"ping"})
    assert declared.descriptor()["home"] is True
    assert "home" not in existing.descriptor()


def test_shared_workbench_entry_is_verified_once_and_mismatched_alias_is_rejected(monkeypatch):
    from types import SimpleNamespace

    from memstack_plugin_sdk.rich_pages import PageAsset

    from src.infrastructure.plugins.v2.project_plugin_package import _ui_files

    raw = b"start()"
    shared = PageAsset(**asset("app.js", raw))
    other = PageAsset(**asset("app.js", b"changed()"))
    checked = []
    verify = PageAsset.verify

    def observe(self, content):
        checked.append(self)
        return verify(self, content)

    monkeypatch.setattr(PageAsset, "verify", observe)
    pages = [SimpleNamespace(assets=(shared,)), SimpleNamespace(assets=(shared,))]
    contribution = SimpleNamespace(commands=(), ui=(), pages=pages)
    assert _ui_files(contribution, {"pages/app.js": raw}) == {"pages/app.js": raw}
    assert checked == [shared]
    pages.append(SimpleNamespace(assets=(other,)))
    with pytest.raises(ValueError, match="signed digest"):
        _ui_files(contribution, {"pages/app.js": raw})


def test_sdk_stages_declared_assets_and_checks_digests(tmp_path):
    from memstack_plugin_sdk.pack import stage_contribution

    source = tmp_path / "source"
    dest = tmp_path / "stage"
    source.mkdir()
    desc = page()
    desc["commands"] = []
    data = {"schema": "memstack.plugin.contributions/1", "pages": [desc]}
    (source / "contributions.json").write_text(json.dumps(data))
    (source / "app.js").write_bytes(b"app.mount(1)")
    (source / "app.css").write_bytes(b"main{padding:1em}")
    stage_contribution(source, dest)
    assert (dest / "app.js").read_bytes() == b"app.mount(1)"
    (source / "app.js").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="digest"):
        stage_contribution(source, dest)


async def test_signed_page_lifecycle(http, publisher, tmp_path):  # noqa: F811
    client, keys = http
    scope = {"tenant_id": "t", "project_id": "p"}
    headers = {"Authorization": "Bearer " + keys["owner"]}
    base = BASE + "/sample.notes"
    (tmp_path / "app.css").write_bytes(b"main{padding:1em}")

    async def activate(plugin, version, code):
        script = code.encode()
        (tmp_path / "app.js").write_bytes(script)
        body, digest = publisher[1](
            version,
            plugin_id=plugin,
            pages=[{**page(script), "sidebar": {"rows": {"command": "ping"}}}],
        )
        assert (await client.post(BASE + "/install", json=body, headers=headers)).is_success
        enabled = await client.post(f"{BASE}/{plugin}/enable", json=scope, headers=headers)
        return digest, enabled

    async def read(digest, target):
        return await client.get(
            base + "/ui",
            params={**scope, "page_id": "notes", "expected_digest": digest, "target": target},
            headers=headers,
        )

    first, enabled = await activate("sample.notes", "1.0.0", "app.mount(1)")
    assert enabled.is_success
    overview = await client.get(BASE + "/", params=scope, headers=headers)
    assert overview.json()["items"][0]["pages"][0]["routes"] == ["/notes/:project"]
    assert overview.json()["items"][0]["pages"][0]["sidebar"]["rows"] == {"command": "ping"}
    for target in ("web", "desktop-renderer"):
        item = (await read(first, target)).json()
        assert item["release_digest"] == first
        assert item["commands"] == ["ping"]
        assert base64.b64decode(item["entry"]["bytes_base64"]) == b"app.mount(1)"
        assert base64.b64decode(item["style"]["bytes_base64"]) == b"main{padding:1em}"
    assert (await read(first, "desktop-sidecar")).status_code == 404
    _, duplicate = await activate("other.notes", "1.0.0", "app.mount(1)")
    assert duplicate.status_code == 409
    second, upgraded = await activate("sample.notes", "1.1.0", "app.mount(2)")
    assert upgraded.is_success and first != second
    assert (await read(first, "web")).status_code == 409
    assert (
        base64.b64decode((await read(second, "web")).json()["entry"]["bytes_base64"])
        == b"app.mount(2)"
    )
    streamed = await client.post(
        base + "/commands?stream=true",
        json={**scope, "command_id": "ping", "expected_digest": second},
        headers=headers,
    )
    assert streamed.headers["content-type"] == "application/x-ndjson"
    assert json.loads(streamed.text)["type"] == "result"
    assert (await client.post(base + "/rollback", json=scope, headers=headers)).is_success
    assert (await read(first, "web")).is_success


async def test_stream_keeps_admitted_release_and_suppresses_withdrawn_output(
    http,  # noqa: F811
    publisher,  # noqa: F811
    monkeypatch,
):
    import asyncio

    from src.infrastructure.adapters.primary.web.routers import optional_business_http_v2 as router

    client, keys = http
    scope = {"tenant_id": "t", "project_id": "p"}
    headers = {"Authorization": "Bearer " + keys["owner"]}
    path = BASE + "/sample.notes"
    started, finish = asyncio.Event(), asyncio.Event()
    original = router._stream_operation

    async def pause(package, binding, body, progress, application):
        started.set()
        await finish.wait()
        return await original(package, binding, body, progress, application)

    monkeypatch.setattr(router, "_stream_operation", pause)

    async def post(endpoint, body):
        response = await client.post(endpoint, json=body, headers=headers)
        assert response.is_success, response.text
        return response

    async def activate(release):
        body, digest = release
        await post(BASE + "/install", body)
        await post(path + "/enable", scope)
        return digest

    async def begin(digest):
        call = asyncio.create_task(
            post(
                path + "/commands?stream=true",
                {
                    **scope,
                    "command_id": "ping",
                    "expected_digest": digest,
                },
            )
        )
        await asyncio.wait_for(started.wait(), timeout=5)
        return call

    first = await activate(publisher[1]())
    stream = await begin(first)
    second = await activate(publisher[1]("1.1.0", result="pong"))
    finish.set()
    assert json.loads((await stream).text) == {"type": "result", "data": {"ok": True, "op": "ping"}}
    started.clear()
    finish.clear()
    stream = await begin(second)
    await post(path + "/disable", scope)
    finish.set()
    frames = [json.loads(line) for line in (await stream).text.splitlines()]
    assert frames[-1]["type"] == "error"
    assert not any(frame["type"] in ("progress", "result") for frame in frames)


async def test_application_command_requires_install_grant_registered_authority_and_project(
    http,  # noqa: F811
    publisher,  # noqa: F811
):
    client, keys = http
    body, digest = publisher[1](application_command="app.inventory.supplier.read")
    headers = {"Authorization": "Bearer " + keys["owner"]}
    denied = await client.post(
        BASE + "/install",
        json={**body, "approved_permissions": ["tools.execute", "ui.slot"]},
        headers=headers,
    )
    assert denied.status_code == 400
    assert (await client.post(BASE + "/install", json=body, headers=headers)).is_success
    base = BASE + "/sample.notes"
    scope = {"tenant_id": "t", "project_id": "p"}
    assert (await client.post(base + "/enable", json=scope, headers=headers)).is_success
    command = {**scope, "command_id": "chat", "expected_digest": digest, "payload": {"page": 1}}
    assert (await client.post(base + "/commands", json=command, headers=headers)).status_code == 503
    calls = []

    async def execute(ctx, payload, _progress):
        calls.append((ctx.user.id, ctx.scope.tenant_id, ctx.scope.project_id, payload))
        return {"items": []}

    client._transport.app.state.package_operations_v1 = {"app.inventory.supplier.read": execute}
    assert (
        await client.post(
            base + "/commands", json={**command, "project_id": "second"}, headers=headers
        )
    ).status_code == 404
    assert (await client.post(base + "/commands", json=command, headers=headers)).json() == {
        "items": []
    }
    assert calls == [("owner", "t", "p", {"page": 1})]
    assert (await client.post(base + "/disable", json=scope, headers=headers)).is_success
    assert (await client.post(base + "/commands", json=command, headers=headers)).status_code >= 400
    assert len(calls) == 1


async def test_configured_runtime_double_checks_project_and_release_over_tcp(
    http,  # noqa: F811
    publisher,  # noqa: F811
):
    import asyncio
    import socket

    import uvicorn

    from src.host.transport.package_kernel import create_app

    client, keys = http
    kernel = client._transport.app
    runtime = create_app()
    runtime.dependency_overrides.update(kernel.dependency_overrides)
    runtime.state.plugin_marketplace_trusted_public_keys_v2 = (publisher[0],)

    async def application(ctx, payload, progress):
        if progress:
            await progress({"actor": ctx.user.id})
        return {"project": ctx.scope.project_id, **payload}

    runtime.state.package_operations_v1 = {"app.agent.list": application}
    server = uvicorn.Server(
        uvicorn.Config(runtime, lifespan="off", access_log=False, log_level="error")
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(16)
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    await asyncio.sleep(0.01)
            kernel.state.package_operations_v1 = {}
            kernel.state.package_application_runtime_origin = (
                f"http://127.0.0.1:{listener.getsockname()[1]}"
            )
            body, digest = publisher[1](application_command="app.agent.list")
            headers = {"Authorization": "Bearer " + keys["owner"]}
            scope = {"tenant_id": "t", "project_id": "p"}
            base = BASE + "/sample.notes"
            assert (await client.post(BASE + "/install", json=body, headers=headers)).is_success
            assert (await client.post(base + "/enable", json=scope, headers=headers)).is_success
            command = {
                **scope,
                "command_id": "chat",
                "expected_digest": digest,
                "payload": {"input": "page"},
            }
            response = await client.post(
                base + "/commands?stream=true", json=command, headers=headers
            )
            assert [json.loads(line) for line in response.text.splitlines()] == [
                {"type": "progress", "data": {"actor": "owner"}},
                {"type": "result", "data": {"project": "p", "input": "page"}},
            ]
            runtime.state.package_operations_v1 = {}
            runtime.state.package_application_runtime_origin = (
                kernel.state.package_application_runtime_origin
            )
            denied = await client.post(base + "/commands", json=command, headers=headers)
            assert denied.status_code == 503
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, 10)


def test_same_target_parameter_shape_is_reserved_and_literal_remains_available():
    from memstack_plugin_sdk.rich_pages import route_bindings

    first = page()
    second = {**page(), "id": "replay", "routes": ["/notes/:conversation"]}
    with pytest.raises(ValueError):
        parse_rich_pages([first, second], {"ping"})
    literal = {**second, "routes": ["/notes/new"]}
    entries = parse_rich_pages([first, literal], {"ping"})
    assert len(route_bindings(entries)) == 4


async def test_route_ownership_survives_an_unreadable_enabled_sibling():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.host.packages.rich_pages import check_page_routes
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

    candidate = SimpleNamespace(
        plugin_id="candidate",
        contribution=SimpleNamespace(pages=parse_rich_pages([page()], {"ping"})),
    )
    service = SimpleNamespace(
        db=AsyncMock(),
        scope=SimpleNamespace(project_id="p"),
        active_release=AsyncMock(side_effect=ValueError("invalid stored archive")),
    )
    service.db.scalars.return_value = ["unreadable.release"]
    with pytest.raises(OptionalBusinessError, match="cannot verify active page routes"):
        await check_page_routes(service, candidate)


def test_worker_and_binary_assets_are_staged_and_digest_checked(tmp_path):
    from memstack_plugin_sdk.pack import stage_contribution

    source, destination = tmp_path / "package", tmp_path / "archive"
    source.mkdir()
    files = {
        "app.js": b"app.mount(1)",
        "app.css": b"main{padding:1em}",
        "layout.worker.js": b"self.postMessage(1)",
        "font.woff2": b"wOF2\xff\x00",
    }
    descriptor = {
        **page(),
        "commands": [],
        "query_params": ["filter"],
        "resources": [asset(name, files[name]) for name in ("layout.worker.js", "font.woff2")],
    }
    for path, data in files.items():
        (source / path).write_bytes(data)
    (source / "contributions.json").write_text(
        json.dumps({"schema": "memstack.plugin.contributions/1", "pages": [descriptor]})
    )
    stage_contribution(source, destination)
    assert (destination / "font.woff2").read_bytes() == files["font.woff2"]
    (source / "layout.worker.js").write_bytes(b"another worker")
    with pytest.raises(ValueError, match="digest"):
        stage_contribution(source, destination)
