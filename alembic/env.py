"""
Alembic migration environment for MemStack.

This module configures Alembic for async SQLAlchemy with:
- Dynamic database URL from environment variables
- Async migration support using asyncpg
- Proper metadata binding for autogenerate
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.sql.schema import SchemaItem

# Import models to ensure they're registered with Base.metadata
# This must happen before accessing Base.metadata
import src.infrastructure.adapters.secondary.persistence.artifact_model
import src.infrastructure.adapters.secondary.persistence.attachment_model
import src.infrastructure.adapters.secondary.persistence.automation_permission_models
import src.infrastructure.adapters.secondary.persistence.channel_models
import src.infrastructure.adapters.secondary.persistence.device_plugin_grant_model
import src.infrastructure.adapters.secondary.persistence.graph_projection_job_model
import src.infrastructure.adapters.secondary.persistence.knowledge_sync_models
import src.infrastructure.adapters.secondary.persistence.legacy_cron_admission_model
import src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_model_v2
import src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3
import src.infrastructure.adapters.secondary.persistence.project_plugin_installation
import src.infrastructure.adapters.secondary.persistence.project_schema_models
import src.infrastructure.adapters.secondary.persistence.subagent_owner_model_v2
import src.infrastructure.adapters.secondary.persistence.subagent_run_snapshot_model_v2  # noqa: F401
import src.infrastructure.adapters.secondary.persistence.tenant_plugin_installation
from alembic import context

# Import settings to get database URL
from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

# Embedded startup migrates the database selected by its engine. The standalone
# Alembic CLI uses the repository's configured dotenv source.
settings = get_settings()
database_url = make_url(config.attributes.get("database_url") or settings.postgres_url)
config.set_main_option(
    "sqlalchemy.url", database_url.render_as_string(hide_password=False).replace("%", "%%")
)

# add your model's MetaData object here for 'autogenerate' support
target_metadata = Base.metadata


def include_host_schema(
    obj: SchemaItem, name: str | None, kind: str, reflected: bool, compare_to: SchemaItem | None
) -> bool:
    """Leave tables under independent package revision histories to their owners."""
    if kind != "table":
        return True
    if name in {"billing_alembic_version", "invoices"}:
        return False
    return not obj.info.get("package_migrations")


def default_admin_promotion_options() -> dict[str, str | None]:
    """Pass only explicit nonsecret development account selection to the data migration."""
    arguments = context.get_x_argument(as_dictionary=True)
    return {
        "user_id": arguments.get("development_admin_user_id"),
        "email": arguments.get("development_admin_email"),
        "environment": settings.environment,
        "database_host": database_url.host,
    }


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_object=include_host_schema,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        development_admin_promotion=default_admin_promotion_options(),
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations using the provided connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_host_schema,
        development_admin_promotion=default_admin_promotion_options(),
    )

    with context.begin_transaction():
        # API workers and CLI migrations share this database-scoped transaction
        # lock. Acquire it before reading the version or executing any DDL.
        connection.execute(text("SELECT pg_advisory_xact_lock(1947362821, 1)"))
        if connection.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON c.relnamespace=n.oid "
                "WHERE c.relname='package_kernel_alembic_version' AND c.relkind='r' "
                "AND n.nspname !~ '^pg_' AND n.nspname <> 'information_schema')"
            )
        ):
            raise RuntimeError("A standalone package database cannot use the full MemStack schema")
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using async engine.

    In this scenario we need to create an async Engine
    and associate a connection with the context.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
