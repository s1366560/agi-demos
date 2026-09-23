"""Durable marketplace state, separate from signed V2 publication authority."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.adapters.secondary.persistence.models import Base


class MarketplaceRecordV3(Base):
    """Scope-keyed records; payload never contains plaintext credentials."""

    __tablename__ = "plugin_marketplace_records_v3"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    record_key: Mapped[str] = mapped_column(String(256), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "project_id", "kind", "record_key", name="uq_marketplace_v3_scope_key"
        ),
    )
