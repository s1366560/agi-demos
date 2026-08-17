"""Minimal content-addressed OCI Distribution client for plugin packages."""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx


class PluginRegistryError(ValueError):
    """Raised when an OCI artifact does not match its immutable digest."""


@dataclass(frozen=True)
class RegistryPluginArtifact:
    registry: str
    repository: str
    manifest_digest: str
    layer_digest: str
    archive: bytes


OCI_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
MEMSTACK_ARTIFACT_TYPE = "application/vnd.memstack.plugin.v1"
MEMSTACK_LAYER_MEDIA_TYPE = "application/vnd.memstack.plugin.bundle.v1+zip"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
REPOSITORY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,254}$")
HEX_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class OciPluginArtifactClient:
    """Download and digest-verify a MemStack OCI artifact layer."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch(
        self,
        *,
        registry: str,
        repository: str,
        manifest_digest: str,
    ) -> RegistryPluginArtifact:
        normalized_registry = normalize_registry(registry)
        normalize_repository(repository)
        normalize_digest(manifest_digest)
        manifest_url = f"{normalized_registry}/v2/{repository}/manifests/sha256:{manifest_digest}"
        async with self._client.stream(
            "GET",
            manifest_url,
            headers={
                "Accept": f"{OCI_MANIFEST_MEDIA_TYPE}, {MEMSTACK_ARTIFACT_TYPE}",
            },
        ) as manifest_response:
            _raise_for_status(manifest_response, "OCI manifest")
            manifest_bytes = await _read_bounded_stream(
                manifest_response,
                MAX_MANIFEST_BYTES,
                "OCI manifest",
            )
        if hashlib.sha256(manifest_bytes).hexdigest() != manifest_digest:
            raise PluginRegistryError("OCI manifest digest mismatch")
        manifest = _json_object(manifest_bytes, "OCI manifest")
        _validate_oci_manifest(manifest)

        layer_digest = manifest["layers"][0]["digest"].removeprefix("sha256:")
        normalize_digest(layer_digest)
        blob_url = f"{normalized_registry}/v2/{repository}/blobs/sha256:{layer_digest}"
        async with self._client.stream("GET", blob_url) as blob_response:
            _raise_for_status(blob_response, "OCI plugin layer")
            archive = await _read_bounded_stream(
                blob_response,
                MAX_ARCHIVE_BYTES,
                "OCI plugin layer",
            )
        if hashlib.sha256(archive).hexdigest() != layer_digest:
            raise PluginRegistryError("OCI plugin layer digest mismatch")
        return RegistryPluginArtifact(
            registry=normalized_registry,
            repository=repository,
            manifest_digest=manifest_digest,
            layer_digest=layer_digest,
            archive=archive,
        )


def normalize_registry(value: str) -> str:
    split = urlsplit(value)
    host = split.hostname
    explicit_port = _port_specified(value)
    if (
        not host
        or split.username is not None
        or split.password is not None
        or split.query
        or split.fragment
        or split.path not in {"", "/"}
        or (split.scheme == "https" and split.port is None and explicit_port)
    ):
        raise PluginRegistryError("OCI registry URL is invalid")
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    if split.scheme not in {"https", "http"} or (split.scheme == "http" and not loopback):
        raise PluginRegistryError("OCI registry must use HTTPS outside loopback")
    return value.rstrip("/")


def _port_specified(value: str) -> bool:
    return ":" in value.rsplit("/", 2)[-1]


def normalize_repository(value: str) -> str:
    if not REPOSITORY_PATTERN.fullmatch(value) or ".." in value:
        raise PluginRegistryError("OCI repository name is invalid")
    return value


def normalize_digest(value: str) -> str:
    if not HEX_DIGEST_PATTERN.fullmatch(value):
        raise PluginRegistryError("OCI digest must be 64 lowercase hexadecimal characters")
    return value


def _validate_oci_manifest(value: dict[str, Any]) -> None:
    layers = value.get("layers")
    if (
        value.get("schemaVersion") != 2
        or value.get("mediaType") != OCI_MANIFEST_MEDIA_TYPE
        or value.get("artifactType") != MEMSTACK_ARTIFACT_TYPE
        or not isinstance(layers, list)
        or len(layers) != 1
        or layers[0].get("mediaType") != MEMSTACK_LAYER_MEDIA_TYPE
        or layers[0].get("digest", "").removeprefix("sha256:") == ""
    ):
        raise PluginRegistryError("OCI artifact is not a MemStack plugin package")
    normalize_digest(layers[0]["digest"].removeprefix("sha256:"))


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PluginRegistryError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise PluginRegistryError(f"{label} must be an object")
    return value


async def _read_bounded_stream(
    response: httpx.Response,
    limit: int,
    label: str,
) -> bytes:
    output = io.BytesIO()
    async for chunk in response.aiter_bytes(64 * 1024):
        output.write(chunk)
        if output.tell() > limit:
            raise PluginRegistryError(f"{label} exceeds its size limit")
    return output.getvalue()


def _raise_for_status(response: httpx.Response, label: str) -> None:
    if response.status_code >= 400:
        raise PluginRegistryError(f"{label} fetch returned {response.status_code}")
