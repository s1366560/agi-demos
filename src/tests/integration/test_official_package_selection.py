"""Install the six business packages together and withdraw one optional model adapter."""

import base64
import hashlib
import json
import os
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from memstack_plugin_sdk.pack import build

from scripts.build_standard_packages import WORKER_CONTEXTS
from src.configuration.config import get_settings
from src.tests.integration.test_oci_mcp_worker_docker import disposable_worker_registry
from src.tests.unit.routers.test_optional_business_http_v2 import http, publisher  # noqa: F401

ROOT = Path(__file__).resolve().parents[3] / "plugins"
BUSINESS = ROOT / "business"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("OCI_WORKER_DOCKER_TESTS") != "1", reason="requires Docker"),
]


@pytest.fixture(scope="module")
def deployment(tmp_path_factory):
    stage = tmp_path_factory.mktemp("official-packages")
    device = BUSINESS / "knowledge/workers/device_search"
    subprocess.run(
        [
            "cargo",
            "build",
            "--locked",
            "--release",
            "--target",
            "wasm32-unknown-unknown",
            "--target-dir",
            str(stage),
            "--manifest-path",
            str(device / "Cargo.toml"),
        ],
        check=True,
    )
    wasm = stage / "wasm32-unknown-unknown/release/memstack_device_knowledge.wasm"
    key = Ed25519PrivateKey.generate()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    with disposable_worker_registry() as (publish, registry, _):
        key_file = stage / "publisher.key"
        key_file.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        target = stage / "archives"
        images = []
        for name, context in WORKER_CONTEXTS.items():
            images.extend(["--" + name + "-image", publish(BUSINESS / context)])
        subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.build_standard_packages",
                "--device-wasm",
                str(wasm),
                "--out",
                str(target),
                "--key",
                str(key_file),
                *images,
            ],
            cwd=ROOT.parent,
            env={**os.environ, "PYTHONPATH": str(ROOT.parent / "sdk/memstack-plugin-sdk/src")},
            check=True,
        )
        archives = [archive.read_bytes() for archive in sorted(target.glob("*.mspkg"))]
        archives.extend(
            build(path, key) for path in sorted((ROOT / "adapters").glob("*/*/package.json"))
        )
        yield registry, public, archives


async def test_packages_coexist_after_model_adapter_withdrawal(http, deployment, monkeypatch):  # noqa: F811
    registry, public, archives = deployment
    client, credentials = http
    client._transport.app.state.plugin_marketplace_trusted_public_keys_v2 = (public,)
    monkeypatch.setattr(get_settings(), "plugin_worker_allowed_registries", (registry,))
    base = "/api/v1/platform-plugins/v2/optional-business"
    scope = {"tenant_id": "t", "project_id": "p"}
    headers = {"Authorization": f"Bearer {credentials['owner']}"}

    async def post(path, **fields):
        response = await client.post(base + path, headers=headers, json={**scope, **fields})
        response.raise_for_status()
        return response.json()

    installed = {"business": set(), "adapter": set()}
    for raw in archives:
        content = base64.b64encode(raw).decode()
        info = await post("/inspect", archive_base64=content)
        await post("/install", archive_base64=content, approved_permissions=info["permissions"])
        path = "/" + info["plugin_id"]
        await post(path + "/enable")
        state = await client.get(base + path, headers=headers, params=scope)
        state.raise_for_status()
        assert state.json()["actual_digest"] == info["digest"]
        if info["kind"] == "business":
            rich_pages = state.json()["pages"]
            assert rich_pages
            with ZipFile(BytesIO(raw)) as archive:
                declared = json.loads(archive.read("contributions.json"))["pages"]
            expected = {
                (page["id"], target): page["entry"]["digest"]
                for page in declared
                for target in page["targets"]
                if page.get("scope", "project") == "project"
            }
            served = {}
            for target in ("web", "desktop-renderer"):
                page = await client.get(
                    base + path + "/ui",
                    headers=headers,
                    params={**scope, "expected_digest": info["digest"], "target": target},
                )
                page.raise_for_status()
                document = json.loads(base64.b64decode(page.json()["bytes_base64"]))
                assert document["actions"][0]["id"] in state.json()["commands"]
                for descriptor in rich_pages:
                    if target not in descriptor["targets"]:
                        continue
                    rich = await client.get(
                        base + path + "/ui",
                        headers=headers,
                        params={
                            **scope,
                            "expected_digest": info["digest"],
                            "target": target,
                            "page_id": descriptor["id"],
                        },
                    )
                    rich.raise_for_status()
                    entry = rich.json()["entry"]
                    digest = (
                        "sha256:"
                        + hashlib.sha256(base64.b64decode(entry["bytes_base64"])).hexdigest()
                    )
                    assert entry["digest"] == digest
                    assert rich.json()["release_digest"] == info["digest"]
                    served[descriptor["id"], target] = digest
            assert served == expected
        installed[info["kind"]].add(info["plugin_id"])

    assert len(installed["business"]) == 6
    assert len(installed["adapter"]) == 4
    await post("/memstack-openai-chat/disable")
    view = await client.get(base + "/memstack-deepseek-chat", params=scope, headers=headers)
    view.raise_for_status()
    assert view.json()["actual_digest"]
    result = await post(
        "/memstack-environments/commands",
        command_id="cluster-health",
        payload={"total_nodes": 2, "used_cpu": 1, "total_cpu": 4},
    )
    assert result["cpu_usage"] == 25
