"""Closed, signed protocol-v2 `.mspkg` archive verification."""

from __future__ import annotations

import base64
import binascii
import io
import json
import stat
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.domain.model.plugins.artifact_attestation_v2 import artifact_digest_v2
from src.domain.model.plugins.generated_v2 import BundleManifestV2

from .protocol import PluginProtocolV2Error, parse_bundle_manifest_v2

BUNDLE_DESCRIPTOR_V2 = "bundle.json"
MAX_BUNDLE_BYTES_V2 = 64 * 1024 * 1024
MAX_BUNDLE_FILES_V2 = 512
MAX_BUNDLE_UNCOMPRESSED_BYTES_V2 = 128 * 1024 * 1024
MAX_BUNDLE_DESCRIPTOR_BYTES_V2 = 2 * 1024 * 1024


class BundleArchiveV2Error(ValueError):
    """Stable rejection for a malformed or untrusted protocol-v2 bundle."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, kw_only=True)
class VerifiedBundleArchiveV2:
    """One verified manifest and immutable artifact byte map keyed by artifact_id."""

    manifest: BundleManifestV2
    artifacts: Mapping[str, bytes]
    source: str


def read_bundle_archive_v2(
    path: Path,
    *,
    trusted_public_keys: Sequence[str] = (),
    approved_permissions: frozenset[str] = frozenset(),
    require_signature: bool = False,
    require_provenance: bool = False,
) -> VerifiedBundleArchiveV2:
    """Read and verify one v2 `.mspkg` without extracting it to the filesystem."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise BundleArchiveV2Error("bundle_read_failed", f"cannot read bundle {path}") from exc
    return parse_bundle_archive_v2(
        raw,
        source=str(path),
        trusted_public_keys=trusted_public_keys,
        approved_permissions=approved_permissions,
        require_signature=require_signature,
        require_provenance=require_provenance,
    )


def parse_bundle_archive_v2(
    raw: bytes,
    *,
    source: str,
    trusted_public_keys: Sequence[str] = (),
    approved_permissions: frozenset[str] = frozenset(),
    require_signature: bool = False,
    require_provenance: bool = False,
) -> VerifiedBundleArchiveV2:
    """Verify archive closure, protocol schema, artifacts, trust, and permissions."""
    if len(raw) > MAX_BUNDLE_BYTES_V2:
        raise BundleArchiveV2Error("bundle_too_large", f"bundle {source} exceeds size limit")
    files = _read_archive_files_v2(raw, source=source)
    manifest = _parse_bundle_descriptor_v2(files, source=source)
    artifacts = _verify_artifact_files_v2(manifest, files, source=source)

    _verify_bundle_signature_v2(
        manifest,
        source=source,
        trusted_public_keys=trusted_public_keys,
        required=require_signature,
    )
    if require_provenance and manifest.provenance is None:
        raise BundleArchiveV2Error(
            "bundle_provenance_required",
            f"bundle {source} has no verified provenance reference",
        )
    required_permissions = {
        permission for plugin in manifest.manifests for permission in plugin.permissions
    }
    missing_permissions = sorted(required_permissions - approved_permissions)
    if missing_permissions:
        raise BundleArchiveV2Error(
            "bundle_permission_not_approved",
            f"bundle {source} lacks approval for {', '.join(missing_permissions)}",
        )
    return VerifiedBundleArchiveV2(
        manifest=manifest,
        artifacts=MappingProxyType(artifacts),
        source=source,
    )


