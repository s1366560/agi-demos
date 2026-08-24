"""Strict recovery-evidence contract for destructive protocol-v1 retirement."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import NoReturn, cast

from src.infrastructure.adapters.secondary.persistence.platform_plugin_v1_migration_repository import (
    digest_payload_v1_to_v2,
)

_SCHEMA_VERSION = 1
_KIND = "plugin_protocol_v1_retirement_preflight"
_MIGRATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SNAPSHOT_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_CONTRACTS = {
    "database_backup": (
        "database.backup",
        "application/vnd.postgresql.custom",
    ),
    "v1_export": ("plugin-v1-export.json", "application/json"),
    "last_ready_v2_snapshot": (
        "last-ready-v2-snapshot.json",
        "application/json",
    ),
}


class PluginProtocolV1RetirementPreflightError(ValueError):
    """Stable validation failure for recovery evidence required before V1 retirement."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, kw_only=True)
class RetirementPreflightArtifact:
    """One immutable, private recovery artifact stored beside the manifest."""

    path: str
    digest: str
    size_bytes: int
    media_type: str

    def to_payload(self) -> dict[str, object]:
        return {
            "path": self.path,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
        }


@dataclass(frozen=True, kw_only=True)
class PluginProtocolV1RetirementPreflightManifest:
    """Content-addressed manifest binding backup evidence to one migration source."""

    migration_id: str
    created_at: datetime
    v1_source_digest: str
    globally_ready_publication_nonce: str
    globally_ready_requested_version: int
    globally_ready_snapshot_digest: str
    database_backup: RetirementPreflightArtifact
    v1_export: RetirementPreflightArtifact
    last_ready_v2_snapshot: RetirementPreflightArtifact
    manifest_digest: str

    def to_payload(self) -> dict[str, object]:
        return {
            **self.unsigned_payload(),
            "manifest_digest": self.manifest_digest,
        }

    def unsigned_payload(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "kind": _KIND,
            "migration_id": self.migration_id,
            "created_at": _format_timestamp(self.created_at),
            "v1_source_digest": self.v1_source_digest,
            "globally_ready": {
                "publication_nonce": self.globally_ready_publication_nonce,
                "requested_version": self.globally_ready_requested_version,
                "snapshot_digest": self.globally_ready_snapshot_digest,
            },
            "artifacts": {
                "database_backup": self.database_backup.to_payload(),
                "v1_export": self.v1_export.to_payload(),
                "last_ready_v2_snapshot": self.last_ready_v2_snapshot.to_payload(),
            },
        }


def build_plugin_v1_retirement_preflight_manifest(
    *,
    migration_id: str,
    created_at: datetime,
    v1_source_digest: str,
    globally_ready_publication_nonce: str,
    globally_ready_requested_version: int,
    globally_ready_snapshot_digest: str,
    database_backup: RetirementPreflightArtifact,
    v1_export: RetirementPreflightArtifact,
    last_ready_v2_snapshot: RetirementPreflightArtifact,
) -> PluginProtocolV1RetirementPreflightManifest:
    """Build only after validating every binding and fixed artifact contract."""
    manifest = PluginProtocolV1RetirementPreflightManifest(
        migration_id=_migration_id(migration_id),
        created_at=_timestamp(created_at),
        v1_source_digest=_digest(v1_source_digest, context="V1 source digest"),
        globally_ready_publication_nonce=_nonce(globally_ready_publication_nonce),
        globally_ready_requested_version=_positive_integer(
            globally_ready_requested_version,
            context="globally-ready requested_version",
        ),
        globally_ready_snapshot_digest=_snapshot_digest(globally_ready_snapshot_digest),
        database_backup=_validate_artifact("database_backup", database_backup),
        v1_export=_validate_artifact("v1_export", v1_export),
        last_ready_v2_snapshot=_validate_artifact(
            "last_ready_v2_snapshot",
            last_ready_v2_snapshot,
        ),
        manifest_digest="",
    )
    return replace(
        manifest,
        manifest_digest=digest_payload_v1_to_v2(manifest.unsigned_payload()),
    )


