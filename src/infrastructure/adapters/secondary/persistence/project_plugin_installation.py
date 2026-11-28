"""Project-scoped signed packages and their independently selected versions."""

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    SQLColumnExpression,
    String,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.model.plugins.chat_adapter_scope import chat_adapter_providers
from src.infrastructure.adapters.secondary.persistence.models import Base


class ProjectPluginRelease(Base):
    __tablename__ = "project_plugin_releases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "tenant_id"], ["projects.id", "projects.tenant_id"], ondelete="CASCADE"
        ),
    )
    project_id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String)
    plugin_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    digest: Mapped[str] = mapped_column(String(71))
    archive: Mapped[bytes] = mapped_column(LargeBinary)
    permissions: Mapped[list[str]] = mapped_column(JSON)
    approved_by: Mapped[str] = mapped_column(String)


class ProjectPluginInstallation(Base):
    __tablename__ = "project_plugin_installations"
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    plugin_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    desired: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[str | None] = mapped_column(String(64))
    previous: Mapped[str | None] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    authorization_epoch: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    generation: Mapped[int] = mapped_column(Integer, default=0)
    failure: Mapped[str | None] = mapped_column(String(512))
    retention: Mapped[str] = mapped_column(String(16), default="retained")


class AgentRunPackageSelection(Base):
    """Persist the signed releases first admitted for a canonical cloud run, including an empty set."""

    __tablename__ = "agent_run_package_selections"
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_run_authorities.id", ondelete="CASCADE"), primary_key=True
    )
    releases: Mapped[list[dict[str, str | int]]] = mapped_column(JSON)


async def agent_driver_conflict(
    db: AsyncSession, tenant_id: str, project_id: str, plugin_id: str, permissions: frozenset[str]
) -> str | None:
    """Consult active release grants under the caller's project publication lock."""
    state, release = ProjectPluginInstallation, ProjectPluginRelease
    providers = chat_adapter_providers(permissions)
    driver = "agent.loop.drive" in permissions
    if not providers and not driver:
        return None
    grants = await db.scalars(
        select(release.permissions)
        .join(
            state,
            (state.project_id == release.project_id)
            & (state.plugin_id == release.plugin_id)
            & (state.active == release.version),
        )
        .where(
            release.project_id == project_id,
            release.tenant_id == tenant_id,
            release.plugin_id != plugin_id,
            state.enabled.is_(True),
        )
    )
    for grant in grants:
        if driver and "agent.loop.drive" in grant:
            return "another Agent loop drives this project"
        if providers.intersection(chat_adapter_providers(grant)):
            return "another chat adapter serves this provider in the project"
    return None


async def select_transition_release(
    db: AsyncSession, tenant_id: str, project_id: str, plugin: str, action: str
) -> tuple[ProjectPluginInstallation, str | None, str | None] | None:
    """Return locked project state and the affected release in the same statement."""
    state, release = ProjectPluginInstallation, ProjectPluginRelease
    version: SQLColumnExpression[str | None] = (
        state.previous if action == "rollback" else state.desired
    )
    if action not in {"enable", "rollback"}:
        version = func.coalesce(state.active, state.desired)
    return (
        (
            await db.execute(
                select(state, release.version, release.digest)
                .outerjoin(
                    release,
                    (release.project_id == state.project_id)
                    & (release.tenant_id == tenant_id)
                    & (release.plugin_id == state.plugin_id)
                    & (release.version == version),
                )
                .where(state.project_id == project_id, state.plugin_id == plugin)
                .execution_options(populate_existing=True)
            )
        )
        .tuples()
        .one_or_none()
    )
