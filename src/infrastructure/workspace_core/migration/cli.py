"""Command-line interface for the offline Avernet Workspace migration."""

# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import asyncpg
from sqlalchemy.engine import make_url

from src.configuration.config import get_settings

from .model import MigrationCommand, MigrationScope
from .service import WorkspaceMigrationService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate and verify legacy Workspace data in the Avernet schema."
    )
    _ = parser.add_argument(
        "--database-url",
        help="PostgreSQL URL; defaults to the repository DATABASE_URL configuration",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in MigrationCommand:
        command_parser = subparsers.add_parser(command.value)
        _ = command_parser.add_argument("--run-id", required=True)
        _ = command_parser.add_argument("--tenant-id")
        _ = command_parser.add_argument("--project-id")
        _ = command_parser.add_argument("--workspace-id")
        if command is MigrationCommand.REVERSE_EXPORT:
            _ = command_parser.add_argument("--output", type=Path, required=True)
            _ = command_parser.add_argument("--force", action="store_true")
    return parser


def _asyncpg_url(raw_url: str) -> str:
    url = make_url(raw_url)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("Workspace migration requires a PostgreSQL database URL")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


async def _run(args: argparse.Namespace) -> int:
    configured_url = args.database_url or get_settings().postgres_url
    connection = await asyncpg.connect(_asyncpg_url(configured_url))
    try:
        service = WorkspaceMigrationService(connection)
        report = await service.run(
            MigrationCommand(args.command),
            migration_run_id=args.run_id,
            scope=MigrationScope(
                tenant_id=args.tenant_id,
                project_id=args.project_id,
                workspace_id=args.workspace_id,
            ),
            output_path=getattr(args, "output", None),
            force=bool(getattr(args, "force", False)),
        )
    finally:
        await connection.close()
    print(report.to_json())
    return 0 if report.ok else 2


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and execute the selected migration operation."""

    args = build_parser().parse_args(argv)
    return asyncio.run(_run(args))
