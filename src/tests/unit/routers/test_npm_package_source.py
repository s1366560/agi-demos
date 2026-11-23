"""The npm registry supplies bytes. The project signer and administrator authorize them."""

import base64
import hashlib
import io
import json
import tarfile

import httpx
import pytest

from src.configuration.config import get_settings
from src.host.packages import npm_source
from src.tests.unit.routers.test_optional_business_http_v2 import http, publisher  # noqa: F401

BASE = "/api/v1/platform-plugins/v2/optional-business"
pytestmark = pytest.mark.unit


def distribution(name, version, archive):
    metadata = {"name": name, "version": version}
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        for path, raw in (
            ("package.json", json.dumps(metadata).encode()),
            ("plugin.mspkg", archive),
        ):
            file = tarfile.TarInfo("package/" + path)
            file.size = len(raw)
            tar.addfile(file, io.BytesIO(raw))
    content = output.getvalue()
    return {
        **metadata,
        "dist": {
            "tarball": "http://npm-registry:4873/sample.notes/-/sample.notes-1.0.0.tgz",
            "integrity": "sha512-" + base64.b64encode(hashlib.sha512(content).digest()).decode(),
        },
    }, content


@pytest.mark.parametrize("failure", ["", "integrity", "origin", "version", "missing"])
async def test_exact_npm_preview_verifies_distribution_and_signature(
    http, publisher, monkeypatch, failure  # noqa: F811
):
    client, keys = http
    body, digest = publisher[1]()
    name = "sample.notes"
    meta, content = distribution(name, "1.0.0", base64.b64decode(body["archive_base64"]))
    if failure == "integrity":
        meta["dist"]["integrity"] = "sha512-incorrect"
    elif failure == "origin":
        meta["dist"]["tarball"] = "http://other.example/sample.tgz"
    elif failure == "version":
        meta["version"] = "2.0.0"
    requests = []

    def respond(request):
        requests.append(request.url)
        if failure == "missing":
            return httpx.Response(404)
        if request.url.path.endswith(".tgz"):
            return httpx.Response(200, content=content)
        return httpx.Response(200, json=meta)

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original_client(transport=httpx.MockTransport(respond), **kw),
    )
    monkeypatch.setattr(get_settings(), "package_npm_registry_url", "http://npm-registry:4873")
    args = {"tenant_id": "t", "project_id": "p", "package_name": name, "version": "1.0.0"}
    viewer = {"Authorization": "Bearer " + keys["viewer"]}
    owner = {"Authorization": "Bearer " + keys["owner"]}
    assert (await client.post(BASE + "/npm/resolve", json=args, headers=viewer)).status_code == 403
    assert not requests
    response = await client.post(BASE + "/npm/resolve", json=args, headers=owner)
    assert len(requests) == (2 if failure in {"", "integrity"} else 1)
    if failure:
        assert response.status_code == (404 if failure == "missing" else 400)
    else:
        assert response.status_code == 200
        assert response.json()["digest"] == digest
        assert response.json()["archive_base64"] == body["archive_base64"]
        listing = await client.get(
            BASE + "/", params={"tenant_id": "t", "project_id": "p"}, headers=owner
        )
        assert listing.json()["items"] == []


@pytest.mark.parametrize(
    "name, version", [("sample", "latest"), ("../sample", "1.0.0"), ("@memstack/agent", "^1.0.0")]
)
def test_source_requires_package_and_exact_version(name, version):
    with pytest.raises(ValueError, match="exact version"):
        npm_source.npm_plugin_id(name, version)