def parse_plugin_v1_retirement_preflight_manifest(
    payload: object,
) -> PluginProtocolV1RetirementPreflightManifest:
    """Parse an exact manifest and reject stale, tampered, or unsafe evidence."""
    raw = _object(payload, code="migration_preflight_manifest_invalid", context="manifest")
    if set(raw) != {
        "schema_version",
        "kind",
        "migration_id",
        "created_at",
        "v1_source_digest",
        "globally_ready",
        "artifacts",
        "manifest_digest",
    }:
        _fail("migration_preflight_manifest_invalid", "preflight manifest fields are not exact")
    if raw["schema_version"] != _SCHEMA_VERSION or raw["kind"] != _KIND:
        _fail(
            "migration_preflight_schema_incompatible",
            "preflight manifest schema or kind is unsupported",
        )
    globally_ready = _object(
        raw["globally_ready"],
        code="migration_preflight_manifest_invalid",
        context="globally_ready",
    )
    if set(globally_ready) != {"publication_nonce", "requested_version", "snapshot_digest"}:
        _fail(
            "migration_preflight_manifest_invalid",
            "globally_ready fields are not exact",
        )
    artifacts = _object(
        raw["artifacts"],
        code="migration_preflight_artifact_invalid",
        context="artifacts",
    )
    if set(artifacts) != set(_ARTIFACT_CONTRACTS):
        _fail(
            "migration_preflight_artifact_invalid",
            "preflight artifacts are not exact",
        )
    parsed_artifacts = {
        name: _parse_artifact(name, artifacts[name]) for name in _ARTIFACT_CONTRACTS
    }
    manifest = PluginProtocolV1RetirementPreflightManifest(
        migration_id=_migration_id(raw["migration_id"]),
        created_at=_parse_timestamp(raw["created_at"]),
        v1_source_digest=_digest(raw["v1_source_digest"], context="V1 source digest"),
        globally_ready_publication_nonce=_nonce(globally_ready["publication_nonce"]),
        globally_ready_requested_version=_positive_integer(
            globally_ready["requested_version"],
            context="globally-ready requested_version",
        ),
        globally_ready_snapshot_digest=_snapshot_digest(globally_ready["snapshot_digest"]),
        database_backup=parsed_artifacts["database_backup"],
        v1_export=parsed_artifacts["v1_export"],
        last_ready_v2_snapshot=parsed_artifacts["last_ready_v2_snapshot"],
        manifest_digest=_digest(raw["manifest_digest"], context="manifest digest"),
    )
    expected = digest_payload_v1_to_v2(manifest.unsigned_payload())
    if manifest.manifest_digest != expected:
        _fail(
            "migration_preflight_manifest_digest_invalid",
            "preflight manifest digest does not match its canonical content",
        )
    return manifest


def _parse_artifact(name: str, payload: object) -> RetirementPreflightArtifact:
    raw = _object(
        payload,
        code="migration_preflight_artifact_invalid",
        context=f"artifact {name}",
    )
    if set(raw) != {"path", "digest", "size_bytes", "media_type"}:
        _fail(
            "migration_preflight_artifact_invalid",
            f"artifact {name} fields are not exact",
        )
    artifact = RetirementPreflightArtifact(
        path=_string(raw["path"], context=f"artifact {name} path", maximum=255),
        digest=_digest(raw["digest"], context=f"artifact {name} digest"),
        size_bytes=_positive_integer(raw["size_bytes"], context=f"artifact {name} size"),
        media_type=_string(
            raw["media_type"],
            context=f"artifact {name} media_type",
            maximum=255,
        ),
    )
    return _validate_artifact(name, artifact)


def _validate_artifact(
    name: str,
    artifact: RetirementPreflightArtifact,
) -> RetirementPreflightArtifact:
    expected_path, expected_media_type = _ARTIFACT_CONTRACTS[name]
    if artifact.path != expected_path or artifact.media_type != expected_media_type:
        _fail(
            "migration_preflight_artifact_invalid",
            f"artifact {name} path or media_type is not canonical",
        )
    _ = _digest(artifact.digest, context=f"artifact {name} digest")
    _ = _positive_integer(artifact.size_bytes, context=f"artifact {name} size")
    return artifact


def _migration_id(value: object) -> str:
    migration_id = _string(value, context="migration_id", maximum=128)
    if _MIGRATION_ID_PATTERN.fullmatch(migration_id) is None:
        _fail("migration_preflight_manifest_invalid", "migration_id is invalid")
    return migration_id


def _nonce(value: object) -> str:
    return _string(value, context="globally-ready publication nonce", maximum=128)


def _digest(value: object, *, context: str) -> str:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        _fail("migration_preflight_manifest_invalid", f"{context} is not a canonical digest")
    return value


def _snapshot_digest(value: object) -> str:
    if not isinstance(value, str) or _SNAPSHOT_DIGEST_PATTERN.fullmatch(value) is None:
        _fail(
            "migration_preflight_manifest_invalid",
            "globally-ready snapshot_digest is not canonical",
        )
    return value


def _positive_integer(value: object, *, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _fail("migration_preflight_manifest_invalid", f"{context} must be positive")
    return value


def _string(value: object, *, context: str, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        _fail("migration_preflight_manifest_invalid", f"{context} has an invalid length")
    return value


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        _fail("migration_preflight_manifest_invalid", "created_at must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PluginProtocolV1RetirementPreflightError(
            "migration_preflight_manifest_invalid",
            "created_at must be a UTC timestamp",
        ) from exc
    parsed = _timestamp(parsed)
    if value != _format_timestamp(parsed):
        _fail("migration_preflight_manifest_invalid", "created_at is not canonical UTC")
    return parsed


def _timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        _fail("migration_preflight_manifest_invalid", "created_at must include a timezone")
    return value.astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _object(payload: object, *, code: str, context: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        _fail(code, f"{context} must be an object")
    raw = cast(dict[object, object], payload)
    if not all(isinstance(key, str) for key in raw):
        _fail(code, f"{context} contains a non-string field name")
    return cast(dict[str, object], raw)


def _fail(code: str, message: str) -> NoReturn:
    raise PluginProtocolV1RetirementPreflightError(code, message)


__all__ = [
    "PluginProtocolV1RetirementPreflightError",
    "PluginProtocolV1RetirementPreflightManifest",
    "RetirementPreflightArtifact",
    "build_plugin_v1_retirement_preflight_manifest",
    "parse_plugin_v1_retirement_preflight_manifest",
]
