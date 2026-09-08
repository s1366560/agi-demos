"""Locked relational reads and durable command replay; no activation on read."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.project_schema.commands import ProjectSchemaReceipt, ProjectSchemaScope
from src.domain.model.project_schema.document import ProjectSchemaDocument
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import Project
from src.infrastructure.adapters.secondary.persistence.project_schema_models import (
    ProjectSchemaHeadModel,
    ProjectSchemaReceiptModel,
)


async def lock_scope(db: AsyncSession, scope: ProjectSchemaScope) -> None:
    project = await db.scalar(
        refresh_select_statement(
            select(Project.id)
            .where(Project.id == scope.project_id, Project.tenant_id == scope.tenant_id)
            .with_for_update()
        )
    )
    if project is None:
        raise ProjectSchemaError("project_schema_scope_not_found")


async def load_head(db: AsyncSession, scope: ProjectSchemaScope) -> dict[str, Any] | None:
    result = await db.execute(
        refresh_select_statement(
            select(ProjectSchemaHeadModel.__table__).where(
                ProjectSchemaHeadModel.tenant_id == scope.tenant_id,
                ProjectSchemaHeadModel.project_id == scope.project_id,
            )
        )
    )
    row = result.mappings().one_or_none()
    return dict(row) if row is not None else None


async def replay_receipt(
    db: AsyncSession, scope: ProjectSchemaScope, *, change_id: str, request_json: str
) -> ProjectSchemaReceipt | None:
    result = await db.execute(
        refresh_select_statement(
            select(ProjectSchemaReceiptModel.__table__).where(
                ProjectSchemaReceiptModel.tenant_id == scope.tenant_id,
                ProjectSchemaReceiptModel.project_id == scope.project_id,
                ProjectSchemaReceiptModel.actor_id == scope.actor_id,
                ProjectSchemaReceiptModel.change_id == change_id,
            )
        )
    )
    row = result.mappings().one_or_none()
    if row is None:
        return None
    if row["request_json"] != request_json:
        raise ProjectSchemaError("project_schema_change_id_reused")
    return ProjectSchemaReceipt(receipt_json=row["receipt_json"])


async def current_document(db: AsyncSession, scope: ProjectSchemaScope) -> ProjectSchemaDocument:
    raw = await db.scalar(
        text("SELECT project_schema_current_document(:project_id)::text"),
        {"project_id": scope.project_id},
    )
    if raw is None:
        raise ProjectSchemaError("project_schema_not_active")
    document = ProjectSchemaDocument.from_json(raw)
    value = document.to_dict()
    if (value["tenant_id"], value["project_id"]) != (scope.tenant_id, scope.project_id):
        raise ProjectSchemaError("project_schema_scope_mismatch")
    return document
