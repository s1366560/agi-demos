"""Original HTTP intent, locked CAS and immutable response replay in one transaction."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.project_schema.commands import (
    ProjectSchemaAction,
    ProjectSchemaScope,
    ReplaceProjectSchema,
    require_legacy_representable,
)
from src.domain.model.project_schema.http_mutations import (
    SchemaHttpMutation,
    SchemaHttpOperation,
    SchemaHttpReceipt,
    materialize_http_mutation,
)
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.domain.ports.services.project_schema_authorization import ProjectSchemaAuthorization
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.project_schema_models import (
    ProjectSchemaHttpReceiptModel,
    ProjectSchemaReceiptModel,
)
from src.infrastructure.adapters.secondary.persistence.project_schema_mutate import (
    apply_replacement,
)
from src.infrastructure.adapters.secondary.persistence.project_schema_read import (
    current_document,
    load_head,
    lock_scope,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_schema_commands import (
    _admit,
    _advance_head,
)
from src.infrastructure.adapters.secondary.schema.active_schema_reads import SchemaCommandRequiredV2

ResultT = TypeVar("ResultT")


async def _replay_http(
    db: AsyncSession,
    scope: ProjectSchemaScope,
    schema_id: str,
    change_id: str,
    request_json: str,
) -> SchemaHttpReceipt | None:
    result = await db.execute(
        refresh_select_statement(
            select(ProjectSchemaHttpReceiptModel.__table__).where(
                ProjectSchemaHttpReceiptModel.tenant_id == scope.tenant_id,
                ProjectSchemaHttpReceiptModel.project_id == scope.project_id,
                ProjectSchemaHttpReceiptModel.schema_id == schema_id,
                ProjectSchemaHttpReceiptModel.actor_id == scope.actor_id,
                ProjectSchemaHttpReceiptModel.change_id == change_id,
            )
        )
    )
    row = result.mappings().one_or_none()
    if row is None:
        return None
    if row["original_request_json"] != request_json:
        raise ProjectSchemaError("project_schema_change_id_reused")
    return SchemaHttpReceipt(response_json=row["response_json"])


@dataclass(frozen=True, kw_only=True)
class SqlProjectSchemaHttpCommands:
    sessions: async_sessionmaker[AsyncSession]
    authorization: ProjectSchemaAuthorization

    async def execute(
        self,
        command: SchemaHttpMutation,
        *,
        legacy: Callable[[AsyncSession], Awaitable[ResultT]],
    ) -> SchemaHttpReceipt | ResultT:
        scope = command.scope
        # The command already copied provided fields into immutable JSON before this await.
        await self.authorization.authorize(scope, ProjectSchemaAction.REPLACE)
        async with self.sessions() as db:
            transaction = await db.begin()
            await lock_scope(db, scope)
            head = await load_head(db, scope)
            await self.authorization.authorize(scope, ProjectSchemaAction.REPLACE)
            if head is None or head["mode"] != "active":
                if command.has_preconditions:
                    raise ProjectSchemaError("project_schema_active_required")
                # These methods retain their existing internal commit/refresh behavior.
                # They run in this isolated session under the same bootstrap lock.
                return await legacy(db)
            if db.get_bind().dialect.name != "postgresql":
                raise ProjectSchemaError("project_schema_postgresql_required")
            try:
                request_json = command.request_json()
            except ProjectSchemaError as error:
                if error.code == "project_schema_command_required":
                    raise SchemaCommandRequiredV2 from error
                raise
            request = json.loads(request_json)
            receipt = await _replay_http(
                db, scope, head["schema_id"], request["change_id"], request_json
            )
            if receipt is None:
                receipt = await self._apply(db, command, head["schema_id"], request_json)
            await self.authorization.authorize(scope, ProjectSchemaAction.REPLACE)
            await transaction.commit()
        return receipt

    async def _apply(
        self,
        db: AsyncSession,
        command: SchemaHttpMutation,
        schema_id: str,
        request_json: str,
    ) -> SchemaHttpReceipt:
        scope = command.scope
        request = json.loads(request_json)
        collision = await db.scalar(
            select(ProjectSchemaReceiptModel.change_id).where(
                ProjectSchemaReceiptModel.tenant_id == scope.tenant_id,
                ProjectSchemaReceiptModel.project_id == scope.project_id,
                ProjectSchemaReceiptModel.schema_id == schema_id,
                ProjectSchemaReceiptModel.actor_id == scope.actor_id,
                ProjectSchemaReceiptModel.change_id == request["change_id"],
            )
        )
        if collision is not None:
            raise ProjectSchemaError("project_schema_change_id_reused")
        previous = await current_document(db, scope)
        previous_value = previous.to_dict()
        if request["expected_revision"] != previous_value["revision"]:
            raise ProjectSchemaError("project_schema_revision_conflict")
        created_id = (
            str(uuid4())
            if command.operation
            in {
                SchemaHttpOperation.CREATE_ENTITY,
                SchemaHttpOperation.CREATE_EDGE,
                SchemaHttpOperation.CREATE_MAP,
            }
            else None
        )
        document = materialize_http_mutation(previous, request_json, created_id=created_id)
        require_legacy_representable(document)
        replacement = ReplaceProjectSchema(
            document=document,
            expected_revision=request["expected_revision"],
            change_id=request["change_id"],
        )
        admitted_request = json.loads(replacement.request_json(scope))
        admitted_request.update(http_mutation=request_json, http_created_id=created_id)
        await _admit(
            db,
            scope,
            document=document,
            change_id=request["change_id"],
            expected_revision=request["expected_revision"],
            source_kind="mutation",
            request_json=json.dumps(
                admitted_request, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
        )
        await _advance_head(db, scope, document=document, exists=True)
        await apply_replacement(db, document)
        _ = await db.execute(
            text("SELECT project_schema_finalize_http(:tenant,:project,:schema,:actor,:change)"),
            {
                "tenant": scope.tenant_id,
                "project": scope.project_id,
                "schema": schema_id,
                "actor": scope.actor_id,
                "change": request["change_id"],
            },
        )
        receipt = await _replay_http(db, scope, schema_id, request["change_id"], request_json)
        if receipt is None:
            raise ProjectSchemaError("project_schema_receipt_missing")
        return receipt
