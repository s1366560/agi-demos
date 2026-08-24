#!/usr/bin/env python3
"""Export, plan, and atomically apply the one-shot plugin V1 desired-state conversion."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, cast

from sqlalchemy.engine import make_url

from src.application.services.plugin_protocol_v1_retirement_preflight import (
    PluginProtocolV1RetirementPreflightError,
    PluginProtocolV1RetirementPreflightManifest,
    RetirementPreflightArtifact,
    build_plugin_v1_retirement_preflight_manifest,
    parse_plugin_v1_retirement_preflight_manifest,
)
from src.application.services.plugin_protocol_v1_to_v2_migration_contract import (
    PluginProtocolV1ToV2MigrationError,
    parse_plugin_v1_to_v2_migration_document,
)
from src.application.services.plugin_protocol_v1_to_v2_migration_service import (
    PluginProtocolV1ToV2MigrationService,
)
from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_v1_migration_repository import (
    PlatformPluginV1MigrationRepository,
    PlatformPluginV1MigrationRepositoryError,
    digest_payload_v1_to_v2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

_MAX_MAPPING_BYTES = 2 * 1024 * 1024
_MAX_RECOVERY_JSON_BYTES = 32 * 1024 * 1024
_DATABASE_BACKUP_NAME = "database.backup"
_V1_EXPORT_NAME = "plugin-v1-export.json"
_LAST_READY_V2_SNAPSHOT_NAME = "last-ready-v2-snapshot.json"
_PREFLIGHT_MANIFEST_NAME = "preflight-manifest.json"
_POSTGRES_BACKUP_MEDIA_TYPE = "application/vnd.postgresql.custom"
_JSON_MEDIA_TYPE = "application/json"
_POSTGRES_CUSTOM_ARCHIVE_MAGIC = b"PGDMP"
_BACKUP_TIMEOUT_SECONDS = 3600
_BACKUP_VERIFY_TIMEOUT_SECONDS = 120


class MigrationCliError(ValueError):
    """Safe operator-facing CLI contract failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, kw_only=True)
class _VerifiedRetirementPreflight:
    manifest: PluginProtocolV1RetirementPreflightManifest
    last_ready_v2_snapshot: dict[str, object]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot offline conversion from frozen plugin protocol V1 desired rows to V2"
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser(
        "preflight",
        help="Create the mandatory database and rollback evidence bundle",
    )
    _ = preflight.add_argument("--migration-id", required=True)
    _ = preflight.add_argument("--output-dir", required=True, type=Path)

    export = commands.add_parser("export", help="Export a secret-free mapping template")
    _ = export.add_argument("--migration-id", required=True)
    _ = export.add_argument("--output", required=True, type=Path)

    plan = commands.add_parser("plan", help="Validate a completed mapping without writes")
    _ = plan.add_argument("--mapping", required=True, type=Path)
    _ = plan.add_argument("--preflight-manifest", required=True, type=Path)
    _ = plan.add_argument("--output", required=True, type=Path)

    apply = commands.add_parser("apply", help="Atomically append V2 heads and audit evidence")
    _ = apply.add_argument("--mapping", required=True, type=Path)
    _ = apply.add_argument("--actor-id", required=True)
    _ = apply.add_argument(
        "--confirm-migration-id",
        required=True,
        help="Must exactly match migration_id inside the reviewed mapping",
    )
    _ = apply.add_argument("--preflight-manifest", required=True, type=Path)
    _ = apply.add_argument("--output", required=True, type=Path)
    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.command == "preflight":
        _ = await _create_preflight_bundle(
            migration_id=args.migration_id,
            output_dir=args.output_dir,
        )
        return 0

    if args.command == "export":
        async with async_session_factory() as session:
            payload = await _service(session).export_template(migration_id=args.migration_id)
        _write_json(args.output, payload)
        return 0

    mapping = _load_json(args.mapping)
    verified = _verify_preflight_bundle(args.preflight_manifest, mapping=mapping)
    if args.command == "plan":
        async with async_session_factory() as session:
            await _verify_persisted_preflight(session, verified)
            plan = await _service(session).plan(mapping)
        _write_json(
            args.output,
            {
                **plan.to_payload(),
                "preflight_manifest_digest": verified.manifest.manifest_digest,
            },
        )
        return 0

    if args.command != "apply":  # pragma: no cover - argparse invariant
        raise RuntimeError(f"unsupported command {args.command}")
    document = parse_plugin_v1_to_v2_migration_document(mapping)
    if args.confirm_migration_id != document.migration_id:
        raise MigrationCliError(
            "migration_confirmation_mismatch",
            "--confirm-migration-id differs from the reviewed mapping",
        )
    async with async_session_factory() as session, session.begin():
        await _verify_persisted_preflight(session, verified)
        result = await _service(session).execute(mapping, actor_id=args.actor_id)
    _write_json(
        args.output,
        _conversion_audit_payload(
            result=result.report,
            preflight=verified.manifest,
        ),
    )
    return 0


