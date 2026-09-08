"""Full-document commands with explicit authorization and atomic commit boundaries.

The operation-owned factory supplies isolated sessions for the cloud document transport;
unrelated caller ORM state is never flushed. Bootstrap remains an internal operation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import insert, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.project_schema.bootstrap import bootstrap_document
from src.domain.model.project_schema.commands import (
    BootstrapProjectSchema,
    ProjectSchemaAction,
    ProjectSchemaReceipt,
    ProjectSchemaScope,
    ReplaceProjectSchema,
    canonical_snapshot,
    require_legacy_representable,
)
from src.domain.model.project_schema.document import ProjectSchemaDocument
from src.domain.model.project_schema.transport import SchemaHistoryQuery, SchemaReceiptQuery
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.domain.ports.services.project_schema_authorization import ProjectSchemaAuthorization
from src.infrastructure.adapters.secondary.persistence.project_schema_history import (
    exact_receipt,
    receipt_history,
)
from src.infrastructure.adapters.secondary.persistence.project_schema_models import (
    ProjectSchemaHeadModel,
)
from src.infrastructure.adapters.secondary.persistence.project_schema_mutate import (
    apply_replacement,
    bootstrap_references,
)
from src.infrastructure.adapters.secondary.persistence.project_schema_read import (
    current_document,
    load_head,
    lock_scope,
    replay_receipt,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_schema_inspection import (
    SqlProjectSchemaInspection,
)


async def _admit(
    db: AsyncSession,
    scope: ProjectSchemaScope,
    *,
    document: ProjectSchemaDocument,
    change_id: str,
    expected_revision: int,
    request_json: str,
    source_kind: str,
) -> None:
    payload = json.dumps(
        {
            "tenant_id": scope.tenant_id,
            "project_id": scope.project_id,
            "actor_id": scope.actor_id,
            "change_id": change_id,
            "expected_revision": expected_revision,
            "schema_id": document.to_dict()["schema_id"],
            "source_kind": source_kind,
            "request_json": request_json,
            "document": document.to_dict(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    await db.execute(
        text("SELECT set_config('memstack.project_schema_intent', :payload, true)"),
        {"payload": payload},
    )


async def _advance_head(
    db: AsyncSession, scope: ProjectSchemaScope, *, document: ProjectSchemaDocument, exists: bool
) -> None:
    value = document.to_dict()
    values: dict[str, Any] = {
        "mode": "active",
        "schema_id": value["schema_id"],
        "revision": value["revision"],
        "sequence": value["revision"],
        "deleted": value["deleted"],
    }
    if exists:
        await db.execute(
            update(ProjectSchemaHeadModel)
            .where(
                ProjectSchemaHeadModel.project_id == scope.project_id,
                ProjectSchemaHeadModel.tenant_id == scope.tenant_id,
            )
            .values(**values)
        )
    else:
        await db.execute(
            insert(ProjectSchemaHeadModel).values(
                **values, tenant_id=scope.tenant_id, project_id=scope.project_id
            )
        )
    # The database head trigger appends the immutable journal and exact receipt.
    # Deferred guards reject commit until the current relational rows match them.


@dataclass(frozen=True, kw_only=True)
class SqlProjectSchemaCommands:
    sessions: async_sessionmaker[AsyncSession]
    authorization: ProjectSchemaAuthorization

    async def _start(
        self, db: AsyncSession, scope: ProjectSchemaScope, action: ProjectSchemaAction
    ) -> None:
        if db.get_bind().dialect.name != "postgresql":
            raise ProjectSchemaError("project_schema_postgresql_required")
        await self.authorization.authorize(scope, action)
        await lock_scope(db, scope)

    async def read(self, scope: ProjectSchemaScope) -> ProjectSchemaDocument | None:
        async with self.sessions() as db, db.begin():
            await self._start(db, scope, ProjectSchemaAction.READ)
            head = await load_head(db, scope)
            document = (
                await current_document(db, scope)
                if head is not None and head["mode"] == "active"
                else None
            )
            await self.authorization.authorize(scope, ProjectSchemaAction.READ)
        return document

    async def receipt(
        self, scope: ProjectSchemaScope, query: SchemaReceiptQuery
    ) -> ProjectSchemaReceipt | None:
        async with self.sessions() as db, db.begin():
            await self._start(db, scope, ProjectSchemaAction.READ)
            await self.authorization.authorize(scope, ProjectSchemaAction.READ)
            result = await exact_receipt(db, scope, query)
            await self.authorization.authorize(scope, ProjectSchemaAction.READ)
        return result

    async def history(self, scope: ProjectSchemaScope, query: SchemaHistoryQuery) -> str:
        async with self.sessions() as db, db.begin():
            await self._start(db, scope, ProjectSchemaAction.READ)
            await self.authorization.authorize(scope, ProjectSchemaAction.READ)
            result = await receipt_history(db, scope, query)
            await self.authorization.authorize(scope, ProjectSchemaAction.READ)
        return result

    async def bootstrap(
        self, scope: ProjectSchemaScope, command: BootstrapProjectSchema
    ) -> ProjectSchemaReceipt:
        request_json = command.request_json(scope)
        async with self.sessions() as db, db.begin():
            await self._start(db, scope, ProjectSchemaAction.BOOTSTRAP)
            receipt = await replay_receipt(
                db, scope, change_id=command.change_id, request_json=request_json
            )
            if receipt is None:
                head = await load_head(db, scope)
                if head is not None and head["mode"] == "active":
                    raise ProjectSchemaError("project_schema_already_active")
                records = await SqlProjectSchemaInspection(session=db).read_records(
                    tenant_id=scope.tenant_id, project_id=scope.project_id
                )
                document = bootstrap_document(
                    scope=scope, schema_id=command.schema_id, records=records
                )
                await _admit(
                    db,
                    scope,
                    document=document,
                    change_id=command.change_id,
                    expected_revision=0,
                    request_json=request_json,
                    source_kind="bootstrap",
                )
                await _advance_head(db, scope, document=document, exists=head is not None)
                await bootstrap_references(db, document)
                receipt = await replay_receipt(
                    db, scope, change_id=command.change_id, request_json=request_json
                )
                if receipt is None:
                    raise ProjectSchemaError("project_schema_receipt_missing")
            await self.authorization.authorize(scope, ProjectSchemaAction.BOOTSTRAP)
        return receipt

    async def replace(
        self, scope: ProjectSchemaScope, command: ReplaceProjectSchema
    ) -> ProjectSchemaReceipt:
        request_json = command.request_json(scope)
        document = canonical_snapshot(command.document)
        require_legacy_representable(document)
        async with self.sessions() as db, db.begin():
            await self._start(db, scope, ProjectSchemaAction.REPLACE)
            receipt = await replay_receipt(
                db, scope, change_id=command.change_id, request_json=request_json
            )
            if receipt is None:
                previous = await current_document(db, scope)
                document.validate_successor(
                    previous=previous, expected_revision=command.expected_revision
                )
                await _admit(
                    db,
                    scope,
                    document=document,
                    change_id=command.change_id,
                    expected_revision=command.expected_revision,
                    request_json=request_json,
                    source_kind="mutation",
                )
                await _advance_head(db, scope, document=document, exists=True)
                await apply_replacement(db, document)
                receipt = await replay_receipt(
                    db, scope, change_id=command.change_id, request_json=request_json
                )
                if receipt is None:
                    raise ProjectSchemaError("project_schema_receipt_missing")
            await self.authorization.authorize(scope, ProjectSchemaAction.REPLACE)
        return receipt
