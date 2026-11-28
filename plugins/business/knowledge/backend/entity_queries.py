"""Read-only entity graph capabilities bound to the invoking project's approved scope."""

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class _Query(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Entities(_Query):
    entity_type: str | None = Field(default=None, max_length=256)
    limit: int = Field(default=20, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=2147483647)


class _Relationships(_Query):
    entity_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    limit: int = Field(default=50, ge=1, le=200)


async def list_entities(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.knowledge.guest.commands import list_entities as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


async def entity_types(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.knowledge.guest.commands import entity_types as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


async def entity_relationships(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.knowledge.guest.commands import entity_relationships as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


ENTITY_OPERATIONS = {
    "app.knowledge.entities.list": list_entities,
    "app.knowledge.entities.types": entity_types,
    "app.knowledge.entities.relationships": entity_relationships,
}
