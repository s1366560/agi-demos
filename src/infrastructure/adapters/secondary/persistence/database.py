import asyncio
import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.relational_store import (
    RelationalStoreSpec,
    bootstrap_sqlite_relational_schema,
    open_relational_store,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# The process driver is PostgreSQL in the cloud and embedded SQLite for a
# desktop or local host. Plugins use the session factory, not this choice.
_relational_store = open_relational_store(settings)
relational_store: RelationalStoreSpec = _relational_store.spec
engine = _relational_store.engine
async_session_factory = _relational_store.session_factory
read_engine: AsyncEngine | None = _relational_store.read_engine
read_session_factory = _relational_store.read_session_factory


async def get_db() -> AsyncGenerator[Any, None]:
    """
    Dependency that provides a database session for write operations.

    Uses the primary database. For read-heavy operations, consider using
    get_read_db() if a read replica is configured.

    Note: Using manual session management instead of 'async with' to allow
    for explicit commit control within endpoints. The caller is responsible
    for committing changes when needed.
    """
    session = async_session_factory()
    try:
        yield session
    finally:
        await session.close()


async def get_read_db() -> AsyncGenerator[Any, None]:
    """
    Dependency that provides a database session for read operations.

    Uses the read replica if configured, otherwise falls back to the primary.
    Use this for SELECT queries to distribute read load.
    """
    if read_session_factory is not None:
        session = read_session_factory()
    else:
        session = async_session_factory()
    try:
        yield session
    finally:
        await session.close()


def _dialect_name(target: AsyncEngine) -> str | None:
    name = getattr(getattr(target, "dialect", None), "name", None)
    return name if isinstance(name, str) else None


async def initialize_database(target: AsyncEngine | None = None) -> None:
    """Apply the schema for the selected relational driver.

    PostgreSQL keeps the Alembic history. SQLite materializes the ORM schema
    and the billing package migration without opening PostgreSQL.
    """
    active = target if target is not None else engine
    if _dialect_name(active) == "sqlite":
        logger.info("Applying embedded sqlite relational schema")
        await bootstrap_sqlite_relational_schema(active)
        logger.info("Embedded sqlite relational schema ready")
        return

    from alembic.config import Config

    from alembic import command

    project_root = Path(__file__).resolve().parents[5]
    alembic_cfg = Config(str(project_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(project_root / "alembic"))
    logger.info("Applying database migrations...")
    # Alembic owns its async event loop. Run it outside the application's loop and
    # propagate migration failures so startup cannot report an incomplete schema.
    # Embedded migrations must not disable the application's already configured loggers.
    alembic_cfg.attributes["configure_logger"] = False
    alembic_cfg.attributes["database_url"] = active.url
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    logger.info("Database migrations completed successfully")


async def update_agent_events_schema() -> None:
    """
    Update agent_execution_events table with indexes and constraints.

    This function ensures that the indexes and unique constraints defined
    in the AgentExecutionEvent model are applied to the database.

    This should be called once during deployment for existing databases.
    """

    from src.infrastructure.adapters.secondary.persistence.models import (
        AGENT_EXECUTION_EVENT_CORRELATION_ID_LENGTH,
    )

    if _dialect_name(engine) == "sqlite":
        logger.info("Skipping PostgreSQL agent event repair on the sqlite relational store")
        return

    logger.info("Updating agent_execution_events schema...")

    async with engine.begin() as conn:
        # Keep correlation IDs wide enough for prefixed UUIDs such as "cron:<uuid>".
        try:
            await conn.execute(
                refresh_select_statement(
                    text(
                        "ALTER TABLE agent_execution_events "
                        "ALTER COLUMN correlation_id "
                        f"TYPE VARCHAR({AGENT_EXECUTION_EVENT_CORRELATION_ID_LENGTH})"
                    )
                )
            )
            logger.info("Widened agent_execution_events.correlation_id")
        except Exception as e:
            logger.info(f"correlation_id column may already be updated: {e}")

        # Create unique constraint on (conversation_id, event_time_us, event_counter).
        # PostgreSQL does not support ``ADD CONSTRAINT IF NOT EXISTS``; check first
        # so startup schema repair does not poison the surrounding transaction.
        try:
            existing_constraint = await conn.execute(
                refresh_select_statement(
                    text(
                        "SELECT 1 FROM pg_constraint "
                        "WHERE conname = 'uq_agent_events_conv_time' "
                        "AND conrelid = 'agent_execution_events'::regclass"
                    )
                )
            )
            if existing_constraint.scalar_one_or_none() is None:
                await conn.execute(
                    refresh_select_statement(
                        text(
                            "ALTER TABLE agent_execution_events "
                            "ADD CONSTRAINT uq_agent_events_conv_time "
                            "UNIQUE (conversation_id, event_time_us, event_counter)"
                        )
                    )
                )
                logger.info("Added unique constraint uq_agent_events_conv_time")
            else:
                logger.info("Unique constraint uq_agent_events_conv_time already exists")
        except Exception as e:
            logger.info(f"Unique constraint may already exist: {e}")

        # Create index on (conversation_id, event_time_us, event_counter)
        try:
            await conn.execute(
                refresh_select_statement(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_agent_events_conv_time "
                        "ON agent_execution_events (conversation_id, event_time_us, event_counter)"
                    )
                )
            )
            logger.info("Created index ix_agent_events_conv_time")
        except Exception as e:
            logger.info(f"Index may already exist: {e}")

        # Create index on (message_id, event_time_us, event_counter)
        try:
            await conn.execute(
                refresh_select_statement(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_agent_events_msg_time "
                        "ON agent_execution_events (message_id, event_time_us, event_counter)"
                    )
                )
            )
            logger.info("Created index ix_agent_events_msg_time")
        except Exception as e:
            logger.info(f"Index may already exist: {e}")

        # Create index on correlation_id for request-scoped event lookups.
        try:
            await conn.execute(
                refresh_select_statement(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_agent_events_corr_id "
                        "ON agent_execution_events (correlation_id)"
                    )
                )
            )
            logger.info("Created index ix_agent_events_corr_id")
        except Exception as e:
            logger.info(f"Index may already exist: {e}")

    logger.info("✅ agent_execution_events schema updated")


