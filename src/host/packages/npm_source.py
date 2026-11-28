"""Fetch the signed MemStack payload of an exact release from the configured npm source."""

from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import io
import json
import re
import tarfile
import zlib
from urllib.parse import quote, unquote, urlsplit

import httpx

from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

_NAME_PART = r"[a-z0-9][a-z0-9._-]*"
_PACKAGE = re.compile(rf"(?:@{_NAME_PART}/)?{_NAME_PART}")
_NUMBER = r"(?:0|[1-9][0-9]*)"
_PRE = rf"(?:{_NUMBER}|[0-9]*[a-zA-Z-][a-zA-Z0-9-]*)"
_VERSION = re.compile(
    rf"{_NUMBER}\.{_NUMBER}\.{_NUMBER}(?:-{_PRE}(?:\.{_PRE})*)?(?:\+[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*)?"
)
_ARCHIVE_LIMIT = 12 * 1024 * 1024
_TAR_LIMIT = _ARCHIVE_LIMIT + 1024 * 1024


def npm_plugin_id(name: str, version: str) -> str:
    if (
        len(name) > 214
        or len(version) > 128
        or not _PACKAGE.fullmatch(name)
        or not _VERSION.fullmatch(version)
    ):
        raise ValueError("An npm package name and exact version are required")
    return name.removeprefix("@").replace("/", "-")


def _metadata(raw: bytes, name: str, version: str) -> dict[str, object]:
    doc = json.loads(raw)
    if not isinstance(doc, dict) or doc.get("name") != name or doc.get("version") != version:
        raise ValueError("npm release identity differs from the requested package")
    return doc


def _unpack(raw: bytes, name: str, version: str) -> bytes:
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
        tar = compressed.read(_TAR_LIMIT + 1)
    if len(tar) > _TAR_LIMIT:
        raise ValueError("npm tarball exceeds the unpacked size limit")
    files: dict[str, bytes] = {}
    limits = {"package/package.json": 128 * 1024, "package/plugin.mspkg": _ARCHIVE_LIMIT}
    with tarfile.open(fileobj=io.BytesIO(tar), mode="r:") as archive:
        for index, member in enumerate(archive):
            if index >= 256:
                raise ValueError("npm tarball contains too many entries")
            if member.name not in limits:
                continue
            if (
                not member.isreg()
                or member.name in files
                or not 0 < member.size <= limits[member.name]
            ):
                raise ValueError("Invalid npm package payload")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("Missing npm package payload")
            with stream:
                files[member.name] = stream.read(member.size)
    if files.keys() != limits.keys():
        raise ValueError("npm release must contain package.json and plugin.mspkg")
    _metadata(files["package/package.json"], name, version)
    return files["package/plugin.mspkg"]


async def download_bounded(client: httpx.AsyncClient, url: str, limit: int) -> bytes:
    async with client.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response:
        if response.status_code == 404:
            raise OptionalBusinessError("npm_not_found", "npm release was not found")
        response.raise_for_status()
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise ValueError("Unsupported npm response encoding")
        out = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=65536):
            if len(out) + len(chunk) > limit:
                raise ValueError("npm download exceeds the size limit")
            out.extend(chunk)
    return bytes(out)


def registry_base(registry: str | None) -> str:
    if not registry:
        raise OptionalBusinessError("runtime_unavailable", "No npm plugin source is configured")
    try:
        root = urlsplit(registry)
        _ = root.port
    except ValueError as exc:
        raise OptionalBusinessError("runtime_unavailable", "Invalid npm plugin source") from exc
    if (
        root.scheme not in {"https", "http"}
        or not root.hostname
        or root.username is not None
        or root.password is not None
        or root.query
        or root.fragment
    ):
        raise OptionalBusinessError("runtime_unavailable", "Invalid npm plugin source")
    return registry.rstrip("/")


async def fetch_npm_archive(registry: str | None, name: str, version: str) -> bytes:
    npm_plugin_id(name, version)
    registry = registry_base(registry)
    root = urlsplit(registry)
    endpoint = f"{registry.rstrip('/')}/{quote(name, safe='@')}/{quote(version, safe='')}"
    try:
        async with (
            asyncio.timeout(35),
            httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=10) as client,
        ):
            doc = _metadata(await download_bounded(client, endpoint, 1024 * 1024), name, version)
            dist = doc.get("dist")
            if not isinstance(dist, dict) or not isinstance(url := dist.get("tarball"), str):
                raise ValueError("Missing npm distribution")
            tar = urlsplit(url)
            parts = unquote(tar.path).split("/")
            if (
                tar.scheme != root.scheme
                or tar.netloc != root.netloc
                or tar.query
                or tar.fragment
                or ".." in parts
                or "-" not in parts
                or "\\" in unquote(tar.path)
                or not tar.path.startswith(root.path.rstrip("/") + "/")
            ):
                raise ValueError("npm tarball is outside the configured source")
            raw = await download_bounded(client, url, _TAR_LIMIT)
            integrity = "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()
            if dist.get("integrity") != integrity:
                raise ValueError("npm tarball integrity mismatch")
        return await asyncio.to_thread(_unpack, raw, name, version)
    except (httpx.HTTPError, TimeoutError) as exc:
        raise OptionalBusinessError(
            "runtime_unavailable", "npm plugin source is unavailable"
        ) from exc
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise ValueError("Invalid npm tarball") from exc
