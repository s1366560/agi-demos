"""Explicit enrollment plus the existing portable synchronization HTTP contract."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from src.domain.model.knowledge_sync.contracts import KnowledgeSyncError
from src.infrastructure.adapters.primary.web.cloud_knowledge_sync_authority_v2 import (
    cloud_knowledge_sync_application_dependency_v2,
    cloud_knowledge_sync_authority_dependency_v2,
    cloud_knowledge_sync_observation_dependency_v2,
)
from src.infrastructure.adapters.primary.web.cloud_knowledge_sync_generation_v2 import (
    cloud_knowledge_sync_generation_payload_v2,
)
from src.infrastructure.adapters.primary.web.routers.knowledge_sync import (
    create_knowledge_sync_router,
    error_response,
)
from src.infrastructure.plugins.v2.cloud_knowledge_sync_services import CloudKnowledgeSyncServicesV2


class KnowledgeSyncEnrollmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    contract_version: Literal["1.0.0"]
    operation: Literal["enroll"]


def create_cloud_knowledge_sync_router() -> APIRouter:
    router = create_knowledge_sync_router(cloud_knowledge_sync_application_dependency_v2)

    async def enrollment_status(
        authority: CloudKnowledgeSyncServicesV2 = Depends(
            cloud_knowledge_sync_observation_dependency_v2
        ),
    ) -> JSONResponse:
        try:
            return JSONResponse(
                content={
                    **(await authority.enrollment.status()).to_dict(),
                    "generation": cloud_knowledge_sync_generation_payload_v2(),
                }
            )
        except KnowledgeSyncError as error:
            return error_response(error)

    async def enroll_project(
        body: KnowledgeSyncEnrollmentBody,
        authority: CloudKnowledgeSyncServicesV2 = Depends(
            cloud_knowledge_sync_authority_dependency_v2
        ),
    ) -> JSONResponse:
        del body  # FastAPI validates the explicit command before admission.
        try:
            result = await authority.enrollment.bootstrap()
            await authority.sync.commit()
            return JSONResponse(
                content={
                    **result.to_dict(),
                    "generation": cloud_knowledge_sync_generation_payload_v2(),
                }
            )
        except KnowledgeSyncError as error:
            return error_response(error)

    router.add_api_route("/enrollment", enrollment_status, methods=["GET"])
    router.add_api_route("/enrollment", enroll_project, methods=["POST"])
    return router
