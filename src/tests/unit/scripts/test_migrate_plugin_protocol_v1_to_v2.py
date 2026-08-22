"""Safety tests for the offline plugin V1-to-V2 migration CLI."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from scripts.migrate_plugin_protocol_v1_to_v2 import (
    MigrationCliError,
    _load_json,
    _parser,
    _write_json,
)

pytestmark = pytest.mark.unit


def test_cli_requires_explicit_subcommand_and_apply_confirmation(tmp_path: Path) -> None:
    parser = _parser()

    args = parser.parse_args(
        [
            "apply",
            "--mapping",
            str(tmp_path / "mapping.json"),
            "--actor-id",
            "platform-admin",
            "--confirm-migration-id",
            "migration-001",
            "--output",
            str(tmp_path / "report.json"),
        ]
    )

    assert args.command == "apply"
    assert args.confirm_migration_id == "migration-001"


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
