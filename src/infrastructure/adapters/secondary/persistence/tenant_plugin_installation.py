"""Tenant approvals have no project foreign key and never inherit a project selection."""

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.adapters.secondary.persistence.models import Base


class TenantPluginRelease(Base):
    __tablename__ = "tenant_plugin_releases"

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    plugin_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    digest: Mapped[str] = mapped_column(String(71))
    archive: Mapped[bytes] = mapped_column(LargeBinary)
    permissions: Mapped[list[str]] = mapped_column(JSON)
    approved_by: Mapped[str] = mapped_column(String)


class TenantPluginInstallation(Base):
    __tablename__ = "tenant_plugin_installations"

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    plugin_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    desired: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[str | None] = mapped_column(String(64))
    previous: Mapped[str | None] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    failure: Mapped[str | None] = mapped_column(String(512))
    retention: Mapped[str] = mapped_column(String(16), default="retained")