def _service(session: AsyncSession) -> PluginProtocolV1ToV2MigrationService:
    return PluginProtocolV1ToV2MigrationService(
        migration_repository=PlatformPluginV1MigrationRepository(session),
        desired_repository=PlatformPluginDesiredBundleSetRepositoryV2(session),
        governance_repository=PlatformPluginGovernanceRepository(session),
        production_sources=production_bundle_sources_v2(),
    )


async def _create_preflight_bundle(*, migration_id: str, output_dir: Path) -> Path:
    """Create all recovery artifacts in a private directory and publish it atomically."""
    if os.path.lexists(output_dir):
        raise MigrationCliError(
            "migration_preflight_output_exists",
            "preflight output directory already exists",
        )
    output_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name or 'plugin-v1-preflight'}.",
            dir=output_dir.parent,
        )
    )
    temporary_dir.chmod(0o700)
    try:
        database_backup = temporary_dir / _DATABASE_BACKUP_NAME
        await asyncio.to_thread(
            _dump_postgres_database,
            database_backup,
            get_settings().postgres_url,
        )
        async with async_session_factory() as session:
            v1_export = await _service(session).export_template(migration_id=migration_id)
            last_ready = await PlatformPluginV1MigrationRepository(
                session
            ).export_globally_ready_v2()
        v1_export_path = temporary_dir / _V1_EXPORT_NAME
        last_ready_path = temporary_dir / _LAST_READY_V2_SNAPSHOT_NAME
        _write_json(v1_export_path, v1_export)
        _write_json(last_ready_path, last_ready.to_payload())
        manifest = build_plugin_v1_retirement_preflight_manifest(
            migration_id=migration_id,
            created_at=datetime.now(UTC),
            v1_source_digest=_v1_source_digest(v1_export),
            globally_ready_publication_nonce=last_ready.nonce,
            globally_ready_requested_version=last_ready.requested_version,
            globally_ready_snapshot_digest=last_ready.snapshot_digest,
            database_backup=_artifact_record(
                database_backup,
                path=_DATABASE_BACKUP_NAME,
                media_type=_POSTGRES_BACKUP_MEDIA_TYPE,
            ),
            v1_export=_artifact_record(
                v1_export_path,
                path=_V1_EXPORT_NAME,
                media_type=_JSON_MEDIA_TYPE,
            ),
            last_ready_v2_snapshot=_artifact_record(
                last_ready_path,
                path=_LAST_READY_V2_SNAPSHOT_NAME,
                media_type=_JSON_MEDIA_TYPE,
            ),
        )
        _write_json(temporary_dir / _PREFLIGHT_MANIFEST_NAME, manifest.to_payload())
        if os.path.lexists(output_dir):
            raise MigrationCliError(
                "migration_preflight_output_exists",
                "preflight output directory was created concurrently",
            )
        os.rename(temporary_dir, output_dir)
        output_dir.chmod(0o700)
        return output_dir / _PREFLIGHT_MANIFEST_NAME
    except Exception:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise


