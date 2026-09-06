"""Private immutable source binding for one exact scoped publication."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKeyConstraint, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.adapters.secondary.persistence.models import Base
from src.infrastructure.adapters.secondary.persistence.plugin_scope_columns_v2 import (
    PluginScopeColumnsV2,
    plugin_scope_constraints_v2,
)


class PlatformPluginV2PublicationSourceModel(PluginScopeColumnsV2, Base):
    """Canonical DesiredBundleSet payload; historical binding does not grant trust."""

    __tablename__ = "platform_plugin_v2_publication_sources"

    publication_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        *plugin_scope_constraints_v2("plugin_v2_publication_source"),
        ForeignKeyConstraint(
            ["scope_key", "publication_id"],
            ["platform_plugin_v2_publications.scope_key", "platform_plugin_v2_publications.id"],
            name="fk_plugin_v2_publication_source_scope",
            ondelete="RESTRICT",
        ),
    )
