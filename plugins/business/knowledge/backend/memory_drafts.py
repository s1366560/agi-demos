"""Private editor drafts within a signed knowledge package's project namespace."""

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.plugin_namespace_store_v2 import (
    NamespaceKeyV2,
    NamespaceRecordV2,
    SqlPluginNamespaceStoreV2,
)

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext


class Draft(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    title: str = Field(max_length=500)
    content: str = Field(max_length=32768)
    tags: list[str] = Field(max_length=100)
    savedAt: str = Field(min_length=1, max_length=48)


def _key(ctx: "PackageOperationContext") -> NamespaceKeyV2:
    if not ctx.scope.project_id or not ctx.scope.tenant_id:
        raise HTTPException(403, _("Project membership is required"))
    return NamespaceKeyV2(
        plugin_id="memstack-knowledge",
        tenant_id=ctx.scope.tenant_id,
        project_id=ctx.scope.project_id,
        item_key="memory-editor-draft:" + ctx.user.id,
    )


async def read_draft(ctx: "PackageOperationContext") -> dict[str, Any]:
    key = _key(ctx)
    record = await ctx.db.run_sync(lambda db: SqlPluginNamespaceStoreV2(db).get(key))
    return {"document": record.document if record else None, "owner_id": ctx.user.id}


async def write_draft_document(
    ctx: "PackageOperationContext", document: dict[str, Any]
) -> dict[str, Any]:
    key = _key(ctx)
    record = NamespaceRecordV2(schema_version=1, document=document)
    try:
        async with ctx.db.begin_nested():
            await ctx.db.run_sync(lambda db: SqlPluginNamespaceStoreV2(db).put(key, record))
            await ctx.db.flush()
    except IntegrityError:
        await ctx.db.run_sync(lambda db: SqlPluginNamespaceStoreV2(db).put(key, record))
    await ctx.db.commit()
    return {"saved": True}
