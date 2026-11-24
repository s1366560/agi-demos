"""The SQL footprint of a standalone signed-package host and its migration entry point."""

from pathlib import Path
from typing import cast

from alembic.config import Config
from sqlalchemy import MetaData, Table, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command
from src.infrastructure.adapters.secondary.persistence.device_plugin_grant_model import (
    DevicePluginGrant,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentLocalRunEventModel,
    AgentPlanRunModel,
    AgentPlanVersionModel,
    AgentRunAuthorityModel,
    APIKey,
    Conversation,
    DesktopWorkspaceContext,
    DesktopWorkspaceContextEvent,
    Permission,
    PlatformPluginPackageModel,
    Project,
    Role,
    RolePermission,
    Tenant,
    User,
    UserProject,
    UserRole,
    UserSession,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_namespace_model_v2 import (
    PlatformPluginNamespaceRecordModelV2,
)
from src.infrastructure.adapters.secondary.persistence.project_plugin_installation import (
    ProjectPluginInstallation,
    ProjectPluginRelease,
)
from src.infrastructure.adapters.secondary.persistence.tenant_plugin_installation import (
    TenantPluginInstallation,
    TenantPluginRelease,
)

VERSION_TABLE = "package_kernel_alembic_version"


def package_kernel_metadata() -> MetaData:
    """Autogenerate only schema used by cloud identity and signed package operations."""
    result = MetaData()
    for model in (
        User,
        Tenant,
        Project,
        UserTenant,
        UserProject,
        APIKey,
        UserSession,
        DesktopWorkspaceContext,
        DesktopWorkspaceContextEvent,
        Role,
        Permission,
        RolePermission,
        UserRole,
        PlatformPluginPackageModel,
        ProjectPluginInstallation,
        ProjectPluginRelease,
        TenantPluginInstallation,
        TenantPluginRelease,
        PlatformPluginNamespaceRecordModelV2,
        DevicePluginGrant,
        Conversation,
        AgentPlanVersionModel,
        AgentPlanRunModel,
        AgentRunAuthorityModel,
        AgentLocalRunEventModel,
        AgentExecutionEvent,
    ):
        _ = cast("Table", model.__table__).to_metadata(result)
    return result


def lock_and_check_standalone(connection: Connection) -> None:
    # Serialize both lineages before reading their stamps, including the first startup.
    _ = connection.execute(text("SELECT pg_advisory_xact_lock(1947362821, 1)"))
    relations = connection.execute(
        text(
            """
            SELECT c.relname, n.nspname = current_schema() AS local
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
              AND c.relkind IN ('r', 'p', 'm', 'v', 'S', 'f')
            """
        )
    ).all()
    if any(name == "alembic_version" for name, _ in relations):
        raise RuntimeError("A full MemStack database cannot use the standalone package schema")
    owns_schema = any(name == VERSION_TABLE and local for name, local in relations)
    if relations and not owns_schema:
        raise RuntimeError("A new standalone package host requires an empty dedicated database")


def migration_config(connection: Connection) -> Config:
    root = Path(__file__).resolve().parents[5]
    config = Config()
    config.set_main_option("script_location", str(root / "alembic" / "package_kernel"))
    config.attributes["connection"] = connection
    return config


async def initialize_package_kernel_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        # Hold the database lock before entering Alembic's environment, including
        # overlapping startup attempts sharing one Python interpreter.
        _ = await connection.execute(text("SELECT pg_advisory_xact_lock(1947362821, 1)"))
        await connection.run_sync(lambda sync: command.upgrade(migration_config(sync), "head"))
