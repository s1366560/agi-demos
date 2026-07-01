"""Retrieval store management API."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.retrieval_store_service import (
    RetrievalStoreInUse,
    RetrievalStoreNameConflict,
    RetrievalStoreNotFound,
    RetrievalStoreService,
    RetrievalStoreValidationError,
)
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.sql_retrieval_store_repository import (
    SqlRetrievalStoreRepository,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.retrieval.backend_factory import build_default_retrieval_factory
from src.infrastructure.retrieval.registry import (
    ENV_RETRIEVAL_STORE_ID_PREFIX,
    get_retrieval_backend_registry,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/retrieval-stores", tags=["retrieval-stores"])


class StoreCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    engine_type: str = Field(default="memstack_pgvector")
    connection_config: dict[str, Any] = Field(default_factory=dict)
    index_config: dict[str, Any] = Field(default_factory=dict)


class StoreUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    connection_config: dict[str, Any] | None = None
    index_config: dict[str, Any] | None = None


class StoreTestRequest(BaseModel):
    engine_type: str = Field(default="memstack_pgvector")
    connection_config: dict[str, Any] = Field(default_factory=dict)


def _service(db: AsyncSession) -> RetrievalStoreService:
    return RetrievalStoreService(
        repo=SqlRetrievalStoreRepository(db),
        registry=get_retrieval_backend_registry(),
        factory=build_default_retrieval_factory(),
    )


def _selected_tenant(tenant_id: str | None, fallback_tenant_id: str) -> str:
    return tenant_id or fallback_tenant_id


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RetrievalStoreNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Retrieval store not found"),
        )
    if isinstance(exc, RetrievalStoreNameConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, RetrievalStoreInUse):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, RetrievalStoreValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    logger.exception("Retrieval store operation failed")
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=_("Retrieval store operation failed"),
    )


@router.get("/types")
async def list_store_types(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _ = current_user
    service = _service(db)
    return {"success": True, "data": service.list_store_types()}


@router.post("/test")
async def test_store_raw(
    request: StoreTestRequest,
    tenant_id: str | None = Query(None),
    fallback_tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    selected_tenant = _selected_tenant(tenant_id, fallback_tenant_id)
    await require_tenant_access(db, current_user, selected_tenant, require_admin=True)
    service = _service(db)
    try:
        version = await service.test_connection(
            engine_type=request.engine_type,
            connection_config=request.connection_config,
        )
        return {"success": True, "version": version}
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_store(
    request: StoreCreateRequest,
    tenant_id: str | None = Query(None),
    fallback_tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    selected_tenant = _selected_tenant(tenant_id, fallback_tenant_id)
    await require_tenant_access(db, current_user, selected_tenant, require_admin=True)
    service = _service(db)
    try:
        store = await service.create_store(
            tenant_id=selected_tenant,
            name=request.name,
            engine_type=request.engine_type,
            connection_config=request.connection_config,
            index_config=request.index_config,
            created_by=current_user.id,
        )
        await db.commit()
        return {
            "success": True,
            "data": (await service.resolve_store_view(selected_tenant, store.id)).to_dict(),
        }
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


@router.get("")
async def list_stores(
    tenant_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    fallback_tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    selected_tenant = _selected_tenant(tenant_id, fallback_tenant_id)
    await require_tenant_access(db, current_user, selected_tenant)
    service = _service(db)
    stores = await service.list_stores(selected_tenant, limit=limit, offset=offset)
    data = [service.env_default_store_view(selected_tenant).to_dict()]
    for store in stores:
        data.append((await service.resolve_store_view(selected_tenant, store.id)).to_dict())
    return {"success": True, "data": data}


@router.get("/{store_id}")
async def get_store(
    store_id: str,
    tenant_id: str | None = Query(None),
    fallback_tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    selected_tenant = _selected_tenant(tenant_id, fallback_tenant_id)
    await require_tenant_access(db, current_user, selected_tenant)
    service = _service(db)
    if store_id.startswith(ENV_RETRIEVAL_STORE_ID_PREFIX):
        return {"success": True, "data": service.env_default_store_view(selected_tenant).to_dict()}
    try:
        return {
            "success": True,
            "data": (await service.resolve_store_view(selected_tenant, store_id)).to_dict(),
        }
    except Exception as exc:
        raise _map_error(exc) from exc


@router.put("/{store_id}")
async def update_store(
    store_id: str,
    request: StoreUpdateRequest,
    tenant_id: str | None = Query(None),
    fallback_tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    selected_tenant = _selected_tenant(tenant_id, fallback_tenant_id)
    await require_tenant_access(db, current_user, selected_tenant, require_admin=True)
    if store_id.startswith(ENV_RETRIEVAL_STORE_ID_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Environment stores are read-only"),
        )
    service = _service(db)
    try:
        store = await service.update_store(
            tenant_id=selected_tenant,
            store_id=store_id,
            name=request.name,
            connection_config=request.connection_config,
            index_config=request.index_config,
        )
        await db.commit()
        return {
            "success": True,
            "data": (await service.resolve_store_view(selected_tenant, store.id)).to_dict(),
        }
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


@router.delete("/{store_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_store(
    store_id: str,
    tenant_id: str | None = Query(None),
    fallback_tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    selected_tenant = _selected_tenant(tenant_id, fallback_tenant_id)
    await require_tenant_access(db, current_user, selected_tenant, require_admin=True)
    if store_id.startswith(ENV_RETRIEVAL_STORE_ID_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Environment stores are read-only"),
        )
    service = _service(db)
    try:
        await service.delete_store(selected_tenant, store_id)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


@router.post("/{store_id}/test")
async def test_store_by_id(
    store_id: str,
    tenant_id: str | None = Query(None),
    fallback_tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    selected_tenant = _selected_tenant(tenant_id, fallback_tenant_id)
    await require_tenant_access(db, current_user, selected_tenant, require_admin=True)
    service = _service(db)
    if store_id.startswith(ENV_RETRIEVAL_STORE_ID_PREFIX):
        version = await service.test_connection(
            engine_type="memstack_pgvector",
            connection_config={"use_default_connection": True},
        )
        return {"success": True, "version": version}
    try:
        store = await service.get_store(selected_tenant, store_id)
        version = await service.test_connection(
            engine_type=store.engine_type,
            connection_config=store.connection_config,
        )
        return {"success": True, "version": version}
    except Exception as exc:
        raise _map_error(exc) from exc