async def migrate_messages_to_events() -> None:
    """
    Migrate messages table data to agent_execution_events table.

    This migration:
    1. Migrates existing messages to user_message/assistant_message events
    2. Removes foreign key constraints referencing messages table
    3. Drops the messages table
    4. Creates optimized indexes for message event queries

    Run this ONCE during deployment to complete the unified event timeline migration.
    """
    logger.info("🔄 Starting messages to events migration...")

    async with engine.begin() as conn:
        # Step 1: Check if messages table exists
        result = await conn.execute(
            refresh_select_statement(
                text(
                    "SELECT EXISTS ("
                    "SELECT FROM information_schema.tables "
                    "WHERE table_name = 'messages'"
                    ")"
                )
            )
        )
        table_exists = result.scalar()

        if not table_exists:
            logger.info("ℹ️  Messages table does not exist, skipping migration")
            return

        # Step 2: Migrate messages to events
        logger.info("📦 Migrating messages to events...")
        migration_result = await conn.execute(
            refresh_select_statement(
                text(
                    """
                INSERT INTO agent_execution_events (
                    id, conversation_id, message_id, event_type, event_data, 
                    event_time_us, event_counter, created_at
                )
                SELECT 
                    gen_random_uuid()::text as id,
                    conversation_id,
                    id as message_id,
                    CASE 
                        WHEN role = 'user' THEN 'user_message'
                        ELSE 'assistant_message'
                    END as event_type,
                    jsonb_build_object(
                        'content', content,
                        'message_id', id,
                        'role', role
                    ) as event_data,
                    -- Convert created_at to microsecond timestamp
                    EXTRACT(EPOCH FROM created_at)::bigint * 1000000 as event_time_us,
                    -- Use ROW_NUMBER within same timestamp as counter
                    ROW_NUMBER() OVER (
                        PARTITION BY conversation_id 
                        ORDER BY created_at ASC
                    ) as event_counter,
                    created_at
                FROM messages 
                WHERE role IN ('user', 'assistant')
                ON CONFLICT (conversation_id, event_time_us, event_counter) DO NOTHING
                """
                )
            )
        )
        logger.info(f"✅ Migrated {migration_result.rowcount} messages to events")

        # Step 3: Drop foreign key constraints
        logger.info("🔗 Removing foreign key constraints...")

        # List of (table_name, constraint_name) tuples
        fk_constraints = [
            ("agent_executions", "agent_executions_message_id_fkey"),
            ("tool_execution_records", "tool_execution_records_message_id_fkey"),
            ("agent_execution_events", "agent_execution_events_message_id_fkey"),
            ("execution_checkpoints", "execution_checkpoints_message_id_fkey"),
        ]

        for table_name, constraint_name in fk_constraints:
            try:
                await conn.execute(
                    refresh_select_statement(
                        text(
                            f"ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS {constraint_name}"
                        )
                    )
                )
                logger.info(f"  ✅ Dropped constraint {constraint_name}")
            except Exception as e:
                logger.warning(f"  ⚠️  Could not drop {constraint_name}: {e}")

        # Step 4: Drop messages table
        logger.info("🗑️  Dropping messages table...")
        try:
            await conn.execute(
                refresh_select_statement(text("DROP TABLE IF EXISTS messages CASCADE"))
            )
            logger.info("✅ Dropped messages table")
        except Exception as e:
            logger.error(f"❌ Failed to drop messages table: {e}")
            raise

        # Step 5: Create optimized index for message event queries
        logger.info("📇 Creating optimized indexes...")
        try:
            await conn.execute(
                refresh_select_statement(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_agent_events_conv_type_time "
                        "ON agent_execution_events (conversation_id, event_type, event_time_us)"
                    )
                )
            )
            logger.info("Created index ix_agent_events_conv_type_time")
        except Exception as e:
            logger.warning(f"⚠️  Index may already exist: {e}")

    logger.info("✅ Messages to events migration completed!")


