"""Project approvals authorizing one user and device to use one signed package."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.adapters.secondary.persistence.models import Base


class DevicePluginGrant(Base):
    __tablename__ = "device_plugin_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "tenant_id"], ["projects.id", "projects.tenant_id"], ondelete="CASCADE"
        ),
        Index(
            "ix_device_plugin_grants_lookup",
            "project_id",
            "user_id",
            "machine_id",
            "bundle_digest",
            "generation_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String)
    tenant_id: Mapped[str] = mapped_column(String)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    approved_by: Mapped[str] = mapped_column(String)
    machine_id: Mapped[str] = mapped_column(String(128))
    device_fingerprint: Mapped[str] = mapped_column(String(71))
    bundle_digest: Mapped[str] = mapped_column(String(64))
    generation_id: Mapped[str] = mapped_column(String(64))
    permissions: Mapped[list[str]] = mapped_column(JSON)
    approved_permissions: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