def _dump_postgres_database(output: Path, database_url: str) -> None:
    executable = shutil.which("pg_dump")
    if executable is None:
        raise MigrationCliError(
            "migration_database_backup_tool_unavailable",
            "pg_dump is required to create retirement recovery evidence",
        )
    command, environment = _postgres_backup_invocation(
        database_url=database_url,
        output=output,
        base_environment=os.environ,
        executable=executable,
    )
    try:
        completed = subprocess.run(
            command,
            env=environment,
            check=False,
            capture_output=True,
            timeout=_BACKUP_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MigrationCliError(
            "migration_database_backup_failed",
            "PostgreSQL backup process did not complete",
        ) from exc
    if completed.returncode != 0:
        output.unlink(missing_ok=True)
        raise MigrationCliError(
            "migration_database_backup_failed",
            "pg_dump rejected the retirement database backup",
        )
    output.chmod(0o600)
    _validate_postgres_backup_archive(output)


def _postgres_backup_invocation(
    *,
    database_url: str,
    output: Path,
    base_environment: Mapping[str, str],
    executable: str,
) -> tuple[list[str], dict[str, str]]:
    """Build a pg_dump invocation without placing the database password in argv."""
    try:
        url = make_url(database_url)
    except (TypeError, ValueError) as exc:
        raise MigrationCliError(
            "migration_database_url_invalid",
            "DATABASE_URL is not a valid PostgreSQL URL",
        ) from exc
    if url.drivername not in {"postgres", "postgresql", "postgresql+asyncpg"} or not url.database:
        raise MigrationCliError(
            "migration_database_url_invalid",
            "DATABASE_URL must identify a PostgreSQL database",
        )
    command = [
        executable,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(output),
    ]
    if url.host:
        command.extend(("--host", url.host))
    if url.port:
        command.extend(("--port", str(url.port)))
    if url.username:
        command.extend(("--username", url.username))
    command.append(url.database)
    environment = dict(base_environment)
    if url.password is not None:
        environment["PGPASSWORD"] = url.password
    return command, environment


def _validate_postgres_backup_archive(path: Path) -> None:
    size_bytes, _digest_value, prefix = _regular_file_metadata(path, prefix_bytes=5)
    if size_bytes < len(_POSTGRES_CUSTOM_ARCHIVE_MAGIC) or prefix != _POSTGRES_CUSTOM_ARCHIVE_MAGIC:
        raise MigrationCliError(
            "migration_database_backup_invalid",
            "database backup is not a PostgreSQL custom archive",
        )
    executable = shutil.which("pg_restore")
    if executable is None:
        raise MigrationCliError(
            "migration_database_backup_tool_unavailable",
            "pg_restore is required to validate retirement recovery evidence",
        )
    try:
        completed = subprocess.run(
            [executable, "--list", str(path)],
            check=False,
            capture_output=True,
            timeout=_BACKUP_VERIFY_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MigrationCliError(
            "migration_database_backup_invalid",
            "database backup validation did not complete",
        ) from exc
    if completed.returncode != 0:
        raise MigrationCliError(
            "migration_database_backup_invalid",
            "pg_restore rejected the retirement database backup",
        )


def _artifact_record(path_obj: Path, *, path: str, media_type: str) -> RetirementPreflightArtifact:
    size_bytes, digest, _prefix = _regular_file_metadata(path_obj)
    return RetirementPreflightArtifact(
        path=path,
        digest=digest,
        size_bytes=size_bytes,
        media_type=media_type,
    )


def _verify_preflight_bundle(
    manifest_path: Path,
    *,
    mapping: object,
) -> _VerifiedRetirementPreflight:
    document = parse_plugin_v1_to_v2_migration_document(mapping)
    manifest = parse_plugin_v1_retirement_preflight_manifest(_load_json(manifest_path))
    if (
        manifest.migration_id != document.migration_id
        or manifest.v1_source_digest != document.source.get("digest")
    ):
        raise MigrationCliError(
            "migration_preflight_binding_mismatch",
            "preflight evidence belongs to another migration source",
        )
    directory = manifest_path.parent
    artifacts = (
        manifest.database_backup,
        manifest.v1_export,
        manifest.last_ready_v2_snapshot,
    )
    for artifact in artifacts:
        _verify_artifact(directory / artifact.path, artifact)
    _validate_postgres_backup_archive(directory / manifest.database_backup.path)
    v1_export = _load_json(directory / manifest.v1_export.path)
    _verify_v1_export(v1_export, mapping=mapping)
    last_ready = _load_json_bounded(
        directory / manifest.last_ready_v2_snapshot.path,
        maximum_bytes=_MAX_RECOVERY_JSON_BYTES,
    )
    last_ready_payload = _verify_last_ready_snapshot(last_ready, manifest=manifest)
    return _VerifiedRetirementPreflight(
        manifest=manifest,
        last_ready_v2_snapshot=last_ready_payload,
    )


async def _verify_persisted_preflight(
    session: AsyncSession,
    verified: _VerifiedRetirementPreflight,
) -> None:
    persisted = await PlatformPluginV1MigrationRepository(session).export_globally_ready_v2(
        nonce=verified.manifest.globally_ready_publication_nonce
    )
    if persisted.to_payload() != verified.last_ready_v2_snapshot:
        raise MigrationCliError(
            "migration_preflight_snapshot_changed",
            "saved globally-ready V2 snapshot differs from persisted recovery evidence",
        )


def _verify_artifact(path: Path, artifact: RetirementPreflightArtifact) -> None:
    size_bytes, digest, _prefix = _regular_file_metadata(path)
    if size_bytes != artifact.size_bytes or digest != artifact.digest:
        raise MigrationCliError(
            "migration_preflight_artifact_changed",
            f"preflight artifact {artifact.path} differs from its manifest",
        )


def _verify_v1_export(payload: object, *, mapping: object) -> None:
    export = _string_object(payload, context="V1 export")
    mapping_object = _string_object(mapping, context="reviewed mapping")
    if set(export) != {"schema_version", "migration_id", "source", "target_heads", "decisions"}:
        raise MigrationCliError(
            "migration_preflight_v1_export_invalid",
            "saved V1 export fields are not exact",
        )
    if (
        export["schema_version"] != 1
        or export["migration_id"] != mapping_object["migration_id"]
        or export["source"] != mapping_object["source"]
        or export["target_heads"] != mapping_object["target_heads"]
    ):
        raise MigrationCliError(
            "migration_preflight_binding_mismatch",
            "saved V1 export differs from the reviewed mapping source or target heads",
        )
    source = _string_object(export["source"], context="V1 export source")
    source_rows = source.get("rows")
    decisions = export["decisions"]
    if not isinstance(source_rows, list) or not isinstance(decisions, list):
        raise MigrationCliError(
            "migration_preflight_v1_export_invalid",
            "saved V1 export rows or decisions are invalid",
        )
    typed_source_rows = cast("list[object]", source_rows)
    expected_decisions = [
        {
            "source_row_id": _string_object(row, context="V1 source row").get("source_row_id"),
            "source_row_digest": _string_object(row, context="V1 source row").get(
                "source_row_digest"
            ),
            "action": None,
            "target_bundle": None,
            "judgment": None,
        }
        for row in typed_source_rows
    ]
    if decisions != expected_decisions:
        raise MigrationCliError(
            "migration_preflight_v1_export_invalid",
            "saved V1 export is not the original incomplete mapping template",
        )


def _verify_last_ready_snapshot(
    payload: object,
    *,
    manifest: PluginProtocolV1RetirementPreflightManifest,
) -> dict[str, object]:
    snapshot = _string_object(payload, context="last globally-ready V2 snapshot")
    expected_fields = {
        "schema_version",
        "kind",
        "publication_id",
        "profile_id",
        "generation",
        "snapshot_digest",
        "requested_version",
        "nonce",
        "type_url",
        "required_data_plane_ids",
        "globally_ready_at",
        "distribution",
        "digest",
    }
    if set(snapshot) != expected_fields:
        raise MigrationCliError(
            "migration_preflight_snapshot_invalid",
            "last globally-ready V2 snapshot fields are not exact",
        )
    unsigned = {key: value for key, value in snapshot.items() if key != "digest"}
    if snapshot["digest"] != digest_payload_v1_to_v2(unsigned):
        raise MigrationCliError(
            "migration_preflight_snapshot_invalid",
            "last globally-ready V2 snapshot digest is invalid",
        )
    if (
        snapshot["schema_version"] != 2
        or snapshot["kind"] != "globally_ready_plugin_publication_v2"
        or snapshot["nonce"] != manifest.globally_ready_publication_nonce
        or snapshot["requested_version"] != manifest.globally_ready_requested_version
        or snapshot["snapshot_digest"] != manifest.globally_ready_snapshot_digest
    ):
        raise MigrationCliError(
            "migration_preflight_binding_mismatch",
            "last globally-ready V2 snapshot differs from the preflight manifest",
        )
    return snapshot


def _conversion_audit_payload(
    *,
    result: dict[str, object],
    preflight: PluginProtocolV1RetirementPreflightManifest,
) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "schema_version": 1,
        "kind": "plugin_protocol_v1_to_v2_retirement_audit",
        "migration_id": preflight.migration_id,
        "preflight_manifest_digest": preflight.manifest_digest,
        "database_backup_digest": preflight.database_backup.digest,
        "v1_export_digest": preflight.v1_export.digest,
        "last_ready_v2_snapshot_digest": preflight.last_ready_v2_snapshot.digest,
        "conversion": dict(result),
    }
    return {**unsigned, "audit_digest": digest_payload_v1_to_v2(unsigned)}


def _v1_source_digest(payload: object) -> str:
    export = _string_object(payload, context="V1 export")
    source = _string_object(export.get("source"), context="V1 export source")
    digest = source.get("digest")
    if not isinstance(digest, str):
        raise MigrationCliError(
            "migration_preflight_v1_export_invalid",
            "V1 export source has no digest",
        )
    return digest


def _regular_file_metadata(
    path: Path,
    *,
    prefix_bytes: int = 0,
) -> tuple[int, str, bytes]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise MigrationCliError(
            "migration_preflight_artifact_unreadable",
            f"preflight artifact {path.name} is unavailable",
        ) from exc
    digest = hashlib.sha256()
    prefix = b""
    try:
        with os.fdopen(descriptor, "rb") as stream:
            file_stat = os.fstat(stream.fileno())
            if not stat.S_ISREG(file_stat.st_mode):
                raise MigrationCliError(
                    "migration_preflight_artifact_invalid",
                    f"preflight artifact {path.name} is not a regular file",
                )
            while chunk := stream.read(1024 * 1024):
                if len(prefix) < prefix_bytes:
                    prefix += chunk[: prefix_bytes - len(prefix)]
                digest.update(chunk)
    except Exception:
        with suppress(OSError):
            os.close(descriptor)
        raise
    return file_stat.st_size, f"sha256:{digest.hexdigest()}", prefix


def _string_object(payload: object, *, context: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise MigrationCliError(
            "migration_preflight_artifact_invalid",
            f"{context} must be an object with string fields",
        )
    raw = cast("dict[object, object]", payload)
    if not all(isinstance(key, str) for key in raw):
        raise MigrationCliError(
            "migration_preflight_artifact_invalid",
            f"{context} must be an object with string fields",
        )
    return cast("dict[str, object]", raw)


def _load_json(path: Path) -> object:
    return _load_json_bounded(path, maximum_bytes=_MAX_MAPPING_BYTES)


def _load_json_bounded(path: Path, *, maximum_bytes: int) -> object:
    try:
        if path.is_symlink():
            raise OSError("symbolic links are not accepted")
        size = path.stat().st_size
    except OSError as exc:
        raise MigrationCliError(
            "migration_mapping_unreadable", "mapping file is unavailable"
        ) from exc
    if size > maximum_bytes:
        raise MigrationCliError(
            "migration_mapping_too_large",
            f"JSON input exceeds {maximum_bytes} bytes",
        )

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise MigrationCliError(
                    "migration_mapping_duplicate_key",
                    "mapping JSON contains a duplicate object key",
                )
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except MigrationCliError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationCliError(
            "migration_mapping_invalid_json", "mapping file is not valid JSON"
        ) from exc


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise MigrationCliError(
            "migration_output_exists",
            "output already exists; choose a new audit path",
        ) from exc
    except OSError as exc:
        raise MigrationCliError(
            "migration_output_unwritable", "output path is not writable"
        ) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            _ = output.write(content)
    except Exception:
        with suppress(OSError):
            path.unlink(missing_ok=True)
        raise


def _error_payload(error: Exception) -> dict[str, str]:
    code = getattr(error, "code", "plugin_v1_to_v2_migration_failed")
    return {"status": "error", "code": str(code), "message": str(error)}


def main() -> NoReturn:
    args = _parser().parse_args()
    try:
        exit_code = asyncio.run(_run(args))
    except (
        MigrationCliError,
        PlatformPluginV1MigrationRepositoryError,
        PluginProtocolV1RetirementPreflightError,
        PluginProtocolV1ToV2MigrationError,
    ) as exc:
        _ = sys.stderr.write(json.dumps(_error_payload(exc), sort_keys=True) + "\n")
        raise SystemExit(1) from exc
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
