"""Independent, typed list-response command capability projection."""

import logging
from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.infrastructure.adapters.primary.web.memory_application_authority_v2 import (
    MemoryApplicationAuthorityV2,
)

logger = logging.getLogger(__name__)


class MemoryObjectCommandActionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memory_id: str
    revision: int
    allowed_actions: list[Literal["update", "delete"]]


class MemoryCommandCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal[1]
    tenant_id: str
    project_id: str
    actor_id: str
    allowed_actions: list[Literal["create"]]
    objects: list[MemoryObjectCommandActionsResponse]


async def command_capabilities_response(
    authority: MemoryApplicationAuthorityV2,
    actor_id: str,
    project_id: str,
    objects: tuple[tuple[str, int], ...],
) -> MemoryCommandCapabilitiesResponse | None:
    try:
        capabilities = await authority.services.online_commands.capabilities(
            actor_id, project_id, objects
        )
        return (
            None
            if capabilities is None
            else MemoryCommandCapabilitiesResponse.model_validate(asdict(capabilities))
        )
    except Exception:
        # No writes use this advisory snapshot: commands always authorize again.
        # A failed independent capability read must not replace the memory page.
        logger.exception("Memory command capabilities unavailable")
        return None
