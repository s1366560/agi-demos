"""Run package migrations before exposing the billing provider on the API data plane."""

from collections.abc import Callable
from pathlib import Path

from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command


def _upgrade(connection: Connection) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


async def migrate_invoices(sessions: Callable[[], AsyncSession]) -> None:
    async with sessions() as session:
        transaction = session.begin_nested() if session.in_transaction() else session.begin()
        async with transaction:
            connection = await session.connection()
            if connection.dialect.name == "postgresql":
                await connection.execute(text("SELECT pg_advisory_xact_lock(1947362821, 2)"))
            await connection.run_sync(_upgrade)
