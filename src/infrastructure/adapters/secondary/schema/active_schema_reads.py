"""Pure active-schema snapshots; no cache, admission grant, or implicit activation.

Internal graph callers already own project access. This adapter resolves the actual
project tenant and checks the stored document scope; it does not invent an actor.
HTTP callers must separately use the live operation-bound authorization port.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.project_schema.document import ProjectSchemaDocument
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.infrastructure.adapters.secondary.persistence.models import (
    EdgeType,
    EdgeTypeMap,
    EntityType,
    Project,
)
from src.infrastructure.adapters.secondary.persistence.project_schema_models import (
    ProjectSchemaHeadModel,
)


class SchemaCommandRequiredV2(ProjectSchemaError):
    """An enrolled project cannot be mutated through a legacy writer."""

    def __init__(self) -> None:
        super().__init__("project_schema_command_required")


async def require_legacy_schema(session: AsyncSession, project_id: str) -> None:
    with session.no_autoflush:
        # Bootstrap takes the same project lock. A writer cannot pass the mode
        # check and then race enrollment before its legacy transaction finishes.
        _ = await session.scalar(
            select(Project.id).where(Project.id == project_id).with_for_update()
        )
        active = await session.scalar(
            select(ProjectSchemaHeadModel.project_id).where(
                ProjectSchemaHeadModel.project_id == project_id,
                ProjectSchemaHeadModel.mode == "active",
            )
        )
    if active is not None:
        raise SchemaCommandRequiredV2


# A single statement means document and response timestamps share one MVCC snapshot.
_SNAPSHOT = text("""
SELECT p.tenant_id, project_schema_current_document(p.id)::text AS document,
       (SELECT jsonb_object_agg(e.id, jsonb_build_object(
           'created_at', e.created_at, 'updated_at', e.updated_at))
        FROM entity_types e WHERE e.project_id = p.id) AS entity_times,
       (SELECT jsonb_object_agg(e.id, jsonb_build_object(
           'created_at', e.created_at, 'updated_at', e.updated_at))
        FROM edge_types e WHERE e.project_id = p.id) AS edge_times,
       (SELECT jsonb_object_agg(m.id, jsonb_build_object('created_at', m.created_at))
        FROM edge_type_maps m WHERE m.project_id = p.id) AS mapping_times
FROM projects p JOIN project_schema_heads h ON h.project_id = p.id
WHERE p.id = :project_id AND h.mode = 'active'
""")


@dataclass(frozen=True, kw_only=True)
class ActiveSchemaSnapshot:
    document: ProjectSchemaDocument
    entity_times: dict[str, Any]
    edge_times: dict[str, Any]
    mapping_times: dict[str, Any]

    def types(self, kind: str) -> list[Any]:
        value = self.document.to_dict()
        model, times = (
            (EntityType, self.entity_times)
            if kind == "entity_types"
            else (EdgeType, self.edge_times)
        )
        return [
            model(
                id=item["id"],
                project_id=value["project_id"],
                name=item["name"],
                description=item["description"],
                schema=item["schema"],
                status=item["status"],
                source=item["source"],
                **_timestamps(times[item["id"]]),
            )
            for item in value[kind]
        ]

    def mappings(self) -> list[EdgeTypeMap]:
        value = self.document.to_dict()
        entities = {item["id"]: item["name"] for item in value["entity_types"]}
        edges = {item["id"]: item["name"] for item in value["edge_types"]}
        return [
            EdgeTypeMap(
                id=item["id"],
                project_id=value["project_id"],
                source_type_id=item["source_type_id"],
                target_type_id=item["target_type_id"],
                edge_type_id=item["edge_type_id"],
                source_type=entities[item["source_type_id"]],
                target_type=entities[item["target_type_id"]],
                edge_type=edges[item["edge_type_id"]],
                status=item["status"],
                source=item["source"],
                **_timestamps(self.mapping_times[item["id"]]),
            )
            for item in value["mappings"]
        ]


def _timestamps(value: dict[str, str | None]) -> dict[str, datetime | None]:
    return {key: datetime.fromisoformat(item) if item else None for key, item in value.items()}


async def active_schema_snapshot(
    session: AsyncSession, project_id: str, *, tenant_id: str | None = None
) -> ActiveSchemaSnapshot | None:
    with session.no_autoflush:
        result = await session.execute(_SNAPSHOT, {"project_id": project_id})
    row = result.mappings().one_or_none()
    if row is None:
        return None
    document = ProjectSchemaDocument.from_json(row["document"])
    value = document.to_dict()
    if (value["tenant_id"], value["project_id"]) != (row["tenant_id"], project_id) or (
        tenant_id is not None and tenant_id != row["tenant_id"]
    ):
        raise ProjectSchemaError("project_schema_scope_mismatch")
    return ActiveSchemaSnapshot(
        document=document,
        entity_times=row["entity_times"] or {},
        edge_times=row["edge_times"] or {},
        mapping_times=row["mapping_times"] or {},
    )
