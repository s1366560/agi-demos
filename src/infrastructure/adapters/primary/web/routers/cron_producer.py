"""Administrator access to a responding producer, never deployment verification."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.infrastructure.adapters.primary.web.cron_producer_authority_v2 import (
    CronProducerAuthorityV2,
    cron_producer_authority_dependency_v2,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.scheduler.cron_deployment_drain import CronProducerCloseRequest

router = APIRouter(prefix="/api/v1/admin/cron-producer", tags=["cron-producer"])


class CronProducerCloseBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    deployment_id: str = Field(min_length=1, max_length=255)
    source_generation: str = Field(min_length=1, max_length=255)
    producer_id: str = Field(min_length=1, max_length=255)
    expected_revision: int = Field(ge=1)
    schedule_ids: list[str] = Field(max_length=10000)


@router.get("")
async def inspect_cron_producer(
    authority: CronProducerAuthorityV2 = Depends(cron_producer_authority_dependency_v2),
) -> dict[str, object]:
    """Inspect current state after a lost response; this is not an operation receipt."""
    return await authority.control.inspect_local()


@router.post("/close")
async def close_cron_producer(
    body: CronProducerCloseBody,
    authority: CronProducerAuthorityV2 = Depends(cron_producer_authority_dependency_v2),
) -> dict[str, object]:
    """Invoke the exact prepared-bound local adapter in the responding process."""
    try:
        request = CronProducerCloseRequest(
            deployment_id=body.deployment_id,
            source_generation=body.source_generation,
            producer_id=body.producer_id,
            expected_revision=body.expected_revision,
            schedule_ids=tuple(body.schedule_ids),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=_("Invalid cron producer close request")
        ) from exc
    observation = await authority.control.close_prepared(request)
    return observation.to_wire()
