"""Authenticated scope-private ProfileSource writes; never runtime publication."""

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    resolve_plugin_publication_scope_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
    PlatformPluginProfileSourceV2Error,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.protocol import (
    parse_profile_source_v2,
    profile_source_v2_to_payload,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.scope import parse_scope_v2, scope_v2_to_payload

router = APIRouter(prefix="/v2", tags=["Platform Plugins V2"])


@router.post("/profile-sources")
async def post_profile_source_v2(
    payload: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Store a validated source; provenance does not confer trust or install bundles."""
    try:
        if set(payload) != {"scope", "source", "expected_revision"}:
            raise ValueError("invalid request fields")
        requested = parse_scope_v2(payload["scope"])
        expected = payload["expected_revision"]
        if expected is not None and (type(expected) is not int or expected < 1):
            raise ValueError("invalid expected revision")
    except ValueError as error:
        raise HTTPException(
            400,
            detail={
                "reason_code": "profile_source_request_invalid",
                "message": _("Invalid profile source request"),
            },
        ) from error
    try:
        scope = await resolve_plugin_publication_scope_v2(
            db, current_user=current_user, requested_scope=requested
        )
    except RuntimeV2Error as error:
        raise HTTPException(
            403,
            detail={
                "reason_code": "profile_source_scope_forbidden",
                "message": _("Profile source scope is not authorized"),
            },
        ) from error
    try:
        source = parse_profile_source_v2(payload["source"])
        saved = await PlatformPluginProfileSourceRepositoryV2(db).record_source(
            scope=scope, source=source, expected_revision=expected
        )
        await db.commit()
    except PlatformPluginProfileSourceV2Error as error:
        await db.rollback()
        conflict = error.code in {"profile_source_head_conflict", "profile_source_revision_gap"}
        raise HTTPException(
            409 if conflict else 400,
            detail={
                "reason_code": "profile_source_revision_conflict"
                if conflict
                else "profile_source_invalid",
                "message": _("Profile source revision conflict")
                if conflict
                else _("Invalid profile source"),
            },
        ) from error
    except ValueError as error:
        await db.rollback()
        raise HTTPException(
            400,
            detail={
                "reason_code": "profile_source_invalid",
                "message": _("Invalid profile source"),
            },
        ) from error
    return {"scope": scope_v2_to_payload(scope), "source": profile_source_v2_to_payload(saved)}
