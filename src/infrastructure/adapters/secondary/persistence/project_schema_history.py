"""Project-locked immutable cloud receipt/history reads across all project writers."""

from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.project_schema.commands import ProjectSchemaReceipt, ProjectSchemaScope
from src.domain.model.project_schema.transport import (
    SchemaHistoryQuery,
    SchemaReceiptQuery,
    history_page_json,
    validate_stored_receipt,
)
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.project_schema_models import (
    ProjectSchemaChangeModel as Change,
    ProjectSchemaReceiptModel as Receipt,
)
from src.infrastructure.adapters.secondary.persistence.project_schema_read import load_head


async def exact_receipt(
    db: AsyncSession, scope: ProjectSchemaScope, query: SchemaReceiptQuery
) -> ProjectSchemaReceipt | None:
    raw = await db.scalar(
        select(Receipt.receipt_json).where(
            Receipt.tenant_id == scope.tenant_id,
            Receipt.project_id == scope.project_id,
            Receipt.schema_id == query.schema_id,
            Receipt.actor_id == scope.actor_id,
            Receipt.change_id == query.change_id,
        )
    )
    if raw is None:
        return None
    _ = validate_stored_receipt(
        raw,
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        schema_id=query.schema_id,
        change_id=query.change_id,
    )
    return ProjectSchemaReceipt(receipt_json=raw)


async def receipt_history(
    db: AsyncSession, scope: ProjectSchemaScope, query: SchemaHistoryQuery
) -> str:
    head = await load_head(db, scope)
    if head is None or head["mode"] != "active":
        raise ProjectSchemaError("project_schema_active_required")
    if head["schema_id"] != query.schema_id:
        raise ProjectSchemaError("project_schema_identity_conflict")
    upper = head["revision"]
    if type(upper) is not int or upper != head["sequence"]:
        raise RuntimeError("corrupt schema history head")
    if query.after_revision > upper:
        raise ProjectSchemaError("project_schema_cursor_invalid")
    statement = (
        select(
            Change.revision,
            Change.sequence,
            Change.change_id,
            Change.snapshot,
            Receipt.receipt_json,
        )
        .outerjoin(
            Receipt,
            and_(
                Receipt.tenant_id == Change.tenant_id,
                Receipt.project_id == Change.project_id,
                Receipt.schema_id == Change.schema_id,
                Receipt.actor_id == Change.actor_id,
                Receipt.change_id == Change.change_id,
            ),
        )
        .where(
            Change.tenant_id == scope.tenant_id,
            Change.project_id == scope.project_id,
            Change.schema_id == query.schema_id,
            Change.revision > query.after_revision,
            Change.revision <= upper,
        )
        .order_by(Change.revision)
        .limit(query.limit)
    )
    rows = (await db.execute(refresh_select_statement(statement))).mappings().all()
    expected_count = min(query.limit, upper - query.after_revision)
    if len(rows) != expected_count:
        raise RuntimeError("corrupt schema history gap")
    receipts: list[str] = []
    for index, row in enumerate(rows, query.after_revision + 1):
        raw = row["receipt_json"]
        if row["revision"] != index or row["sequence"] != index or not isinstance(raw, str):
            raise RuntimeError("corrupt schema history gap")
        value = validate_stored_receipt(
            raw,
            tenant_id=scope.tenant_id,
            project_id=scope.project_id,
            schema_id=query.schema_id,
            change_id=row["change_id"],
        )
        if value["revision"] != index or value["document"] != row["snapshot"]:
            raise RuntimeError("corrupt schema history snapshot")
        receipts.append(raw)
    return history_page_json(
        schema_id=query.schema_id,
        after_revision=query.after_revision,
        upper_revision=upper,
        receipts=receipts,
    )
