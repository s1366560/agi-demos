"""Immutable local outcomes retained before a newer request replaces a blocked attempt."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.adapters.secondary.persistence.models import Base
from src.infrastructure.adapters.secondary.persistence.plugin_scope_columns_v2 import (
    PluginScopeColumnsV2,
    plugin_scope_constraints_v2,
)


class PlatformPluginV2OutcomeSupersessionModel(PluginScopeColumnsV2, Base):
    """Audit only: these rows never grant admission or advance applied state."""

    __tablename__ = "platform_plugin_v2_outcome_supersessions"

    data_plane_id: Mapped[str] = mapped_column(String(255), nullable=False)
    outcome_publication_id: Mapped[str] = mapped_column(String(36), nullable=False)
    replacement_publication_id: Mapped[str] = mapped_column(String(36), nullable=False)
    receipt_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        *plugin_scope_constraints_v2("plugin_v2_outcome_supersession"),
        PrimaryKeyConstraint(
            "scope_key", "data_plane_id", "outcome_publication_id", "replacement_publication_id"
        ),
        ForeignKeyConstraint(
            ["scope_key", "outcome_publication_id"],
            ["platform_plugin_v2_publications.scope_key", "platform_plugin_v2_publications.id"],
            name="fk_plugin_v2_supersession_outcome",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["scope_key", "replacement_publication_id"],
            ["platform_plugin_v2_publications.scope_key", "platform_plugin_v2_publications.id"],
            name="fk_plugin_v2_supersession_replacement",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "outcome_publication_id <> replacement_publication_id",
            name="ck_plugin_v2_supersession_distinct",
        ),
        CheckConstraint("length(trim(data_plane_id)) > 0", name="ck_plugin_v2_supersession_plane"),
    )
