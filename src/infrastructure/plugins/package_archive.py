"""Safe in-memory parsing for MemStack plugin distribution archives."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from dataclasses import dataclass
from typing import Any


class PluginPackageArchiveError(ValueError):
    """Raised before untrusted package bytes can enter desired state."""


@dataclass(frozen=True)
class VerifiedPluginPackage:
    manifest: dict[str, Any]
    checksums: dict[str, str]
    runtime_files: tuple[tuple[str, bytes], ...]


MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_FILE_COUNT = 512
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_TEXT_FILE_BYTES = 2 * 1024 * 1024
REQUIRED_FILES = {
    "plugin.manifest.json",
    "checksums.json",
}
RUNTIME_ARTIFACT_PATHS: dict[str, str] = {
    "python-trusted": "runtime/plugin.json",
    "wasm": "runtime/plugin.wasm",
    "mcp": "runtime/plugin.json",
    "subprocess": "runtime/plugin.json",
    "frontend": "runtime/plugin.json",
}


def verify_plugin_package_archive(data: bytes) -> VerifiedPluginPackage:
    """Parse a bounded archive and verify every declared file checksum."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise PluginPackageArchiveError("plugin archive exceeds its size limit")
    files = _read_archive_files(data)
    missing = sorted(REQUIRED_FILES - files.keys())
    if missing:
        raise PluginPackageArchiveError(f"plugin archive is missing required files: {missing}")
    manifest = _json_object(files["plugin.manifest.json"], "plugin.manifest.json")
    checksums = _json_object(files["checksums.json"], "checksums.json")
    _verify_checksums(files, checksums)
    _verify_runtime_artifact(manifest, files)
    runtime_files = tuple(
        (name, raw) for name, raw in sorted(files.items()) if name.startswith("runtime/")
    )
    if not runtime_files:
        raise PluginPackageArchiveError("plugin archive contains no runtime artifact")
    return VerifiedPluginPackage(
        manifest=manifest,
        checksums=checksums,
        runtime_files=runtime_files,
    )


def _verify_runtime_artifact(manifest: dict[str, Any], files: dict[str, bytes]) -> None:
    runtime = manifest.get("runtime")
    expected = RUNTIME_ARTIFACT_PATHS.get(runtime) if isinstance(runtime, str) else None
    if expected is None:
        raise PluginPackageArchiveError(f"plugin runtime {runtime!r} has no artifact mapping")
    runtime_files = sorted(name for name in files if name.startswith("runtime/"))
    if runtime_files != [expected]:
        raise PluginPackageArchiveError(f"plugin runtime {runtime} requires exactly {expected}")


def _read_archive_files(data: bytes) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PluginPackageArchiveError("plugin artifact is not a valid zip archive") from exc
    entries = archive.infolist()
    if len(entries) > MAX_FILE_COUNT:
        raise PluginPackageArchiveError("plugin archive contains too many files")
    total_uncompressed = 0
    files: dict[str, bytes] = {}
    for entry in entries:
        if entry.is_dir():
            continue
        name = _safe_entry_name(entry.filename)
        _validate_entry_metadata(entry, name)
        total_uncompressed += entry.file_size
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise PluginPackageArchiveError("plugin archive expands beyond its size limit")
        if name in files:
            raise PluginPackageArchiveError(f"plugin archive contains duplicate entry {name}")
        files[name] = archive.read(entry)
    return files


def _validate_entry_metadata(entry: zipfile.ZipInfo, name: str) -> None:
    mode = entry.external_attr >> 16
    if mode & (stat.S_IFLNK | stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX):
        raise PluginPackageArchiveError(f"plugin archive entry {name} has unsafe metadata")
    if entry.file_size > MAX_TEXT_FILE_BYTES and _is_contract_file(name):
        raise PluginPackageArchiveError(f"plugin archive entry {name} is too large")


def _verify_checksums(files: dict[str, bytes], checksums: dict[str, str]) -> None:
    for name, raw in files.items():
        if name == "checksums.json":
            continue
        declared = checksums.get(name)
        if not isinstance(declared, str):
            raise PluginPackageArchiveError(f"plugin archive file {name} has no checksum")
        if declared != hashlib.sha256(raw).hexdigest():
            raise PluginPackageArchiveError(f"plugin archive file {name} failed its checksum")


def _safe_entry_name(name: str) -> str:
    if not name or name != name.strip() or "\\" in name or name.startswith("/"):
        raise PluginPackageArchiveError("plugin archive entry name is invalid")
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise PluginPackageArchiveError(f"plugin archive entry name is invalid: {name}")
    return "/".join(parts)


def _is_contract_file(name: str) -> bool:
    return name in REQUIRED_FILES


def _json_object(raw: bytes, name: str) -> dict[str, Any]:
    if len(raw) > MAX_TEXT_FILE_BYTES:
        raise PluginPackageArchiveError(f"plugin archive file {name} is too large")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PluginPackageArchiveError(f"plugin archive file {name} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise PluginPackageArchiveError(f"plugin archive file {name} must be an object")
    return value
