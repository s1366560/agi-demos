#!/usr/bin/env python3
"""Run three deterministic Workspace migration and recovery rehearsals."""

# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

import asyncpg
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.configuration.config import get_settings  # noqa: E402
from src.infrastructure.workspace_core.migration.model import (  # noqa: E402
    MIGRATION_VERSION,
    MigrationCommand,
    MigrationReport,
    MigrationScope,
    canonical_json,
)
from src.infrastructure.workspace_core.migration.service import (  # noqa: E402
    WorkspaceMigrationService,
)
from src.infrastructure.workspace_core.migration.specs import MIGRATION_SPECS  # noqa: E402

REHEARSAL_COUNT = 3
PRODUCTION_MIGRATION_LIMIT_SECONDS = 70 * 60
PRODUCTION_RECOVERY_LIMIT_SECONDS = 15 * 60
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVERSE_ENTITY_TYPES = {
    spec.entity_type for spec in MIGRATION_SPECS if spec.reverse_mapper is not None
}


class RehearsalError(RuntimeError):
    """Raised when a rehearsal cannot provide release-grade evidence."""


class MigrationBackend(Protocol):
    """Minimal backend used by the real PostgreSQL runner and fixture tests."""

    evidence_class: str

    async def run(
        self,
        command: MigrationCommand,
        *,
        migration_run_id: str,
        scope: MigrationScope,
        output_path: Path | None = None,
        force: bool = False,
    ) -> MigrationReport: ...


RestoreRunner = Callable[[Path, Path, str, str, float], Awaitable[Mapping[str, Any]]]
Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class RehearsalConfig:
    """Safety and evidence inputs for exactly three rehearsals."""

    run_id: str
    snapshot_id: str
    evidence_output: Path
    export_directory: Path
    scope: MigrationScope = field(default_factory=MigrationScope)
    production_scale: bool = False
    expected_source_records: int | None = None
    expected_snapshot_sha256: str | None = None
    restore_verifier: Path | None = None
    max_migration_seconds: float = PRODUCTION_MIGRATION_LIMIT_SECONDS
    max_recovery_seconds: float = PRODUCTION_RECOVERY_LIMIT_SECONDS
    force: bool = False


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _report_payload(report: MigrationReport) -> dict[str, Any]:
    payload = cast("dict[str, Any]", json.loads(report.to_json()))
    if not report.ok:
        issues = [str(item.get("code")) for item in payload.get("preflight_issues", [])]
        raise RehearsalError(f"migration phase failed preflight: {issues}")
    if payload.get("preflight_issues"):
        raise RehearsalError("successful migration phase unexpectedly contains preflight issues")
    return payload


def _snapshot_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    entities = cast("list[dict[str, Any]]", payload.get("entities", []))
    if not entities:
        raise RehearsalError("migration report contains no entity evidence")
    normalized = [
        {
            "entityType": item["entity_type"],
            "sourceCount": item["source_count"],
            "primaryKeyHash": item["primary_key_hash"],
            "contentHash": item["content_hash"],
        }
        for item in sorted(entities, key=lambda value: str(value["entity_type"]))
    ]
    return {
        "sourceRecords": sum(int(item["sourceCount"]) for item in normalized),
        "primaryKeySetSha256": _hash(
            [(item["entityType"], item["primaryKeyHash"]) for item in normalized]
        ),
        "contentSha256": _hash([(item["entityType"], item["contentHash"]) for item in normalized]),
        "snapshotSha256": _hash(normalized),
        "entities": normalized,
    }


def _validate_target_parity(payload: Mapping[str, Any], *, command: MigrationCommand) -> None:
    if command is MigrationCommand.DRY_RUN:
        return
    for entity in cast("list[dict[str, Any]]", payload["entities"]):
        name = str(entity["entity_type"])
        source_count = int(entity["source_count"])
        if int(entity["verified_count"]) != source_count or int(entity["failed_count"]) != 0:
            raise RehearsalError(f"{command.value} count mismatch for {name}")
        hash_fields = (
            "primary_key_hash",
            "target_primary_key_hash",
            "content_hash",
            "target_content_hash",
        )
        if any(
            not isinstance(entity.get(field), str)
            or _SHA256.fullmatch(cast("str", entity[field])) is None
            for field in hash_fields
        ):
            raise RehearsalError(f"{command.value} hash evidence is invalid for {name}")
        if entity["target_content_hash"] != entity["content_hash"]:
            raise RehearsalError(f"{command.value} content hash mismatch for {name}")