async def check_messages_table_exists() -> bool:
    """Check if messages table still exists in the database."""
    async with engine.begin() as conn:
        result = await conn.execute(
            refresh_select_statement(
                text(
                    "SELECT EXISTS ("
                    "SELECT FROM information_schema.tables "
                    "WHERE table_name = 'messages'"
                    ")"
                )
            )
        )
        return bool(result.scalar())


async def migrate_skills_multi_tenant() -> None:
    """
    Migrate skills table to support three-level scoping (system/tenant/project).

    This migration:
    1. Adds 'scope' column with default 'tenant'
    2. Adds 'is_system_skill' boolean column
    3. Adds 'full_content' text column for SKILL.md content
    4. Creates tenant_skill_configs table for controlling system skills
    5. Creates necessary indexes

    Run this ONCE during deployment to enable multi-tenant skill isolation.
    """
    logger.info("🔄 Starting skills multi-tenant migration...")

    async with engine.begin() as conn:
        # Step 1: Check if scope column already exists
        result = await conn.execute(
            refresh_select_statement(
                text(
                    "SELECT EXISTS ("
                    "SELECT FROM information_schema.columns "
                    "WHERE table_name = 'skills' AND column_name = 'scope'"
                    ")"
                )
            )
        )
        scope_exists = result.scalar()

        if scope_exists:
            logger.info("ℹ️  Skills scope column already exists, skipping column migration")
        else:
            # Add scope column
            logger.info("📦 Adding scope column to skills table...")
            await conn.execute(
                refresh_select_statement(
                    text(
                        "ALTER TABLE skills ADD COLUMN scope VARCHAR(20) DEFAULT 'tenant' NOT NULL"
                    )
                )
            )
            logger.info("✅ Added scope column")

            # Add is_system_skill column
            await conn.execute(
                refresh_select_statement(
                    text(
                        "ALTER TABLE skills ADD COLUMN is_system_skill BOOLEAN DEFAULT FALSE NOT NULL"
                    )
                )
            )
            logger.info("✅ Added is_system_skill column")

            # Add full_content column
            await conn.execute(
                refresh_select_statement(
                    text("ALTER TABLE skills ADD COLUMN full_content TEXT NULL")
                )
            )
            logger.info("✅ Added full_content column")

            # Create index on scope
            await conn.execute(
                refresh_select_statement(
                    text("CREATE INDEX IF NOT EXISTS ix_skills_scope ON skills(scope)")
                )
            )
            logger.info("✅ Created index ix_skills_scope")

            # Create composite index
            await conn.execute(
                refresh_select_statement(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_skills_tenant_scope ON skills(tenant_id, scope)"
                    )
                )
            )
            logger.info("✅ Created index ix_skills_tenant_scope")

        # Step 2: Create tenant_skill_configs table if not exists
        result = await conn.execute(
            refresh_select_statement(
                text(
                    "SELECT EXISTS ("
                    "SELECT FROM information_schema.tables "
                    "WHERE table_name = 'tenant_skill_configs'"
                    ")"
                )
            )
        )
        config_table_exists = result.scalar()

        if config_table_exists:
            logger.info("ℹ️  tenant_skill_configs table already exists")
        else:
            logger.info("📦 Creating tenant_skill_configs table...")
            await conn.execute(
                refresh_select_statement(
                    text(
                        """
                    CREATE TABLE tenant_skill_configs (
                        id VARCHAR PRIMARY KEY,
                        tenant_id VARCHAR NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                        system_skill_name VARCHAR(200) NOT NULL,
                        action VARCHAR(20) NOT NULL,
                        override_skill_id VARCHAR REFERENCES skills(id) ON DELETE SET NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        CONSTRAINT uq_tenant_skill_config UNIQUE(tenant_id, system_skill_name)
                    )
                    """
                    )
                )
            )
            logger.info("✅ Created tenant_skill_configs table")

            # Create index
            await conn.execute(
                refresh_select_statement(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_tenant_skill_configs_tenant "
                        "ON tenant_skill_configs(tenant_id)"
                    )
                )
            )
            logger.info("✅ Created index ix_tenant_skill_configs_tenant")

    logger.info("✅ Skills multi-tenant migration completed!")
