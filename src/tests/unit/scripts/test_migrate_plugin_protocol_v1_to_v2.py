"""Safety tests for the offline plugin V1-to-V2 migration CLI."""

from __future__ import annotations

import hashlib
import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

import scripts.migrate_plugin_protocol_v1_to_v2 as migration_cli
from scripts.migrate_plugin_protocol_v1_to_v2 import (
    MigrationCliError,
    _load_json,
    _parser,
    _postgres_backup_invocation,
    _verify_preflight_bundle,
    _write_json,
)
from src.application.services.plugin_protocol_v1_retirement_preflight import (
    RetirementPreflightArtifact,
    build_plugin_v1_retirement_preflight_manifest,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_v1_migration_repository import (
    digest_payload_v1_to_v2,
)

pytestmark = pytest.mark.unit


def _digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _preflight_fixture(tmp_path: Path) -> tuple[Path, dict[str, object], Path]:
    bundle = tmp_path / "preflight"
    bundle.mkdir(mode=0o700)
    source: dict[str, object] = {
        "schema_version": 1,
        "digest": digest_payload_v1_to_v2({"schema_version": 1, "rows": []}),
        "rows": [],
    }
    mapping: dict[str, object] = {
        "schema_version": 1,
        "migration_id": "migration-001",
        "source": source,
        "target_heads": [
            {
                "scope": {"kind": "root"},
                "expected_revision": None,
                "expected_digest": None,
            }
        ],
        "decisions": [],
    }
    backup_path = bundle / "database.backup"
    backup_path.write_bytes(b"PGDMP-test-archive")
    backup_path.chmod(0o600)
    v1_export_path = bundle / "plugin-v1-export.json"
    _write_json(v1_export_path, mapping)
    unsigned_ready: dict[str, object] = {
        "schema_version": 2,
        "kind": "globally_ready_plugin_publication_v2",
        "publication_id": "publication-1",
        "profile_id": "memstack-default",
        "generation": 7,
        "snapshot_digest": "3" * 64,
        "requested_version": 9,
        "nonce": "ready-9",
        "type_url": "type.memstack.ai/plugin-profile.v2",
        "required_data_plane_ids": ["python-api-v2"],
        "globally_ready_at": "2026-08-24T12:00:00Z",
        "distribution": {},
    }
    ready_payload = {
        **unsigned_ready,
        "digest": digest_payload_v1_to_v2(unsigned_ready),
    }
    ready_path = bundle / "last-ready-v2-snapshot.json"
    _write_json(ready_path, ready_payload)
    manifest = build_plugin_v1_retirement_preflight_manifest(
        migration_id="migration-001",
        created_at=datetime(2026, 8, 24, 12, 1, tzinfo=UTC),
        v1_source_digest=str(source["digest"]),
        globally_ready_publication_nonce="ready-9",
        globally_ready_requested_version=9,
        globally_ready_snapshot_digest="3" * 64,
        database_backup=RetirementPreflightArtifact(
            path=backup_path.name,
            digest=_digest(backup_path.read_bytes()),
            size_bytes=backup_path.stat().st_size,
            media_type="application/vnd.postgresql.custom",
        ),
        v1_export=RetirementPreflightArtifact(
            path=v1_export_path.name,
            digest=_digest(v1_export_path.read_bytes()),
            size_bytes=v1_export_path.stat().st_size,
            media_type="application/json",
        ),
        last_ready_v2_snapshot=RetirementPreflightArtifact(
            path=ready_path.name,
            digest=_digest(ready_path.read_bytes()),
            size_bytes=ready_path.stat().st_size,
            media_type="application/json",
        ),
    )
    manifest_path = bundle / "preflight-manifest.json"
    _write_json(manifest_path, manifest.to_payload())
    return manifest_path, mapping, v1_export_path


def test_cli_requires_explicit_subcommand_and_apply_confirmation(tmp_path: Path) -> None:
    parser = _parser()

    preflight = parser.parse_args(
        [
            "preflight",
            "--migration-id",
            "migration-001",
            "--output-dir",
            str(tmp_path / "preflight"),
        ]
    )

    args = parser.parse_args(
        [
            "apply",
            "--mapping",
            str(tmp_path / "mapping.json"),
            "--actor-id",
            "platform-admin",
            "--confirm-migration-id",
            "migration-001",
            "--preflight-manifest",
            str(tmp_path / "preflight" / "preflight-manifest.json"),
            "--output",
            str(tmp_path / "report.json"),
        ]
    )

    assert preflight.command == "preflight"
    assert preflight.output_dir == tmp_path / "preflight"
    assert args.command == "apply"
    assert args.confirm_migration_id == "migration-001"
    assert args.preflight_manifest.name == "preflight-manifest.json"


def test_postgres_backup_invocation_keeps_password_out_of_process_arguments(
    tmp_path: Path,
) -> None:
    command, environment = _postgres_backup_invocation(
        database_url="postgresql+asyncpg://operator:sensitive-value@db.internal:5544/memstack",
        output=tmp_path / "database.backup",
        base_environment={"PATH": "/usr/bin"},
        executable="/usr/bin/pg_dump",
    )

    assert all("sensitive-value" not in argument for argument in command)
    assert command[-1] == "memstack"
    assert environment == {"PATH": "/usr/bin", "PGPASSWORD": "sensitive-value"}


def test_mapping_loader_rejects_duplicate_keys_and_oversized_input(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version": 1, "schema_version": 2}', encoding="utf-8")
    with pytest.raises(MigrationCliError) as duplicate_error:
        _load_json(duplicate)
    assert duplicate_error.value.code == "migration_mapping_duplicate_key"

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    with pytest.raises(MigrationCliError) as size_error:
        _load_json(oversized)
    assert size_error.value.code == "migration_mapping_too_large"


def test_audit_writer_is_private_and_never_overwrites(tmp_path: Path) -> None:
    output = tmp_path / "audit.json"
    _write_json(output, {"source_digest": "sha256:test"})

    assert json.loads(output.read_text(encoding="utf-8"))["source_digest"] == "sha256:test"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(MigrationCliError) as exists:
        _write_json(output, {"source_digest": "sha256:changed"})
    assert exists.value.code == "migration_output_exists"


def test_preflight_bundle_verification_binds_all_artifacts_and_rejects_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, mapping, v1_export_path = _preflight_fixture(tmp_path)
    monkeypatch.setattr(migration_cli, "_validate_postgres_backup_archive", lambda _path: None)

    verified = _verify_preflight_bundle(manifest_path, mapping=mapping)

    assert verified.manifest.migration_id == "migration-001"
    assert verified.last_ready_v2_snapshot["nonce"] == "ready-9"

    v1_export_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(MigrationCliError) as changed:
        _verify_preflight_bundle(manifest_path, mapping=mapping)
    assert changed.value.code == "migration_preflight_artifact_changed"
