# pyright: reportImportCycles=false
"""Authorize global control before resolving any scheduler or barrier service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, HTTPException, Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.cron_producer_control import (
    CRON_PRODUCER_CONTROL_SERVICE_V2,
    CronProducerControlProtocolV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error


@dataclass(frozen=True, kw_only=True)
class CronProducerAuthorityV2:
    operation: OperationContextV2
    control: CronProducerControlProtocolV2


async def cron_producer_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> AsyncIterator[CronProducerAuthorityV2]:
    """Authentication may read users; cron storage remains untouched before authorization."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail=_("Platform administrator access required"))
    async with OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-cron-producer:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ) as operation:
        _identity = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2, {"user_id": str(current_user.id)}
        )
        _metadata = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {"kind": "http-authority", "method": request.method, "path": request.url.path},
        )
        control = operation.require(CRON_PRODUCER_CONTROL_SERVICE_V2)
        if not isinstance(control, CronProducerControlProtocolV2):
            raise RuntimeV2Error(
                "invalid_cron_producer_control", "cron producer control service is unavailable"
            )
        yield CronProducerAuthorityV2(operation=operation, control=control)