def _parse_bundle_descriptor_v2(
    files: Mapping[str, bytes],
    *,
    source: str,
) -> BundleManifestV2:
    descriptor = files.get(BUNDLE_DESCRIPTOR_V2)
    if descriptor is None:
        raise BundleArchiveV2Error(
            "bundle_descriptor_missing",
            f"bundle {source} is missing {BUNDLE_DESCRIPTOR_V2}",
        )
    if len(descriptor) > MAX_BUNDLE_DESCRIPTOR_BYTES_V2:
        raise BundleArchiveV2Error(
            "bundle_descriptor_too_large",
            f"bundle {source} descriptor exceeds size limit",
        )
    try:
        payload = json.loads(descriptor.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleArchiveV2Error(
            "bundle_descriptor_invalid",
            f"bundle {source} descriptor is not valid JSON",
        ) from exc
    try:
        return parse_bundle_manifest_v2(payload)
    except PluginProtocolV2Error as exc:
        raise BundleArchiveV2Error(exc.code, f"bundle {source}: {exc}") from exc


def _verify_artifact_files_v2(
    manifest: BundleManifestV2,
    files: Mapping[str, bytes],
    *,
    source: str,
) -> dict[str, bytes]:
    declared_paths = {artifact.path for artifact in manifest.artifacts}
    actual_paths = set(files) - {BUNDLE_DESCRIPTOR_V2}
    missing_paths = sorted(declared_paths - actual_paths)
    if missing_paths:
        raise BundleArchiveV2Error(
            "bundle_artifact_missing",
            f"bundle {source} is missing declared artifact {missing_paths[0]}",
        )
    extra_paths = sorted(actual_paths - declared_paths)
    if extra_paths:
        raise BundleArchiveV2Error(
            "undeclared_archive_entry",
            f"bundle {source} contains undeclared entry {extra_paths[0]}",
        )

    artifacts: dict[str, bytes] = {}
    for artifact in manifest.artifacts:
        content = files[artifact.path]
        if len(content) != artifact.size_bytes:
            raise BundleArchiveV2Error(
                "bundle_artifact_size_mismatch",
                f"bundle {source} artifact {artifact.artifact_id} has an unexpected size",
            )
        if artifact_digest_v2(content) != artifact.digest:
            raise BundleArchiveV2Error(
                "bundle_artifact_digest_mismatch",
                f"bundle {source} artifact {artifact.artifact_id} digest does not match",
            )
        artifacts[artifact.artifact_id] = content
    return artifacts


def _read_archive_files_v2(raw: bytes, *, source: str) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise BundleArchiveV2Error("bundle_archive_invalid", f"bundle {source} is not ZIP") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_BUNDLE_FILES_V2:
            raise BundleArchiveV2Error(
                "bundle_file_limit_exceeded",
                f"bundle {source} contains too many entries",
            )
        files: dict[str, bytes] = {}
        declared_size = 0
        for info in infos:
            name = info.filename
            _validate_archive_path_v2(name, source=source)
            if info.is_dir():
                continue
            if name in files:
                raise BundleArchiveV2Error(
                    "duplicate_archive_entry",
                    f"bundle {source} repeats archive entry {name}",
                )
            if info.flag_bits & 0x1:
                raise BundleArchiveV2Error(
                    "encrypted_archive_entry",
                    f"bundle {source} contains encrypted entry {name}",
                )
            file_type = (info.external_attr >> 16) & 0o170000
            if file_type == stat.S_IFLNK:
                raise BundleArchiveV2Error(
                    "archive_symlink_forbidden",
                    f"bundle {source} contains symlink entry {name}",
                )
            declared_size += info.file_size
            if declared_size > MAX_BUNDLE_UNCOMPRESSED_BYTES_V2:
                raise BundleArchiveV2Error(
                    "bundle_uncompressed_limit_exceeded",
                    f"bundle {source} exceeds uncompressed size limit",
                )
            try:
                content = archive.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise BundleArchiveV2Error(
                    "bundle_entry_read_failed",
                    f"bundle {source} entry {name} cannot be read",
                ) from exc
            if len(content) != info.file_size:
                raise BundleArchiveV2Error(
                    "bundle_entry_size_mismatch",
                    f"bundle {source} entry {name} has an invalid ZIP size",
                )
            files[name] = content
    return files


def _validate_archive_path_v2(name: str, *, source: str) -> None:
    raw_parts = name.split("/")
    path = PurePosixPath(name)
    invalid = (
        not name
        or "\\" in name
        or "\x00" in name
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in raw_parts)
    )
    if invalid:
        raise BundleArchiveV2Error(
            "unsafe_archive_path",
            f"bundle {source} contains unsafe entry path",
        )


def _verify_bundle_signature_v2(
    manifest: BundleManifestV2,
    *,
    source: str,
    trusted_public_keys: Sequence[str],
    required: bool,
) -> None:
    signature_text = manifest.signature
    if signature_text is None:
        if required:
            raise BundleArchiveV2Error(
                "bundle_signature_required",
                f"bundle {source} must carry a detached Ed25519 signature",
            )
        return
    if not trusted_public_keys:
        raise BundleArchiveV2Error(
            "bundle_signature_untrusted",
            f"bundle {source} has no matching trusted signing key",
        )
    try:
        signature = base64.b64decode(signature_text, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise BundleArchiveV2Error(
            "bundle_signature_invalid",
            f"bundle {source} signature is not canonical base64",
        ) from exc
    message = manifest.digest.encode("ascii")
    for public_key_pem in trusted_public_keys:
        try:
            key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
        except (TypeError, ValueError):
            continue
        if not isinstance(key, Ed25519PublicKey):
            continue
        try:
            key.verify(signature, message)
        except InvalidSignature:
            continue
        return
    raise BundleArchiveV2Error(
        "bundle_signature_invalid",
        f"bundle {source} signature verification failed",
    )


__all__ = [
    "BUNDLE_DESCRIPTOR_V2",
    "BundleArchiveV2Error",
    "VerifiedBundleArchiveV2",
    "parse_bundle_archive_v2",
    "read_bundle_archive_v2",
]
