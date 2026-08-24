"""Strict evidence contract for destructive plugin protocol-v1 retirement."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from src.application.services.plugin_protocol_v1_retirement_preflight import (
    PluginProtocolV1RetirementPreflightError,
    RetirementPreflightArtifact,
    build_plugin_v1_retirement_preflight_manifest,
    parse_plugin_v1_retirement_preflight_manifest,
)

pytestmark = pytest.mark.unit
_SOURCE_DIGEST = f"sha256:{'1' * 64}"
_ARTIFACT_DIGEST = f"sha256:{'2' * 64}"
_SNAPSHOT_DIGEST = "3" * 64


def _artifact(path: str, media_type: str) -> RetirementPreflightArtifact:
    return RetirementPreflightArtifact(
        path=path,
        digest=_ARTIFACT_DIGEST,
        size_bytes=128,
        media_type=media_type,
    )


def _manifest_payload() -> dict[str, object]:
    manifest = build_plugin_v1_retirement_preflight_manifest(
        migration_id="plugin-v1-final-20260824",
        created_at=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
        v1_source_digest=_SOURCE_DIGEST,
        globally_ready_publication_nonce="ready-publication-17",
        globally_ready_requested_version=17,
        globally_ready_snapshot_digest=_SNAPSHOT_DIGEST,
        database_backup=_artifact(
            "database.backup",
            "application/vnd.postgresql.custom",
        ),
        v1_export=_artifact("plugin-v1-export.json", "application/json"),
        last_ready_v2_snapshot=_artifact(
            "last-ready-v2-snapshot.json",
            "application/json",
        ),
    )
    return manifest.to_payload()


def test_preflight_manifest_is_canonical_strict_and_content_addressed() -> None:
    payload = _manifest_payload()

    parsed = parse_plugin_v1_retirement_preflight_manifest(payload)

    assert parsed.migration_id == "plugin-v1-final-20260824"
    assert parsed.v1_source_digest == _SOURCE_DIGEST
    assert parsed.globally_ready_publication_nonce == "ready-publication-17"
    assert parsed.globally_ready_requested_version == 17
    assert parsed.globally_ready_snapshot_digest == _SNAPSHOT_DIGEST
    assert parsed.to_payload() == payload


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (
            lambda payload: payload.update(v1_source_digest=f"sha256:{'4' * 64}"),
            "migration_preflight_manifest_digest_invalid",
        ),
        (
            lambda payload: payload["artifacts"]["database_backup"].update(  # type: ignore[index,union-attr]
                path="../database.backup"
            ),
            "migration_preflight_artifact_invalid",
        ),
        (
            lambda payload: payload.update(unexpected=True),
            "migration_preflight_manifest_invalid",
        ),
    ],
)
def test_preflight_manifest_rejects_tampering_and_unsafe_paths(mutator, code: str) -> None:
    payload = deepcopy(_manifest_payload())
    mutator(payload)

    with pytest.raises(PluginProtocolV1RetirementPreflightError) as error:
        parse_plugin_v1_retirement_preflight_manifest(payload)

    assert error.value.code == code
