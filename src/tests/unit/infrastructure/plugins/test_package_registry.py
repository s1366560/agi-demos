import hashlib
import io
import json
import zipfile

import httpx
import pytest

from src.infrastructure.plugins.package_archive import (
    PluginPackageArchiveError,
    verify_plugin_package_archive,
)
from src.infrastructure.plugins.package_registry import (
    OciPluginArtifactClient,
    PluginRegistryError,
)


def checksum(name: str, data: bytes) -> dict[str, str]:
    return {name: hashlib.sha256(data).hexdigest()}


def archive(runtime: bytes = b"wasm-runtime") -> bytes:
    manifest = json.dumps(
        {
            "schemaVersion": 1,
            "id": "third-party-tool",
            "version": "1.0.0",
            "runtime": "wasm",
            "trust": "signed",
            "provides": [{"kind": "tool", "id": "demo", "permissions": ["tools.execute"]}],
        },
        separators=(",", ":"),
    ).encode()
    checksums = {
        **checksum("plugin.manifest.json", manifest),
        **checksum("runtime/plugin.wasm", runtime),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("plugin.manifest.json", manifest)
        bundle.writestr("runtime/plugin.wasm", runtime)
        bundle.writestr("checksums.json", json.dumps(checksums, separators=(",", ":")))
    return output.getvalue()


@pytest.mark.unit
async def test_oci_client_downloads_and_verifies_content_addressed_artifact():
    layer = archive()
    layer_digest = hashlib.sha256(layer).hexdigest()
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": "application/vnd.memstack.plugin.v1",
        "config": {
            "mediaType": "application/vnd.oci.empty.v1+json",
            "digest": f"sha256:{'0' * 64}",
            "size": 2,
        },
        "layers": [
            {
                "mediaType": "application/vnd.memstack.plugin.bundle.v1+zip",
                "digest": f"sha256:{layer_digest}",
                "size": len(layer),
            }
        ],
    }
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode()
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/manifests/sha256:{manifest_digest}"):
            return httpx.Response(200, content=manifest_bytes)
        if request.url.path.endswith(f"/blobs/sha256:{layer_digest}"):
            return httpx.Response(200, content=layer)
        return httpx.Response(404)

    client = OciPluginArtifactClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    artifact = await client.fetch(
        registry="http://127.0.0.1:5000",
        repository="memstack/plugins/third-party-tool",
        manifest_digest=manifest_digest,
    )
    package = verify_plugin_package_archive(artifact.archive)

    assert artifact.layer_digest == layer_digest
    assert package.manifest["id"] == "third-party-tool"
    assert package.runtime_files == (("runtime/plugin.wasm", b"wasm-runtime"),)


@pytest.mark.unit
async def test_oci_client_rejects_registry_metadata_and_digest_mismatches():
    layer = archive()
    layer_digest = hashlib.sha256(layer).hexdigest()
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": "application/vnd.memstack.plugin.v1",
        "layers": [
            {
                "mediaType": "application/vnd.memstack.plugin.bundle.v1+zip",
                "digest": f"sha256:{layer_digest}",
            }
        ],
    }
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode()

    async def handler(request: httpx.Request) -> httpx.Response:
        if "manifests" in request.url.path:
            return httpx.Response(200, content=manifest_bytes + b"tampered")
        return httpx.Response(200, content=layer)

    client = OciPluginArtifactClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(PluginRegistryError, match="manifest digest mismatch"):
        await client.fetch(
            registry="https://registry.memstack.test",
            repository="memstack/plugin",
            manifest_digest="0" * 64,
        )
    with pytest.raises(PluginRegistryError, match="must use HTTPS"):
        await client.fetch(
            registry="http://registry.memstack.test",
            repository="memstack/plugin",
            manifest_digest="0" * 64,
        )


@pytest.mark.unit
def test_package_archive_rejects_path_escape_duplicates_and_bad_checksums():
    good = archive()
    parsed = verify_plugin_package_archive(good)
    assert parsed.manifest["runtime"] == "wasm"

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(zipfile.ZipInfo("../evil.txt"), b"evil")
    with pytest.raises(PluginPackageArchiveError, match="entry name is invalid"):
        verify_plugin_package_archive(output.getvalue())
