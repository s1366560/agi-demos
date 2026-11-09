"""Marketplace projection, update hints, and the review queue."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.marketplace_governance_v2 import (
    CatalogProjectionRowV2,
    MarketplaceReviewQueueV2,
    project_catalog_v2,
    projection_row_from_package_v2,
    update_available_v2,
)


class ReviewSubmitV2(BaseModel):
    plugin_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=32)
    digest: str = Field(min_length=7, max_length=80)
    note: str = ""


class ReviewDecisionV2(BaseModel):
    status: str


class InstalledPackageV2(BaseModel):
    plugin_id: str
    version: str


class UpdateQueryV2(BaseModel):
    installed: list[InstalledPackageV2]


def review_queue_v2(request: Request) -> MarketplaceReviewQueueV2:
    queue = getattr(request.app.state, "marketplace_review_queue_v2", None)
    if not isinstance(queue, MarketplaceReviewQueueV2):
        queue = MarketplaceReviewQueueV2()
        request.app.state.marketplace_review_queue_v2 = queue
    return queue


async def _rows(request: Request, db: AsyncSession) -> tuple[CatalogProjectionRowV2, ...]:
    raw = getattr(request.app.state, "marketplace_projection_rows_v2", None)
    if raw:
        return tuple(raw)
    packages = await PlatformPluginGovernanceRepository(db).list_packages(include_revoked=True)
    return tuple(projection_row_from_package_v2(package) for package in packages)


async def marketplace_projection_v2(
    request: Request,
    q: str = "",
    permission: str | None = None,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = project_catalog_v2(await _rows(request, db), query=q, permission=permission)
    return {
        "items": [
            {"plugin_id": row.plugin_id, "version": row.version, "permissions": list(row.permissions)}
            for row in rows
        ]
    }


async def marketplace_updates_v2(
    body: UpdateQueryV2,
    request: Request,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    installed = {item.plugin_id: item.version for item in body.installed}
    return {"updates": list(update_available_v2(installed, await _rows(request, db)))}


async def submit_marketplace_review_v2(
    body: ReviewSubmitV2,
    request: Request,
    _current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    row = review_queue_v2(request).submit(
        plugin_id=body.plugin_id, version=body.version, digest=body.digest, note=body.note
    )
    return {"review_id": row.review_id, "status": row.status}


async def list_marketplace_reviews_v2(
    request: Request,
    status: str | None = None,
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return {
        "items": [
            {
                "review_id": row.review_id,
                "plugin_id": row.plugin_id,
                "version": row.version,
                "status": row.status,
            }
            for row in review_queue_v2(request).list(status)
        ]
    }


async def decide_marketplace_review_v2(
    review_id: str,
    body: ReviewDecisionV2,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    if not current_user.is_superuser:
        raise HTTPException(403, _("Only a platform administrator may decide a review"))
    try:
        row = review_queue_v2(request).decide(review_id, body.status)
    except KeyError as exc:
        raise HTTPException(404, _("Review was not found")) from exc
    except ValueError as exc:
        raise HTTPException(400, _(str(exc))) from exc
    return {"review_id": row.review_id, "status": row.status}