def _expected_reverse_records(payload: Mapping[str, Any]) -> int:
    return sum(
        int(entity["source_count"])
        for entity in cast("list[dict[str, Any]]", payload["entities"])
        if entity["entity_type"] in _REVERSE_ENTITY_TYPES
    )


def _inspect_reverse_export(path: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line:
            raise RehearsalError(f"reverse export contains a blank line at {line_number}")
        item = json.loads(raw_line)
        if not isinstance(item, dict):
            raise RehearsalError(f"reverse export row {line_number} is not an object")
        if (
            item.get("migration_version") != MIGRATION_VERSION
            or not isinstance(item.get("source_table"), str)
            or not isinstance(item.get("source_row"), dict)
        ):
            raise RehearsalError(f"reverse export row {line_number} has an invalid envelope")
        if raw_line != canonical_json(item):
            raise RehearsalError(f"reverse export row {line_number} is not canonical JSON")
        records.append(cast("dict[str, Any]", item))
    return {
        "recordCount": len(records),
        "contentSha256": _hash(records),
        "tablesSha256": _hash(sorted(str(item["source_table"]) for item in records)),
    }


def _validate_config(config: RehearsalConfig) -> None:
    if not config.run_id.strip() or not config.snapshot_id.strip():
        raise RehearsalError("run id and snapshot id must not be blank")
    if config.max_migration_seconds <= 0 or config.max_recovery_seconds <= 0:
        raise RehearsalError("rehearsal timing limits must be positive")
    if config.production_scale:
        if any(asdict(config.scope).values()):
            raise RehearsalError("production-scale rehearsal must cover the full snapshot")
        if config.expected_source_records is None or config.expected_source_records <= 0:
            raise RehearsalError("production-scale rehearsal requires expected source records")
        if (
            config.expected_snapshot_sha256 is None
            or _SHA256.fullmatch(config.expected_snapshot_sha256) is None
        ):
            raise RehearsalError("production-scale rehearsal requires the expected snapshot hash")
        if config.restore_verifier is None or not config.restore_verifier.is_file():
            raise RehearsalError(
                "production-scale rehearsal requires a restore verifier executable"
            )
        if not os.access(config.restore_verifier, os.X_OK):
            raise RehearsalError("restore verifier is not executable")
        if config.max_migration_seconds > PRODUCTION_MIGRATION_LIMIT_SECONDS:
            raise RehearsalError("production migration limit cannot exceed 70 minutes")
        if config.max_recovery_seconds > PRODUCTION_RECOVERY_LIMIT_SECONDS:
            raise RehearsalError("production recovery limit cannot exceed 15 minutes")


async def _run_restore_verifier(
    executable: Path,
    export_path: Path,
    rehearsal_id: str,
    snapshot_id: str,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    environment = os.environ.copy()
    environment.update(
        {
            "WORKSPACE_REHEARSAL_EXPORT_PATH": str(export_path),
            "WORKSPACE_REHEARSAL_RUN_ID": rehearsal_id,
            "WORKSPACE_REHEARSAL_SNAPSHOT_ID": snapshot_id,
        }
    )
    process = await asyncio.create_subprocess_exec(
        str(executable),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    try:
        stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except TimeoutError:
        process.kill()
        _ = await process.communicate()
        raise RehearsalError("legacy restore verifier exceeded its time budget") from None
    if process.returncode != 0:
        raise RehearsalError("legacy restore verifier failed")
    if len(stdout) > 64 * 1024:
        raise RehearsalError("legacy restore verifier output exceeds 64 KiB")
    lines = [line for line in stdout.decode("utf-8").splitlines() if line.strip()]
    if len(lines) != 1:
        raise RehearsalError("legacy restore verifier must emit exactly one JSON object")
    payload = json.loads(lines[0])
    if not isinstance(payload, Mapping):
        raise RehearsalError("legacy restore verifier output must be an object")
    return cast("Mapping[str, Any]", payload)


def _validate_restore_proof(
    proof: Mapping[str, Any],
    *,
    expected_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    expected = {
        "ok": True,
        "sourceRecords": expected_snapshot["sourceRecords"],
        "primaryKeySetSha256": expected_snapshot["primaryKeySetSha256"],
        "contentSha256": expected_snapshot["contentSha256"],
        "snapshotSha256": expected_snapshot["snapshotSha256"],
        "orphanCount": 0,
    }
    actual = {key: proof.get(key) for key in expected}
    if actual != expected:
        raise RehearsalError("legacy restore verifier proof does not match the source snapshot")
    return cast("dict[str, Any]", actual)


@dataclass(frozen=True, slots=True)
class _MigrationPhaseResult:
    evidence: dict[str, Any]
    payloads: dict[MigrationCommand, dict[str, Any]]
    snapshot: dict[str, Any]
    duration_seconds: float


async def _run_migration_phases(
    config: RehearsalConfig,
    backend: MigrationBackend,
    rehearsal_id: str,
    *,
    baseline_snapshot: Mapping[str, Any] | None,
    clock: Clock,
) -> _MigrationPhaseResult:
    evidence: dict[str, Any] = {}
    payloads: dict[MigrationCommand, dict[str, Any]] = {}
    durations: dict[MigrationCommand, float] = {}
    authoritative_snapshot = dict(baseline_snapshot) if baseline_snapshot is not None else None
    for command in (
        MigrationCommand.DRY_RUN,
        MigrationCommand.EXECUTE,
        MigrationCommand.VALIDATE,
    ):
        started_at = clock()
        report = await backend.run(
            command,
            migration_run_id=rehearsal_id,
            scope=config.scope,
        )
        duration = clock() - started_at
        payload = _report_payload(report)
        _validate_target_parity(payload, command=command)
        snapshot = _snapshot_summary(payload)
        if authoritative_snapshot is None:
            authoritative_snapshot = snapshot
        elif snapshot != authoritative_snapshot:
            raise RehearsalError("source snapshot changed between rehearsal phases")
        payloads[command] = payload
        durations[command] = duration
        evidence[command.value] = {
            "durationSeconds": duration,
            "sourceRecords": snapshot["sourceRecords"],
            "snapshotSha256": snapshot["snapshotSha256"],
            "orphanCount": 0,
        }

    assert authoritative_snapshot is not None
    migration_seconds = durations[MigrationCommand.EXECUTE] + durations[MigrationCommand.VALIDATE]
    if migration_seconds > config.max_migration_seconds:
        raise RehearsalError("migration and validation exceeded the configured time budget")
    return _MigrationPhaseResult(
        evidence=evidence,
        payloads=payloads,
        snapshot=authoritative_snapshot,
        duration_seconds=migration_seconds,
    )


@dataclass(frozen=True, slots=True)
class _RecoveryPhaseResult:
    evidence: dict[str, Any]
    export_hash: str
    duration_seconds: float
    restore_proof: dict[str, Any] | None


async def _run_recovery_phase(
    config: RehearsalConfig,
    backend: MigrationBackend,
    rehearsal_id: str,
    *,
    execute_payload: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    baseline_export_hash: str | None,
    restore_runner: RestoreRunner,
    clock: Clock,
) -> _RecoveryPhaseResult:
    export_path = config.export_directory / f"{rehearsal_id}.jsonl"
    reverse_started_at = clock()
    reverse_report = await backend.run(
        MigrationCommand.REVERSE_EXPORT,
        migration_run_id=rehearsal_id,
        scope=config.scope,
        output_path=export_path,
        force=config.force,
    )
    reverse_seconds = clock() - reverse_started_at
    reverse_payload = _report_payload(reverse_report)
    export_summary = _inspect_reverse_export(export_path)
    expected_exported = _expected_reverse_records(execute_payload)
    if (
        int(reverse_payload.get("exported_records", -1)) != expected_exported
        or export_summary["recordCount"] != expected_exported
    ):
        raise RehearsalError("reverse export count does not match authoritative source rows")
    export_hash = cast("str", export_summary["contentSha256"])
    if baseline_export_hash is not None and export_hash != baseline_export_hash:
        raise RehearsalError("reverse export content changed between rehearsals")

    restore_proof: dict[str, Any] | None = None
    restore_seconds = 0.0
    if config.restore_verifier is not None:
        restore_started_at = clock()
        raw_restore_proof = await restore_runner(
            config.restore_verifier,
            export_path,
            rehearsal_id,
            config.snapshot_id,
            config.max_recovery_seconds,
        )
        restore_seconds = clock() - restore_started_at
        restore_proof = _validate_restore_proof(
            raw_restore_proof,
            expected_snapshot=source_snapshot,
        )
    recovery_seconds = reverse_seconds + restore_seconds
    if recovery_seconds > config.max_recovery_seconds:
        raise RehearsalError("reverse export and restore exceeded the configured time budget")
    return _RecoveryPhaseResult(
        evidence={"durationSeconds": reverse_seconds, **export_summary},
        export_hash=export_hash,
        duration_seconds=recovery_seconds,
        restore_proof=restore_proof,
    )


async def _run_one_rehearsal(
    config: RehearsalConfig,
    backend: MigrationBackend,
    number: int,
    *,
    baseline_snapshot: Mapping[str, Any] | None,
    baseline_export_hash: str | None,
    restore_runner: RestoreRunner,
    clock: Clock,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    rehearsal_id = f"{config.run_id}-r{number}"
    migration = await _run_migration_phases(
        config,
        backend,
        rehearsal_id,
        baseline_snapshot=baseline_snapshot,
        clock=clock,
    )
    recovery = await _run_recovery_phase(
        config,
        backend,
        rehearsal_id,
        execute_payload=migration.payloads[MigrationCommand.EXECUTE],
        source_snapshot=migration.snapshot,
        baseline_export_hash=baseline_export_hash,
        restore_runner=restore_runner,
        clock=clock,
    )
    phases = dict(migration.evidence)
    phases[MigrationCommand.REVERSE_EXPORT.value] = recovery.evidence
    run = {
        "rehearsal": number,
        "runId": rehearsal_id,
        "phases": phases,
        "migrationAndValidationSeconds": migration.duration_seconds,
        "recoverySeconds": recovery.duration_seconds,
        "restoreVerified": recovery.restore_proof is not None,
        "restoreProof": recovery.restore_proof,
    }
    return run, migration.snapshot, recovery.export_hash


async def run_rehearsals(
    config: RehearsalConfig,
    backend: MigrationBackend,
    *,
    restore_runner: RestoreRunner = _run_restore_verifier,
    clock: Clock = time.perf_counter,
) -> dict[str, Any]:
    """Execute exactly three runs and return release-auditable evidence."""

    _validate_config(config)
    if config.evidence_output.exists() and not config.force:
        raise RehearsalError("evidence output already exists")
    config.export_directory.mkdir(parents=True, exist_ok=True)
    config.evidence_output.parent.mkdir(parents=True, exist_ok=True)

    baseline_snapshot: dict[str, Any] | None = None
    baseline_export_hash: str | None = None
    runs: list[dict[str, Any]] = []
    for number in range(1, REHEARSAL_COUNT + 1):
        run, baseline_snapshot, baseline_export_hash = await _run_one_rehearsal(
            config,
            backend,
            number,
            baseline_snapshot=baseline_snapshot,
            baseline_export_hash=baseline_export_hash,
            restore_runner=restore_runner,
            clock=clock,
        )
        runs.append(run)

    assert baseline_snapshot is not None
    if config.expected_source_records is not None and (
        baseline_snapshot["sourceRecords"] != config.expected_source_records
    ):
        raise RehearsalError("source record count does not match the declared snapshot")
    if config.expected_snapshot_sha256 is not None and (
        baseline_snapshot["snapshotSha256"] != config.expected_snapshot_sha256
    ):
        raise RehearsalError("source snapshot hash does not match the declared snapshot")
    backend_evidence_class = backend.evidence_class
    if backend_evidence_class not in {"fixture-harness", "postgresql-snapshot"}:
        raise RehearsalError("migration backend declares an unsupported evidence class")
    if config.production_scale and backend_evidence_class != "postgresql-snapshot":
        raise RehearsalError("production-scale rehearsal requires the PostgreSQL backend")
    if config.production_scale and not all(run["restoreVerified"] for run in runs):
        raise RehearsalError("production-scale rehearsal lacks verified legacy restore evidence")

    evidence_class = "production-scale" if config.production_scale else backend_evidence_class
    evidence = {
        "schemaVersion": "workspace-migration-rehearsal-v1",
        "ok": True,
        "evidenceClass": evidence_class,
        "productionEvidence": config.production_scale,
        "postgresqlEvidence": backend_evidence_class == "postgresql-snapshot",
        "migrationVersion": MIGRATION_VERSION,
        "snapshotId": config.snapshot_id,
        "snapshot": baseline_snapshot,
        "rehearsalCount": len(runs),
        "thresholds": {
            "migrationAndValidationSeconds": config.max_migration_seconds,
            "recoverySeconds": config.max_recovery_seconds,
        },
        "runs": runs,
    }
    temporary = config.evidence_output.with_name(f".{config.evidence_output.name}.tmp")
    try:
        _ = temporary.write_text(f"{canonical_json(evidence)}\n", encoding="utf-8")
        os.replace(temporary, config.evidence_output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return evidence


class PostgresMigrationBackend:
    """Real service backend over one PostgreSQL snapshot connection."""

    evidence_class = "postgresql-snapshot"

    def __init__(self, connection: asyncpg.Connection) -> None:
        super().__init__()
        self._service = WorkspaceMigrationService(connection)

    async def run(
        self,
        command: MigrationCommand,
        *,
        migration_run_id: str,
        scope: MigrationScope,
        output_path: Path | None = None,
        force: bool = False,
    ) -> MigrationReport:
        return await self._service.run(
            command,
            migration_run_id=migration_run_id,
            scope=scope,
            output_path=output_path,
            force=force,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--database-url")
    _ = parser.add_argument("--run-id", required=True)
    _ = parser.add_argument("--snapshot-id", required=True)
    _ = parser.add_argument("--evidence-output", type=Path, required=True)
    _ = parser.add_argument("--export-directory", type=Path, required=True)
    _ = parser.add_argument("--tenant-id")
    _ = parser.add_argument("--project-id")
    _ = parser.add_argument("--workspace-id")
    _ = parser.add_argument("--production-scale", action="store_true")
    _ = parser.add_argument("--expected-source-records", type=int)
    _ = parser.add_argument("--expected-snapshot-sha256")
    _ = parser.add_argument("--restore-verifier", type=Path)
    _ = parser.add_argument(
        "--max-migration-seconds",
        type=float,
        default=PRODUCTION_MIGRATION_LIMIT_SECONDS,
    )
    _ = parser.add_argument(
        "--max-recovery-seconds",
        type=float,
        default=PRODUCTION_RECOVERY_LIMIT_SECONDS,
    )
    _ = parser.add_argument("--force", action="store_true")
    return parser


def _asyncpg_url(raw_url: str) -> str:
    url = make_url(raw_url)
    if not url.drivername.startswith("postgresql"):
        raise RehearsalError("Workspace rehearsal requires a PostgreSQL database URL")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


async def _main(args: argparse.Namespace) -> dict[str, Any]:
    config = RehearsalConfig(
        run_id=args.run_id,
        snapshot_id=args.snapshot_id,
        evidence_output=args.evidence_output,
        export_directory=args.export_directory,
        scope=MigrationScope(
            tenant_id=args.tenant_id,
            project_id=args.project_id,
            workspace_id=args.workspace_id,
        ),
        production_scale=args.production_scale,
        expected_source_records=args.expected_source_records,
        expected_snapshot_sha256=args.expected_snapshot_sha256,
        restore_verifier=args.restore_verifier,
        max_migration_seconds=args.max_migration_seconds,
        max_recovery_seconds=args.max_recovery_seconds,
        force=args.force,
    )
    configured_url = args.database_url or get_settings().postgres_url
    connection = await asyncpg.connect(_asyncpg_url(configured_url))
    try:
        return await run_rehearsals(config, PostgresMigrationBackend(connection))
    finally:
        await connection.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = asyncio.run(_main(args))
    except (RehearsalError, OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "evidenceClass": evidence["evidenceClass"],
                "rehearsalCount": evidence["rehearsalCount"],
                "snapshotSha256": evidence["snapshot"]["snapshotSha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
