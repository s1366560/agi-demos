#!/usr/bin/env python3
"""Export, plan, and atomically apply the one-shot plugin V1 desired-state conversion."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from src.application.services.plugin_protocol_v1_to_v2_migration_contract import (
    PluginProtocolV1ToV2MigrationError,
    parse_plugin_v1_to_v2_migration_document,
)
from src.application.services.plugin_protocol_v1_to_v2_migration_service import (
    PluginProtocolV1ToV2MigrationService,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_v1_migration_repository import (
    PlatformPluginV1MigrationRepository,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_MAX_MAPPING_BYTES = 2 * 1024 * 1024


class MigrationCliError(ValueError):
    """Safe operator-facing CLI contract failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot offline conversion from frozen plugin protocol V1 desired rows to V2"
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="Export a secret-free mapping template")
    _ = export.add_argument("--migration-id", required=True)
    _ = export.add_argument("--output", required=True, type=Path)

    plan = commands.add_parser("plan", help="Validate a completed mapping without writes")
    _ = plan.add_argument("--mapping", required=True, type=Path)
    _ = plan.add_argument("--output", required=True, type=Path)

    apply = commands.add_parser("apply", help="Atomically append V2 heads and audit evidence")
    _ = apply.add_argument("--mapping", required=True, type=Path)
    _ = apply.add_argument("--actor-id", required=True)
    _ = apply.add_argument(
        "--confirm-migration-id",
        required=True,
        help="Must exactly match migration_id inside the reviewed mapping",
    )
    _ = apply.add_argument("--output", required=True, type=Path)
    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.command == "export":
        async with async_session_factory() as session:
            payload = await _service(session).export_template(migration_id=args.migration_id)
        _write_json(args.output, payload)
        return 0

    mapping = _load_json(args.mapping)
    if args.command == "plan":
        async with async_session_factory() as session:
            plan = await _service(session).plan(mapping)
        _write_json(args.output, plan.to_payload())
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
        result = await _service(session).execute(mapping, actor_id=args.actor_id)
    _write_json(args.output, result.report)
    return 0


def _service(session: AsyncSession) -> PluginProtocolV1ToV2MigrationService:
    return PluginProtocolV1ToV2MigrationService(
        migration_repository=PlatformPluginV1MigrationRepository(session),
        desired_repository=PlatformPluginDesiredBundleSetRepositoryV2(session),
        governance_repository=PlatformPluginGovernanceRepository(session),
        production_sources=production_bundle_sources_v2(),
    )


def _load_json(path: Path) -> object:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise MigrationCliError(
            "migration_mapping_unreadable", "mapping file is unavailable"
        ) from exc
    if size > _MAX_MAPPING_BYTES:
        raise MigrationCliError("migration_mapping_too_large", "mapping file exceeds 2 MiB")

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
    except (MigrationCliError, PluginProtocolV1ToV2MigrationError) as exc:
        _ = sys.stderr.write(json.dumps(_error_payload(exc), sort_keys=True) + "\n")
        raise SystemExit(1) from exc
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
