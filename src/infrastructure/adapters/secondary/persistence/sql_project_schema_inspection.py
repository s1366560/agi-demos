"""One-snapshot, no-autoflush legacy schema inspection. No runtime/API binding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, Text, cast, literal, null, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from src.domain.model.project_schema.inspection import (
    LegacySchemaInspection,
    LegacySchemaRecord,
    SchemaRecordKind,
    inspect_legacy_project_schema,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    EdgeType,
    EdgeTypeMap,
    EntityType,
    Project,
)


class ProjectSchemaInspectionScopeNotFound(ValueError):
    """The exact requested tenant/project scope was not found; no rows are disclosed."""


@dataclass(frozen=True, kw_only=True)
class SqlProjectSchemaInspection:
    """Uses a caller-owned read session; never flushes, commits, initializes or persists."""

    session: AsyncSession

    async def inspect(self, *, tenant_id: str, project_id: str) -> LegacySchemaInspection:
        scope = (
            select(Project.id)
            .where(Project.id == project_id, Project.tenant_id == tenant_id)
            .cte("schema_inspection_scope")
        )
        empty = cast(null(), String)
        # UNION ALL keeps the existence marker and all three tables in one MVCC snapshot.
        queries: list[Select[Any]] = [
            select(
                literal("project").label("kind"),
                scope.c.id.label("record_id"),
                empty.label("name"),
                empty.label("description"),
                empty.label("schema_json"),
                empty.label("status"),
                empty.label("source"),
                empty.label("source_type"),
                empty.label("target_type"),
                empty.label("edge_type"),
            )
        ]
        for model, kind in ((EntityType, "entity_type"), (EdgeType, "edge_type")):
            queries.append(
                select(
                    literal(kind),
                    model.id,
                    model.name,
                    model.description,
                    cast(model.schema, Text),
                    model.status,
                    model.source,
                    empty,
                    empty,
                    empty,
                ).join(scope, model.project_id == scope.c.id)
            )
        queries.append(
            select(
                literal("mapping"),
                EdgeTypeMap.id,
                empty,
                empty,
                empty,
                EdgeTypeMap.status,
                EdgeTypeMap.source,
                EdgeTypeMap.source_type,
                EdgeTypeMap.target_type,
                EdgeTypeMap.edge_type,
            ).join(scope, EdgeTypeMap.project_id == scope.c.id)
        )
        statement = union_all(*queries).order_by("kind", "record_id")
        with self.session.no_autoflush:
            result = await self.session.execute(refresh_select_statement(statement))
        rows = result.mappings().all()
        if not any(row["kind"] == "project" for row in rows):
            raise ProjectSchemaInspectionScopeNotFound("project_schema_inspection_scope_not_found")
        records = tuple(
            LegacySchemaRecord(
                kind=SchemaRecordKind(row["kind"]),
                record_id=row["record_id"],
                name=row["name"],
                description=row["description"],
                schema_json=row["schema_json"],
                status=row["status"],
                source=row["source"],
                source_type=row["source_type"],
                target_type=row["target_type"],
                edge_type=row["edge_type"],
            )
            for row in rows
            if row["kind"] != "project"
        )
        return inspect_legacy_project_schema(
            tenant_id=tenant_id, project_id=project_id, records=records
        )
