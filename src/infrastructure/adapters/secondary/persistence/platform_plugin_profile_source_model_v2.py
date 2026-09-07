"""Immutable scope-private profile source revisions; no trust or auth grant."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.adapters.secondary.persistence.models import Base, IdGeneratorMixin
from src.infrastructure.adapters.secondary.persistence.plugin_scope_columns_v2 import (
    PluginScopeColumnsV2,
    plugin_scope_constraints_v2,
)


class PlatformPluginV2ProfileSourceModel(PluginScopeColumnsV2, IdGeneratorMixin, Base):
    """Payload integrity does not imply provenance signature or execution authorization."""

    __tablename__ = "platform_plugin_v2_profile_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(255), nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    digest: Mapped[str] = mapped_column(String(71), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        *plugin_scope_constraints_v2("plugin_v2_profile_source"),
        UniqueConstraint("scope_key", "source_id", "revision", name="uq_plugin_v2_source_revision"),
        CheckConstraint("revision > 0", name="ck_plugin_v2_source_revision"),
        CheckConstraint("length(digest) = 71", name="ck_plugin_v2_source_digest"),
    )
