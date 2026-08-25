"""Generation-owned attachment application service seam."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.attachment_service import AttachmentService
from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.sql_attachment_repository import (
    SqlAttachmentRepository,
)

from .artifact_content_gc_runtime import ObjectStorageServiceV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

ATTACHMENT_APPLICATION_MODULE_V2 = "builtin://memstack/application/attachment-services"
ATTACHMENT_APPLICATION_SERVICE_V2 = "service:application.attachment-services"
ATTACHMENT_STORAGE_INJECT_V2 = "storage"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class AttachmentApplicationResolverProtocolV2(Protocol):
    """Build one attachment service from the active operation boundary."""

    def resolve(self, operation: OperationContextV2) -> AttachmentService: ...


@dataclass(frozen=True, kw_only=True)
class AttachmentApplicationResolverV2:
    """Bind generation-owned storage to an operation-owned SQL repository."""

    storage: ObjectStorageServiceV2
    upload_max_size_llm_mb: int
    upload_max_size_sandbox_mb: int

    def resolve(self, operation: OperationContextV2) -> AttachmentService:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "attachment services require an AsyncSession operation service",
            )
        return AttachmentService(
            storage_service=self.storage.storage_service,
            attachment_repository=SqlAttachmentRepository(db),
            upload_max_size_llm_mb=self.upload_max_size_llm_mb,
            upload_max_size_sandbox_mb=self.upload_max_size_sandbox_mb,
        )


def attachment_application_service_definition_v2() -> PluginDefinitionV2:
    """Publish the attachment resolver through an explicit storage alias."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "operation-scoped-provider":
            raise ValueError(
                "attachment application resolver requires strategy operation-scoped-provider"
            )
        if config.get("limits_from_settings") is not True:
            raise ValueError("attachment application resolver requires limits_from_settings")
        storage = context.require(ATTACHMENT_STORAGE_INJECT_V2)
        if not isinstance(storage, ObjectStorageServiceV2):
            raise RuntimeV2Error(
                "invalid_attachment_storage",
                "attachment storage inject has an invalid implementation",
            )
        settings = get_settings()
        _ = context.provide(
            ATTACHMENT_APPLICATION_SERVICE_V2,
            AttachmentApplicationResolverV2(
                storage=storage,
                upload_max_size_llm_mb=settings.upload_max_size_llm_mb,
                upload_max_size_sandbox_mb=settings.upload_max_size_sandbox_mb,
            ),
            label="attachment-application",
        )

    return PluginDefinitionV2(
        module_ref=ATTACHMENT_APPLICATION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ATTACHMENT_APPLICATION_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "ATTACHMENT_APPLICATION_MODULE_V2",
    "ATTACHMENT_APPLICATION_SERVICE_V2",
    "ATTACHMENT_STORAGE_INJECT_V2",
    "AttachmentApplicationResolverProtocolV2",
    "AttachmentApplicationResolverV2",
    "attachment_application_service_definition_v2",
]
