"""Full-document application operations using the existing isolated command authority."""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.model.project_schema.commands import (
    ProjectSchemaReceipt,
    ProjectSchemaScope,
    ReplaceProjectSchema,
)
from src.domain.model.project_schema.document import ProjectSchemaDocument
from src.domain.model.project_schema.transport import (
    SchemaHistoryQuery,
    SchemaReceiptQuery,
    validate_stored_receipt,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_schema_commands import (
    SqlProjectSchemaCommands,
)


@dataclass(frozen=True, kw_only=True)
class SchemaDocumentServicesV2:
    commands: SqlProjectSchemaCommands
    scope: ProjectSchemaScope

    async def read(self) -> ProjectSchemaDocument | None:
        return await self.commands.read(self.scope)

    async def replace(self, command: ReplaceProjectSchema) -> ProjectSchemaReceipt:
        receipt = await self.commands.replace(self.scope, command)
        _ = validate_stored_receipt(
            receipt.receipt_json,
            tenant_id=self.scope.tenant_id,
            project_id=self.scope.project_id,
            schema_id=command.document.to_dict()["schema_id"],
            change_id=command.change_id,
        )
        return receipt

    async def receipt(self, query: SchemaReceiptQuery) -> ProjectSchemaReceipt | None:
        return await self.commands.receipt(self.scope, query)

    async def history(self, query: SchemaHistoryQuery) -> str:
        return await self.commands.history(self.scope, query)
