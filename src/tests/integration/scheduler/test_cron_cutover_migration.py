"""The additive barrier defaults to unknown and cannot be erased while prepared."""

import uuid

import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from src.configuration.config import get_settings

pytestmark = pytest.mark.integration
migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("7c90e5134285").module


@pytest_asyncio.fixture(loop_scope="function")
async def migration_database():
    schema = f"qa_cron_cutover_migration_{uuid.uuid4().hex}"
    url = get_settings().postgres_url
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("""
                CREATE TABLE agistack_cron_scheduler_owners (
                    scope_id text PRIMARY KEY, owner_kind text NOT NULL, lease_token text
                )
            """)
            )
            await connection.execute(
                text("INSERT INTO agistack_cron_scheduler_owners VALUES ('global', 'python', NULL)")
            )
        yield engine
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()


def upgrade(connection):
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()


def downgrade(connection):
    with Operations.context(MigrationContext.configure(connection)):
        migration.downgrade()


async def test_upgrade_preserves_owner_and_starts_unverified(migration_database):
    async with migration_database.begin() as connection:
        await connection.run_sync(upgrade)
        row = (
            await connection.execute(
                text(
                    "SELECT owner_kind, cutover_phase, cutover_revision, cutover_evidence "
                    "FROM agistack_cron_scheduler_owners"
                )
            )
        ).one()
        assert tuple(row) == ("python", "unverified", 0, {})
        await connection.run_sync(downgrade)
        assert (
            await connection.execute(text("SELECT owner_kind FROM agistack_cron_scheduler_owners"))
        ).scalar_one() == "python"


async def test_downgrade_refuses_to_drop_prepared_evidence(migration_database):
    async with migration_database.begin() as connection:
        await connection.run_sync(upgrade)
        await connection.execute(
            text(
                "UPDATE agistack_cron_scheduler_owners SET owner_kind='draining', "
                "cutover_phase='prepared', cutover_revision=1, cutover_evidence='{}'"
            )
        )
    with pytest.raises(DBAPIError, match="Cannot remove a prepared"):
        async with migration_database.begin() as connection:
            await connection.run_sync(downgrade)
    async with migration_database.begin() as connection:
        row = (
            await connection.execute(
                text("SELECT owner_kind, cutover_phase FROM agistack_cron_scheduler_owners")
            )
        ).one()
        assert tuple(row) == ("draining", "prepared")
