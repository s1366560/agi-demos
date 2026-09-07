import hashlib
import json

import httpx
import pytest

from src.infrastructure.plugins.package_registry import (
    OciPluginArtifactClient,
    PluginRegistryError,
)


@pytest.mark.unit
async def test_oci_client_downloads_and_verifies_content_addressed_artifact():
    layer = b"closed-protocol-v2-bundle"
    layer_digest = hashlib.sha256(layer).hexdigest()
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": "application/vnd.memstack.plugin.v2",
        "config": {
            "mediaType": "application/vnd.oci.empty.v1+json",
            "digest": f"sha256:{'0' * 64}",
            "size": 2,
        },
        "layers": [
            {
                "mediaType": "application/vnd.memstack.plugin.bundle.v2+zip",
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
    assert artifact.layer_digest == layer_digest
    assert artifact.archive == layer


@pytest.mark.unit
async def test_oci_client_rejects_registry_metadata_and_digest_mismatches():
    layer = b"closed-protocol-v2-bundle"
    layer_digest = hashlib.sha256(layer).hexdigest()
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": "application/vnd.memstack.plugin.v2",
        "layers": [
            {
                "mediaType": "application/vnd.memstack.plugin.bundle.v2+zip",
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
async def test_oci_client_rejects_protocol_v1_media_types_as_incompatible():
    layer = b"retired-v1-bundle"
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
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=manifest_bytes)

    client = OciPluginArtifactClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(PluginRegistryError, match="plugin_protocol_v1_incompatible"):
        await client.fetch(
            registry="https://registry.memstack.test",
            repository="memstack/plugin",
            manifest_digest=manifest_digest,
        )
