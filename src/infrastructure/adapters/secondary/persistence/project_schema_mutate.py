"""Relational row changes inside an admitted command transaction, never an independent writer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import Table, delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.project_schema.document import ProjectSchemaDocument
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    EdgeType,
    EdgeTypeMap,
    EntityType,
)
from src.infrastructure.adapters.secondary.persistence.project_schema_models import (
    ProjectSchemaTombstoneModel,
)


async def _replace_types(
    db: AsyncSession, table: Table, project_id: str, members: list[dict[str, Any]]
) -> None:
    result = await db.execute(
        refresh_select_statement(select(table).where(table.c.project_id == project_id))
    )
    old = {row["id"]: dict(row) for row in result.mappings()}
    new = {item["id"]: item for item in members}
    # Delete/reinsert name changes atomically to support name swaps under the old
    # immediate name uniqueness constraint. IDs/created_at remain unchanged;
    # the new mapping ID foreign keys are deferred until the full command commits.
    replace_ids = {key for key in old.keys() & new.keys() if old[key]["name"] != new[key]["name"]}
    removed = (old.keys() - new.keys()) | replace_ids
    if removed:
        await db.execute(
            delete(table).where(table.c.project_id == project_id, table.c.id.in_(removed))
        )
    for member_id, member in new.items():
        values = {**member, "project_id": project_id}
        if member_id not in old or member_id in replace_ids:
            if member_id in old:
                values["created_at"] = old[member_id]["created_at"]
                values["updated_at"] = datetime.now(UTC)
            await db.execute(insert(table).values(**values))
        elif any(old[member_id][key] != value for key, value in member.items() if key != "id"):
            await db.execute(
                update(table)
                .where(table.c.project_id == project_id, table.c.id == member_id)
                .values(**{key: value for key, value in member.items() if key != "id"})
            )


async def bootstrap_references(db: AsyncSession, document: ProjectSchemaDocument) -> None:
    value = document.to_dict()
    for member in value["mappings"]:
        await db.execute(
            update(EdgeTypeMap)
            .where(EdgeTypeMap.project_id == value["project_id"], EdgeTypeMap.id == member["id"])
            .values(
                source_type_id=member["source_type_id"],
                target_type_id=member["target_type_id"],
                edge_type_id=member["edge_type_id"],
            )
        )


async def apply_replacement(db: AsyncSession, document: ProjectSchemaDocument) -> None:
    value = document.to_dict()
    project_id = value["project_id"]
    # Maps are compatibility fields, reconstructed from IDs in this same transaction.
    # Replacing them also permits endpoint/name swaps under the old triple uniqueness.
    existing_maps = await db.execute(
        refresh_select_statement(
            select(EdgeTypeMap.id, EdgeTypeMap.created_at).where(
                EdgeTypeMap.project_id == project_id
            )
        )
    )
    created_at = {row[0]: row[1] for row in existing_maps}
    await db.execute(delete(EdgeTypeMap).where(EdgeTypeMap.project_id == project_id))
    await _replace_types(db, cast(Table, EntityType.__table__), project_id, value["entity_types"])
    await _replace_types(db, cast(Table, EdgeType.__table__), project_id, value["edge_types"])
    entities = {item["id"]: item["name"] for item in value["entity_types"]}
    edges = {item["id"]: item["name"] for item in value["edge_types"]}
    for item in value["mappings"]:
        preserved = {"created_at": created_at[item["id"]]} if item["id"] in created_at else {}
        await db.execute(
            insert(EdgeTypeMap).values(
                **item,
                **preserved,
                project_id=project_id,
                source_type=entities[item["source_type_id"]],
                target_type=entities[item["target_type_id"]],
                edge_type=edges[item["edge_type_id"]],
            )
        )
    for tombstone in value["tombstones"]:
        if tombstone["deleted_revision"] != value["revision"]:
            continue
        await db.execute(
            insert(ProjectSchemaTombstoneModel).values(
                tenant_id=value["tenant_id"],
                project_id=project_id,
                schema_id=value["schema_id"],
                member_id=tombstone["id"],
                kind=tombstone["kind"],
                deleted_revision=tombstone["deleted_revision"],
            )
        )
