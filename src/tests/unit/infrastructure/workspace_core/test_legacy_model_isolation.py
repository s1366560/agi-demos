"""Legacy Workspace ORM isolation contracts."""

from __future__ import annotations

from sqlalchemy.orm import configure_mappers

from src.infrastructure.adapters.secondary.persistence.models import Base
from src.infrastructure.workspace_core.migration.legacy_models import (
    LEGACY_WORKSPACE_TABLES,
    LegacyWorkspaceBase,
    legacy_workspace_metadata,
)


def test_production_metadata_does_not_register_legacy_workspace_tables() -> None:
    assert LEGACY_WORKSPACE_TABLES.isdisjoint(Base.metadata.tables)


def test_offline_legacy_metadata_registers_complete_workspace_source_schema() -> None:
    assert legacy_workspace_metadata.tables.keys() >= LEGACY_WORKSPACE_TABLES
    assert LegacyWorkspaceBase.metadata is legacy_workspace_metadata


def test_offline_legacy_mappers_configure_independently() -> None:
    configure_mappers()
