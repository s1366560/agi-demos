"""Browse without downloading, review signed bytes, and change only the selected project."""

import base64

import httpx
import pytest

from src.configuration.config import get_settings
from src.host.packages.npm_catalog import version_key
from src.tests.unit.routers.test_npm_package_source import BASE, distribution
from src.tests.unit.routers.test_optional_business_http_v2 import http, publisher  # noqa: F401

pytestmark = pytest.mark.unit
SCOPE = {"tenant_id": "t", "project_id": "p"}
NAME = "sample.notes"
ORIGIN = "http://npm-registry:4873"


@pytest.fixture
def registry(monkeypatch, publisher):  # noqa: F811
    versions = {}
    payloads = {}
    digests = {}
    for version, options in (
        ("1.0.0", {}),
        ("1.10.0", {"result": "pong"}),
        ("2.0.0-beta.1", {"broken": True}),
    ):
        body, digests[version] = publisher[1](version, **options)
        meta, archive = distribution(NAME, version, base64.b64decode(body["archive_base64"]))
        path = f"/{NAME}/-/{NAME}-{version}.tgz"
        meta["dist"]["tarball"] = ORIGIN + path
        payloads[path] = archive
        versions[version] = {
            **meta,
            "files": ["plugin.mspkg"],
            "memstack": {"market": {"name": {"zh": "项目笔记"}, "icon": "notes"}},
        }

    calls = []
    settings = {"online": True, "latest": "1.10.0"}

    def respond(request):
        path = request.url.path
        calls.append(path)
        if not settings["online"]:
            raise httpx.ConnectError("offline")
        if path == "/-/all":
            return httpx.Response(
                200, json={NAME: {"name": NAME}, "ordinary": {"name": "ordinary"}}
            )
        if path == f"/{NAME}":
            return httpx.Response(
                200,
                json={
                    "name": NAME,
                    "versions": versions,
                    "dist-tags": {"latest": settings["latest"]},
                },
            )
        if path == "/ordinary":
            return httpx.Response(200, json={"name": "ordinary", "versions": {"1.0.0": {}}})
        if path in payloads:
            return httpx.Response(200, content=payloads[path])
        if path.startswith(f"/{NAME}/") and (version := path.split("/")[-1]) in versions:
            return httpx.Response(200, json=versions[version])
        return httpx.Response(404)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw)
    )
    monkeypatch.setattr(get_settings(), "package_npm_registry_url", ORIGIN)
    return settings, calls, digests


async def test_browse_and_review_as_a_project_member(http, registry):  # noqa: F811
    client, keys = http
    _, calls, digests = registry
    owner = {"Authorization": "Bearer " + keys["owner"]}
    viewer = {"Authorization": "Bearer " + keys["viewer"]}

    async def get(path, *, headers=owner, **params):
        return await client.get(BASE + "/npm/" + path, params={**SCOPE, **params}, headers=headers)

    assert (await get("catalog", headers=viewer, tenant_id="other")).status_code in (403, 404)
    assert calls == []
    browse = (await get("catalog", headers=viewer, q="笔记")).json()
    assert browse["can_manage"] is False and browse["can_execute"] is False
    assert browse["total"] == 1
    assert browse["items"][0]["display_name"] == {"zh": "项目笔记"}
    assert not any(path.endswith(".tgz") for path in calls)
    assert (await get("catalog", offset=1)).json()["items"] == []
    reviewed = (await get("detail", plugin_id=NAME, version="1.0.0")).json()
    assert reviewed["can_manage"] is True and reviewed["can_execute"] is True
    assert reviewed["installation"] is None
    assert reviewed["release"]["digest"] == digests["1.0.0"]
    assert set(reviewed["release"]["targets"]) == {"python", "web"}
    assert reviewed["versions"] == ["2.0.0-beta.1", "1.10.0", "1.0.0"]
    denied = await client.post(
        BASE + "/npm/apply",
        headers=viewer,
        json={
            **SCOPE,
            "package_name": NAME,
            "version": "1.0.0",
            "approved_permissions": reviewed["release"]["permissions"],
            "expected_revision": 0,
            "expected_digest": digests["1.0.0"],
        },
    )
    assert denied.status_code == 403


