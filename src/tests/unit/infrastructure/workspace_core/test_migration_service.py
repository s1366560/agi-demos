"""Focused SQL contracts for repeatable Workspace migration upserts."""

from __future__ import annotations

from typing import Any, cast

import pytest

from src.infrastructure.workspace_core.migration.model import MigrationScope, MigrationSpec
from src.infrastructure.workspace_core.migration.service import WorkspaceMigrationService

pytestmark = pytest.mark.unit


class _RecordingConnection:
    def __init__(self) -> None:
        self.sql: str | None = None
        self.parameters: tuple[object, ...] = ()

    async def execute(self, sql: str, *parameters: object) -> str:
        self.sql = sql
        self.parameters = parameters
        return "INSERT 0 1"


class _FetchRecordingConnection:
    def __init__(self) -> None:
        self.sql: str | None = None
        self.parameters: tuple[object, ...] = ()

    async def fetch(self, sql: str, *parameters: object) -> list[dict[str, object]]:
        self.sql = sql
        self.parameters = parameters
        return []


async def test_upsert_refreshes_changed_non_key_columns_without_noop_updates() -> None:
    connection = _RecordingConnection()
    service = WorkspaceMigrationService(cast(Any, connection), specs=())
    spec = MigrationSpec(
        entity_type="principal",
        source_table="workspace_members",
        target_table="workspace_principal_identities",
        source_sql="SELECT 1",
        source_id_column="id",
        target_columns=("workspace_id", "user_id", "email"),
        key_columns=("workspace_id", "user_id"),
    )

    await service._upsert_target(  # pyright: ignore[reportPrivateUsage]
        spec,
        {"workspace_id": "workspace-1", "user_id": "user-1", "email": "new@example.com"},
    )

    assert connection.sql is not None
    assert "ON CONFLICT (workspace_id, user_id)" in connection.sql
    assert "DO UPDATE SET email = EXCLUDED.email" in connection.sql
    assert "workspace_principal_identities.email IS DISTINCT FROM EXCLUDED.email" in connection.sql
    assert connection.parameters == ("workspace-1", "user-1", "new@example.com")


async def test_project_scoped_source_uses_workspace_project_membership_filter() -> None:
    connection = _FetchRecordingConnection()
    spec = MigrationSpec(
        entity_type="project_principal_membership",
        source_table="user_projects",
        target_table="project_principal_memberships",
        source_sql=(
            "SELECT up.id, p.tenant_id AS _tenant_id, p.id AS _project_id, "
            "NULL::text AS _workspace_id FROM user_projects up "
            "JOIN projects p ON p.id = up.project_id"
        ),
        source_id_column="id",
        target_columns=("tenant_id", "project_id", "user_id"),
        key_columns=("tenant_id", "project_id", "user_id"),
        project_scoped=True,
    )
    service = WorkspaceMigrationService(cast(Any, connection), specs=(spec,))

    rows = await service._source_rows(  # pyright: ignore[reportPrivateUsage]
        spec,
        MigrationScope(workspace_id="workspace-1"),
    )

    assert rows == []
    assert connection.sql is not None
    assert "migration_scope_workspace.project_id = migration_source._project_id" in connection.sql
    assert connection.parameters == (None, None, "workspace-1", True)
