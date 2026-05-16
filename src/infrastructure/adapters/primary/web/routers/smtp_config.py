"""SMTP Configuration router -- tenant-scoped mail server settings."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.smtp_schemas import (
    SmtpConfigCreate,
    SmtpConfigResponse,
    SmtpTestRequest,
)
from src.application.services.smtp_config_service import (
    SmtpConfigService,
    mask_password,
)
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.sql_smtp_config_repository import (
    SqlSmtpConfigRepository,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/smtp-config",
    tags=["smtp-config"],
)


def _build_service(db: AsyncSession) -> SmtpConfigService:
    return SmtpConfigService(repo=SqlSmtpConfigRepository(db))


async def _require_tenant_access(
    db: AsyncSession,
    current_user: User,
    tenant_id: str,
    *,
    require_admin: bool = False,
) -> None:
    if getattr(current_user, "is_superuser", False):
        return
    await require_tenant_access(db, current_user, tenant_id, require_admin=require_admin)


@router.get("", response_model=SmtpConfigResponse | None)
async def get_smtp_config(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SmtpConfigResponse | None:
    await _require_tenant_access(db, current_user, tenant_id)
    service = _build_service(db)
    config = await service.get_config(tenant_id)
    if config is None:
        return None
    return SmtpConfigResponse(
        id=config.id,
        tenant_id=config.tenant_id,
        smtp_host=config.smtp_host,
        smtp_port=config.smtp_port,
        smtp_username=config.smtp_username,
        smtp_password_masked=mask_password(config.smtp_password_encrypted),
        from_email=config.from_email,
        from_name=config.from_name,
        use_tls=config.use_tls,
    )


@router.put("", response_model=SmtpConfigResponse)
async def upsert_smtp_config(
    tenant_id: str,
    body: SmtpConfigCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SmtpConfigResponse:
    await _require_tenant_access(db, current_user, tenant_id, require_admin=True)
    service = _build_service(db)
    config = await service.upsert_config(
        tenant_id,
        smtp_host=body.smtp_host,
        smtp_port=body.smtp_port,
        smtp_username=body.smtp_username,
        smtp_password=body.smtp_password,
        from_email=body.from_email,
        from_name=body.from_name,
        use_tls=body.use_tls,
    )
    await db.commit()
    return SmtpConfigResponse(
        id=config.id,
        tenant_id=config.tenant_id,
        smtp_host=config.smtp_host,
        smtp_port=config.smtp_port,
        smtp_username=config.smtp_username,
        smtp_password_masked=mask_password(config.smtp_password_encrypted),
        from_email=config.from_email,
        from_name=config.from_name,
        use_tls=config.use_tls,
    )


@router.delete("", status_code=204)
async def delete_smtp_config(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_tenant_access(db, current_user, tenant_id, require_admin=True)
    service = _build_service(db)
    config = await service.get_config(tenant_id)
    if config is None:
        raise HTTPException(status_code=404, detail=_("SMTP config not found"))
    await service.delete_config(config.id)
    await db.commit()


@router.post("/test", status_code=200)
async def test_smtp_config(
    tenant_id: str,
    body: SmtpTestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await _require_tenant_access(db, current_user, tenant_id, require_admin=True)
    service = _build_service(db)
    try:
        await service.test_smtp(tenant_id, body.recipient_email)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=_(f"SMTP test failed: {exc}"),
        ) from exc
    return {"message": "Test email sent successfully"}