async def test_discover_review_and_activate_one_package(http, registry):  # noqa: F811
    client, keys = http
    settings, _, digests = registry
    owner = {"Authorization": "Bearer " + keys["owner"]}

    async def get(path, *, headers=owner, **params):
        return await client.get(BASE + "/npm/" + path, params={**SCOPE, **params}, headers=headers)

    async def detail(version=None):
        args = {"version": version} if version else {}
        response = await get("detail", plugin_id=NAME, **args)
        assert response.status_code == 200, response.text
        return response.json()

    async def apply(version, revision, **overrides):
        return await client.post(
            BASE + "/npm/apply",
            headers=owner,
            json={
                **SCOPE,
                "package_name": NAME,
                "version": version,
                "approved_permissions": ["tools.execute", "ui.slot"],
                "expected_revision": revision,
                "expected_digest": digests[version],
                **overrides,
            },
        )

    reviewed = await detail("1.0.0")
    assert (await apply("1.0.0", 0, expected_digest="sha256:" + "0" * 64)).status_code == 409
    assert (await apply("1.0.0", 0, approved_permissions=[])).status_code in (400, 403)
    first = await apply("1.0.0", 0)
    assert first.status_code == 200, first.text
    assert first.json()["running_version"] == "1.0.0"
    revision = first.json()["desired_revision"]
    assert (await get("catalog", view="updates")).json()["total"] == 1
    assert (await apply("1.10.0", 0)).status_code == 409
    second = await apply("1.10.0", revision)
    assert second.status_code == 200, second.text
    assert second.json()["actual_digest"] == digests["1.10.0"]
    failed = await apply("2.0.0-beta.1", second.json()["desired_revision"])
    assert failed.status_code == 409
    after = await detail()
    assert after["installation"]["failure"]
    assert after["installation"]["running_version"] == "1.10.0"
    invoked = await client.post(
        BASE + "/sample.notes/invoke",
        headers=owner,
        json={**SCOPE, "tool_name": "note.ping", "payload": {"op": "ping"}},
    )
    assert invoked.json()["op"] == "pong"
    settings["online"] = False
    fallback = (await get("catalog", view="installed")).json()
    assert (
        fallback["source_error"]
        and fallback["items"][0]["installation"]["running_version"] == "1.10.0"
    )
    cached = await detail()
    assert cached["source_error"] and cached["release"]["digest"] == digests["1.10.0"]
    assert cached["installation"]["signed_slot_targets"] == ["web"]
    assert cached["current_permissions"] == reviewed["release"]["permissions"]
    rolled = await client.post(
        BASE + "/sample.notes/rollback",
        headers=owner,
        json={**SCOPE, "expected_revision": cached["desired_revision"]},
    )
    assert rolled.status_code == 200, rolled.text
    restored = await detail()
    assert restored["installation"]["actual_digest"] == digests["1.0.0"]
    removed = await client.post(
        BASE + "/sample.notes/uninstall",
        headers=owner,
        json={**SCOPE, "expected_revision": restored["desired_revision"]},
    )
    assert removed.status_code == 200, removed.text
    assert not (await get("catalog", view="installed")).json()["items"]
    settings["online"] = True
    assert (await detail())["desired_revision"] > revision
    assert (await apply("1.0.0", 0)).status_code == 409


def test_npm_semver_precedence():
    assert version_key("1.0.0-alpha.10") > version_key("1.0.0-alpha.2")
    assert version_key("1.0.0") > version_key("1.0.0-rc.9")
    assert version_key("1.0.0+build") == version_key("1.0.0+other")


@pytest.mark.parametrize("scope", ["tenant", "project", "project_archive"])
def test_signed_release_permission_review_accepts_full_device_request(scope):
    from pydantic import ValidationError

    from src.host.transport.project_marketplace import ApplyNpmRelease
    from src.host.transport.tenant_packages import Apply
    from src.infrastructure.adapters.primary.web.routers.optional_business_http_v2 import (
        OptionalBusinessInstallV2,
    )

    model = {
        "tenant": Apply,
        "project": ApplyNpmRelease,
        "project_archive": OptionalBusinessInstallV2,
    }[scope]
    body = {"tenant_id": "tenant", "expected_revision": 0, "expected_digest": "sha256:" + "a" * 64}
    if scope != "tenant":
        body["project_id"] = "project"
    if scope == "project_archive":
        body["archive_base64"] = "YQ=="
    else:
        body.update(package_name="@memstack/environments", version="1.5.8")
    approvals = [f"permission.{i}" for i in range(35)]
    assert (
        model.model_validate({**body, "approved_permissions": approvals}).approved_permissions
        == approvals
    )
    with pytest.raises(ValidationError, match="at most 100"):
        model.model_validate(
            {**body, "approved_permissions": [f"permission.{i}" for i in range(101)]}
        )
