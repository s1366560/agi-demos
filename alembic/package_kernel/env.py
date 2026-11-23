"""Separate PostgreSQL migration history for a fresh standalone package host."""

import asyncio

from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import context
from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.package_kernel_database import (
    VERSION_TABLE,
    lock_and_check_standalone,
    package_kernel_metadata,
)


def migrate(connection: Connection) -> None:
    metadata = package_kernel_metadata()
    context.configure(
        connection=connection,
        target_metadata=metadata,
        # Third-party tables and their revision histories remain package-owned.
        include_name=lambda name, kind, _parents: kind != "table" or name in metadata.tables,
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        lock_and_check_standalone(connection)
        context.run_migrations()


async def migrate_configured_database() -> None:
    settings = get_settings()
    if settings.package_kernel_database_mode != "standalone":
        raise RuntimeError("Standalone migrations require PACKAGE_KERNEL_DATABASE_MODE=standalone")
    engine = create_async_engine(settings.postgres_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Standalone migrations require an online database ownership check")
if (supplied := context.config.attributes.get("connection")) is not None:
    migrate(supplied)
else:
    asyncio.run(migrate_configured_database())
