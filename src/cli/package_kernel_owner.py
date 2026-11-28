"""Explicitly provision the first project owner of a standalone package database."""

import argparse
import asyncio
import getpass
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.host.identity.initial_owner import create_initial_owner
from src.infrastructure.adapters.secondary.persistence.models import (
    User,
)
from src.infrastructure.adapters.secondary.persistence.package_kernel_database import (
    VERSION_TABLE,
    lock_and_check_standalone,
)


async def provision_owner(
    engine: AsyncEngine, *, email: str, password: str, tenant_name: str, project_name: str
) -> tuple[str, str]:
    async with engine.begin() as connection:
        await connection.run_sync(lock_and_check_standalone)
        if not await connection.scalar(text("SELECT to_regclass(:name)"), {"name": VERSION_TABLE}):
            raise RuntimeError("Initialize the standalone database before provisioning its owner")
        async with AsyncSession(bind=connection, expire_on_commit=False) as db:
            if await db.scalar(select(User.id).limit(1)) is not None:
                raise RuntimeError("An identity already exists; first-owner provisioning is closed")
            _, tenant, project = await create_initial_owner(
                db,
                email=email,
                password=password,
                tenant_name=tenant_name,
                project_name=project_name,
            )
            await db.commit()
            return tenant, project


async def _run(args: argparse.Namespace) -> None:
    from src.configuration.config import get_settings
    from src.infrastructure.adapters.secondary.persistence.database import engine

    if get_settings().package_kernel_database_mode != "standalone":
        raise RuntimeError("Provisioning requires PACKAGE_KERNEL_DATABASE_MODE=standalone")
    password = (
        args.password_file.read_text().rstrip("\r\n")
        if args.password_file is not None
        else getpass.getpass("Project owner password: ")
    )
    try:
        tenant, project = await provision_owner(
            engine,
            email=args.email,
            password=password,
            tenant_name=args.tenant,
            project_name=args.project,
        )
    finally:
        await engine.dispose()
    print(f"Project owner provisioned. Tenant {tenant}, project {project}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--email", required=True)
    _ = parser.add_argument("--tenant", required=True, help="Tenant display name")
    _ = parser.add_argument("--project", required=True, help="Project display name")
    _ = parser.add_argument(
        "--password-file", type=Path, help="Mounted secret, defaults to a hidden prompt"
    )
    try:
        asyncio.run(_run(parser.parse_args()))
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
