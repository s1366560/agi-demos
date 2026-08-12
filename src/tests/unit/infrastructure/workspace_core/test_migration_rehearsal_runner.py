"""Deterministic three-run contracts for Workspace migration rehearsals."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from src.infrastructure.workspace_core.migration.model import (
    EntityMigrationReport,
    MigrationCommand,
    MigrationReport,
    MigrationScope,
    canonical_json,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]
RUNNER_PATH = REPO_ROOT / "scripts/workspace-core/run-migration-rehearsals.py"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("workspace_migration_rehearsals", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FixtureMigrationBackend:
    evidence_class = "fixture-harness"

    def __init__(self, *, records_per_entity: int) -> None:
        self.records_per_entity = records_per_entity
        self.calls: list[tuple[MigrationCommand, str]] = []

    def report(self, command: MigrationCommand, run_id: str) -> MigrationReport:
        entities: list[EntityMigrationReport] = []
        if command is not MigrationCommand.REVERSE_EXPORT:
            for entity_type in ("workspace_profile", "organization_mirror"):
                primary_key_hash = "1" * 64 if entity_type == "workspace_profile" else "2" * 64
                content_hash = "3" * 64 if entity_type == "workspace_profile" else "4" * 64
                verified = self.records_per_entity if command is not MigrationCommand.DRY_RUN else 0
                target_primary_key_hash = (
                    primary_key_hash if command is not MigrationCommand.DRY_RUN else None
                )
                target_content_hash = (
                    content_hash if command is not MigrationCommand.DRY_RUN else None
                )
                entities.append(
                    EntityMigrationReport(
                        entity_type=entity_type,
                        source_table=entity_type,
                        target_table=entity_type,
                        source_count=self.records_per_entity,
                        verified_count=verified,
                        primary_key_hash=primary_key_hash,
                        content_hash=content_hash,
                        target_primary_key_hash=target_primary_key_hash,
                        target_content_hash=target_content_hash,
                    )
                )
        return MigrationReport(
            command=command,
            migration_run_id=run_id,
            migration_version="avernet-workspace-v1",
            scope=MigrationScope(),
            entities=entities,
            exported_records=(
                self.records_per_entity if command is MigrationCommand.REVERSE_EXPORT else 0
            ),
        )

    async def run(
        self,
        command: MigrationCommand,
        *,
        migration_run_id: str,
        scope: MigrationScope,
        output_path: Path | None = None,
        force: bool = False,
    ) -> MigrationReport:
        del scope, force
        self.calls.append((command, migration_run_id))
        if command is MigrationCommand.REVERSE_EXPORT:
            assert output_path is not None
            output_path.write_text(
                "".join(
                    f"{canonical_json({'migration_version': 'avernet-workspace-v1', 'source_table': 'workspaces', 'source_row': {'id': f'workspace-{index}'}})}\n"
                    for index in range(self.records_per_entity)
                ),
                encoding="utf-8",
            )
        return self.report(command, migration_run_id)


class IncrementingClock:
    def __init__(self, step: float) -> None:
        self.value = 0.0
        self.step = step

    def __call__(self) -> float:
        current = self.value
        self.value += self.step
        return current


def test_target_parity_accepts_valid_transformed_primary_keys() -> None:
    runner = _load_runner()
    payload = {
        "entities": [
            {
                "entity_type": "project_principal_membership",
                "source_count": 1,
                "verified_count": 1,
                "failed_count": 0,
                "primary_key_hash": "1" * 64,
                "content_hash": "2" * 64,
                "target_primary_key_hash": "3" * 64,
                "target_content_hash": "2" * 64,
            }
        ]
    }

    runner._validate_target_parity(  # pyright: ignore[reportPrivateUsage]
        payload,
        command=MigrationCommand.EXECUTE,
    )


async def test_fixture_harness_runs_same_configurable_snapshot_three_times(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    backend = FixtureMigrationBackend(records_per_entity=25)
    config = runner.RehearsalConfig(
        run_id="fixture-rehearsal",
        snapshot_id="fixture-25x2",
        evidence_output=tmp_path / "evidence.json",
        export_directory=tmp_path / "exports",
        expected_source_records=50,
    )

    evidence = await runner.run_rehearsals(
        config,
        backend,
        clock=IncrementingClock(0.25),
    )

    assert evidence["evidenceClass"] == "fixture-harness"
    assert evidence["productionEvidence"] is False
    assert evidence["postgresqlEvidence"] is False
    assert evidence["rehearsalCount"] == 3
    assert evidence["snapshot"]["sourceRecords"] == 50
    assert [item["restoreVerified"] for item in evidence["runs"]] == [False, False, False]
    assert [item["migrationAndValidationSeconds"] for item in evidence["runs"]] == [
        0.5,
        0.5,
        0.5,
    ]
    assert [item["recoverySeconds"] for item in evidence["runs"]] == [0.25, 0.25, 0.25]
    assert len(backend.calls) == 12
    assert (tmp_path / "evidence.json").is_file()
    assert len(list((tmp_path / "exports").glob("*.jsonl"))) == 3


async def test_postgres_backend_evidence_is_not_labeled_as_fixture(tmp_path: Path) -> None:
    runner = _load_runner()
    backend = FixtureMigrationBackend(records_per_entity=2)
    backend.evidence_class = "postgresql-snapshot"

    evidence = await runner.run_rehearsals(
        runner.RehearsalConfig(
            run_id="postgres-rehearsal",
            snapshot_id="local-postgres-snapshot",
            evidence_output=tmp_path / "postgres-evidence.json",
            export_directory=tmp_path / "postgres-exports",
        ),
        backend,
        clock=IncrementingClock(0.1),
    )

    assert evidence["evidenceClass"] == "postgresql-snapshot"
    assert evidence["productionEvidence"] is False
    assert evidence["postgresqlEvidence"] is True


async def test_fixture_restore_proof_covers_count_hash_orphans_and_recovery_budget(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    backend = FixtureMigrationBackend(records_per_entity=4)
    executable = tmp_path / "restore-verifier"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    snapshot = runner._snapshot_summary(  # pyright: ignore[reportPrivateUsage]
        runner._report_payload(  # pyright: ignore[reportPrivateUsage]
            backend.report(MigrationCommand.DRY_RUN, "fixture")
        )
    )

    async def restore_runner(
        verifier: Path,
        path: Path,
        run_id: str,
        snapshot_id: str,
        timeout: float,
    ) -> dict[str, Any]:
        assert verifier == executable
        assert path.is_file()
        assert run_id.startswith("fixture-restore-r")
        assert snapshot_id == "fixture-restore"
        assert timeout == 900
        return {
            "ok": True,
            "sourceRecords": snapshot["sourceRecords"],
            "primaryKeySetSha256": snapshot["primaryKeySetSha256"],
            "contentSha256": snapshot["contentSha256"],
            "snapshotSha256": snapshot["snapshotSha256"],
            "orphanCount": 0,
        }

    evidence = await runner.run_rehearsals(
        runner.RehearsalConfig(
            run_id="fixture-restore",
            snapshot_id="fixture-restore",
            evidence_output=tmp_path / "restore-evidence.json",
            export_directory=tmp_path / "restore-exports",
            restore_verifier=executable,
        ),
        backend,
        restore_runner=restore_runner,
        clock=IncrementingClock(0.2),
    )

    assert [item["restoreVerified"] for item in evidence["runs"]] == [True, True, True]
    assert [item["recoverySeconds"] for item in evidence["runs"]] == pytest.approx([0.4, 0.4, 0.4])
    assert all(item["restoreProof"]["orphanCount"] == 0 for item in evidence["runs"])


def test_production_mode_rejects_scopes_missing_snapshot_proof_and_relaxed_budgets(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    restore_verifier = tmp_path / "production-restore-verifier"
    restore_verifier.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    restore_verifier.chmod(0o700)
    base = {
        "run_id": "production-rehearsal",
        "snapshot_id": "snapshot-2026-08-11",
        "evidence_output": tmp_path / "production.json",
        "export_directory": tmp_path / "exports",
        "production_scale": True,
    }

    with pytest.raises(runner.RehearsalError, match="full snapshot"):
        runner._validate_config(  # pyright: ignore[reportPrivateUsage]
            runner.RehearsalConfig(
                **base,
                scope=MigrationScope(workspace_id="workspace-1"),
            )
        )
    with pytest.raises(runner.RehearsalError, match="expected source records"):
        runner._validate_config(  # pyright: ignore[reportPrivateUsage]
            runner.RehearsalConfig(**base)
        )
    with pytest.raises(runner.RehearsalError, match="70 minutes"):
        runner._validate_config(  # pyright: ignore[reportPrivateUsage]
            runner.RehearsalConfig(
                **base,
                expected_source_records=1,
                expected_snapshot_sha256="a" * 64,
                restore_verifier=restore_verifier,
                max_migration_seconds=4201,
            )
        )
