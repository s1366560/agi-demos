"""Bounded, immutable marketplace source snapshots; never execute downloaded code."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import http.client
import io
import ipaddress
import json
import os
import shutil
import socket
import ssl
import stat
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from src.infrastructure.plugins.codex_package import (
    MAX_FILES,
    MAX_PACKAGE_BYTES,
    CodexPackageError,
    package_digest,
    package_path,
)


def _public_address(location: str) -> tuple[str, int, str, str]:
    parsed = urlsplit(location)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise CodexPackageError(
            "Remote sources require an HTTPS URL without credentials or fragment"
        )
    port = parsed.port or 443
    addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise CodexPackageError("Remote source addresses must be public")
    request_path = parsed.path or "/"
    if parsed.query:
        request_path += "?" + parsed.query
    address = addresses[0][4][0]
    if not isinstance(address, str):
        raise CodexPackageError("Remote source address must be an IP string")
    return parsed.hostname, port, address, request_path


def _download(location: str) -> bytes:
    """Pin the validated IP while verifying TLS against the original hostname."""
    host, port, address, request_path = _public_address(location)
    connection = http.client.HTTPSConnection(host, port, timeout=30)
    try:
        raw = socket.create_connection((address, port), timeout=30)
        try:
            connection.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        except BaseException:
            raw.close()
            raise
        connection.request(
            "GET", request_path, headers={"Accept": "application/json, application/zip"}
        )
        response = connection.getresponse()
        if response.status != 200:
            raise CodexPackageError(
                f"Source returned HTTP {response.status}; redirects are not followed"
            )
        data = response.read(MAX_PACKAGE_BYTES + 1)
        if len(data) > MAX_PACKAGE_BYTES:
            raise CodexPackageError("Remote source exceeds download limit")
        return data
    finally:
        connection.close()


def _extract_zip(data: bytes, destination: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_FILES or sum(item.file_size for item in entries) > MAX_PACKAGE_BYTES:
            raise CodexPackageError("Archive exceeds extraction limits")
        seen: set[str] = set()
        for item in entries:
            target = package_path(destination, item.filename)
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode) or (
                stat.S_IFMT(mode) and not (stat.S_ISDIR(mode) or stat.S_ISREG(mode))
            ):
                raise CodexPackageError("Archive contains a link or special file")
            identity = target.relative_to(destination).as_posix().casefold()
            if identity in seen:
                raise CodexPackageError("Archive contains duplicate paths")
            seen.add(identity)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o700 if mode & 0o111 else 0o600)


def _remote_snapshot(location: str, destination: Path) -> None:
    data = _download(location)
    if zipfile.is_zipfile(io.BytesIO(data)):
        _extract_zip(data, destination)
        return
    try:
        catalog = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise CodexPackageError("Source must be a ZIP archive or JSON catalog") from exc
    entries = catalog.get("plugins") if isinstance(catalog, dict) else None
    if not isinstance(entries, list) or len(entries) > 100:
        raise CodexPackageError("Catalog requires at most 100 plugin entries")
    local_entries = []
    total = len(data)
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise CodexPackageError("Invalid remote catalog entry")
        source = entry.get("source", {})
        if not isinstance(source, dict):
            raise CodexPackageError("Remote catalog source must be an object")
        url = source.get("url", entry.get("archive_url"))
        if not isinstance(url, str):
            raise CodexPackageError("Remote catalog entries require source.url")
        package_bytes = _download(url)
        expected = entry.get("sha256")
        if expected is not None and (
            not isinstance(expected, str)
            or hashlib.sha256(package_bytes).hexdigest() != expected.lower()
        ):
            raise CodexPackageError("Catalog archive digest mismatch")
        total += len(package_bytes)
        if total > MAX_PACKAGE_BYTES:
            raise CodexPackageError("Catalog exceeds aggregate download limit")
        relative = f"plugins/{index}"
        package_root = destination / relative
        package_root.mkdir(parents=True)
        _extract_zip(package_bytes, package_root)
        local_entries.append({"path": relative})
    (destination / "catalog.json").write_text(json.dumps({"plugins": local_entries}))


def list_source_packages(root: Path) -> list[Path]:
    """Resolve direct packages and explicitly declared, root-relative catalog entries."""
    if (root / ".codex-plugin/plugin.json").is_file():
        return [root]
    catalog = next(
        (
            root / p
            for p in ("catalog.json", "marketplace.json", ".agents/plugins/marketplace.json")
            if (root / p).is_file()
        ),
        None,
    )
    if catalog is None:
        raise CodexPackageError("Source has no plugin manifest or marketplace catalog")
    package_path(root, catalog.relative_to(root).as_posix())
    try:
        payload = json.loads(catalog.read_text())
        entries = payload.get("plugins") if isinstance(payload, dict) else None
    except (ValueError, UnicodeError) as exc:
        raise CodexPackageError("Invalid marketplace catalog") from exc
    if not isinstance(entries, list) or len(entries) > 100:
        raise CodexPackageError("Catalog requires at most 100 plugin entries")
    result: list[Path] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise CodexPackageError("Invalid catalog entry")
        source = entry.get("source", {})
        if not isinstance(source, dict):
            raise CodexPackageError("Catalog source must be an object")
        relative = entry.get("path", source.get("path"))
        if not isinstance(relative, str):
            raise CodexPackageError("Snapshot catalog requires relative plugin paths")
        path = package_path(root, relative)
        if path in result:
            raise CodexPackageError("Duplicate plugin path")
        if not (path / ".codex-plugin/plugin.json").is_file():
            raise CodexPackageError("Catalog plugin manifest is missing")
        result.append(path)
    return result


async def _git_snapshot(location: str, destination: Path, revision: str | None) -> None:
    host, port, address, _ = await asyncio.to_thread(_public_address, location)
    if revision and (
        len(revision) != 40 or any(c not in "0123456789abcdefABCDEF" for c in revision)
    ):
        raise CodexPackageError("Git revisions must be complete commit hashes")
    # Do not inherit caller-injected Git configuration, credentials or proxy settings.
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
        and key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}
    }
    environment.update(
        {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}
    )
    options = [
        "git",
        "-c",
        "core.hooksPath=" + os.devnull,
        "-c",
        "http.followRedirects=false",
        "-c",
        "http.proxy=",
        "-c",
        f"http.curloptResolve={host}:{port}:{address}",
        "-c",
        "protocol.file.allow=never",
        "-c",
        "protocol.ext.allow=never",
    ]

    async def run(*args: str) -> bytes:
        process = await asyncio.create_subprocess_exec(
            *options,
            *args,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        async def bounded_output() -> bytes:
            assert process.stdout is not None
            output = bytearray()
            while chunk := await process.stdout.read(65536):
                output.extend(chunk)
                if len(output) > MAX_PACKAGE_BYTES:
                    raise CodexPackageError("Git output exceeds download limit")
            await process.wait()
            return bytes(output)

        try:
            output = await asyncio.wait_for(bounded_output(), timeout=60)
        except BaseException:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise CodexPackageError("Git source fetch failed")
        return output

    await run("init", "--quiet", str(destination))
    await run(
        "-C",
        str(destination),
        "fetch",
        "--depth=1",
        "--no-tags",
        "--",
        location,
        revision or "HEAD",
    )
    resolved = (await run("-C", str(destination), "rev-parse", "FETCH_HEAD")).decode().strip()
    archive = await run("-C", str(destination), "archive", "--format=zip", resolved)
    if len(archive) > MAX_PACKAGE_BYTES:
        raise CodexPackageError("Git archive exceeds download limit")
    # This .git directory was created in our private staging directory above.
    shutil.rmtree(destination / ".git")
    _extract_zip(archive, destination)
    (destination / ".marketplace-revision").write_text(resolved)


async def snapshot_source(
    kind: str, location: str, destination: Path, revision: str | None = None
) -> Path:
    """Fetch into owned staging and publish only a completely validated snapshot.

    Cloud HTTP callers must reject local sources; local paths are for trusted deployment
    configuration and desktop-only import. Existing destinations are never overwritten.
    """
    if destination.exists():
        raise CodexPackageError("Snapshot destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="marketplace-", dir=destination.parent))
    try:
        if kind == "local":
            source = Path(location)
            await asyncio.to_thread(package_digest, source)
            await asyncio.to_thread(
                shutil.copytree,
                source,
                staging,
                dirs_exist_ok=True,
                symlinks=True,
                ignore=shutil.ignore_patterns(".git"),
            )
        elif kind == "https":
            await asyncio.to_thread(_remote_snapshot, location, staging)
        elif kind == "git":
            await _git_snapshot(location, staging, revision)
        else:
            raise CodexPackageError("Unknown marketplace source kind")
        await asyncio.to_thread(package_digest, staging)
        await asyncio.to_thread(list_source_packages, staging)
        staging.rename(destination)
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging)
