"""Generation-owned persistence and application seams for attachments."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.attachment_service import AttachmentService
from src.configuration.config import get_settings
from src.domain.model.agent.attachment import Attachment, AttachmentStatus
from src.domain.ports.repositories.attachment_repository import AttachmentRepositoryPort
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import Project, UserProject
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

ATTACHMENT_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/attachment-provider"
ATTACHMENT_PROVIDER_SERVICE_V2 = "service:persistence.attachment-provider"
ATTACHMENT_APPLICATION_MODULE_V2 = "builtin://memstack/application/attachment-services"
ATTACHMENT_APPLICATION_SERVICE_V2 = "service:application.attachment-services"
ATTACHMENT_PROVIDER_INJECT_V2 = "provider"
ATTACHMENT_STORAGE_INJECT_V2 = "storage"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"
_OPERATION_IDENTITY_SERVICE_V2 = "service:operation.identity"


class AttachmentServiceErrorV2(Exception):
    """Base class for typed attachment application failures."""


class AttachmentProjectAccessDeniedV2(AttachmentServiceErrorV2):
    """The operation identity cannot access the requested project."""


class AttachmentNotFoundV2(AttachmentServiceErrorV2):
    """The requested attachment does not exist."""


class AttachmentAccessDeniedV2(AttachmentServiceErrorV2):
    """The attachment tenant does not match the authorized project tenant."""


@runtime_checkable
class AttachmentProjectAccessProtocolV2(Protocol):
    """Resolve authoritative project tenants for one operation identity."""

    async def accessible_project_tenants(
        self,
        *,
        project_ids: frozenset[str],
        user_id: str,
        is_superuser: bool,
    ) -> dict[str, str]: ...


@dataclass(frozen=True, kw_only=True)
class SqlAttachmentProjectAccessV2:
    """SQL project-access queries bound to one operation-owned session."""

    _session: AsyncSession

    async def accessible_project_tenants(
        self,
        *,
        project_ids: frozenset[str],
        user_id: str,
        is_superuser: bool,
    ) -> dict[str, str]:
        if not project_ids:
            return {}

        if is_superuser:
            statement = select(Project.id, Project.tenant_id).where(Project.id.in_(project_ids))
        else:
            statement = (
                select(Project.id, Project.tenant_id)
                .join(UserProject, UserProject.project_id == Project.id)
                .where(
                    and_(
                        UserProject.user_id == user_id,
                        Project.id.in_(project_ids),
                    )
                )
            )
        result = await self._session.execute(refresh_select_statement(statement))
        return {str(project_id): str(tenant_id) for project_id, tenant_id in result.all()}


@dataclass(frozen=True, kw_only=True)
class AttachmentPersistenceServicesV2:
    """Persistence-neutral attachment resources for one operation."""

    attachments: AttachmentRepositoryPort
    access: AttachmentProjectAccessProtocolV2


@runtime_checkable
class AttachmentPersistenceFactoryProtocolV2(Protocol):
    """Build attachment persistence from an operation-owned DB session."""

    def build(self, operation: OperationContextV2) -> AttachmentPersistenceServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlAttachmentPersistenceFactoryV2:
    """Trusted SQL Provider selected only by the active Profile."""

    def build(self, operation: OperationContextV2) -> AttachmentPersistenceServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "attachment services require an AsyncSession operation service",
            )
        return AttachmentPersistenceServicesV2(
            attachments=SqlAttachmentRepository(db),
            access=SqlAttachmentProjectAccessV2(_session=db),
        )


@dataclass(frozen=True, kw_only=True)
class AttachmentApplicationServiceV2:
    """Attachment behavior and access policy for one pinned HTTP operation."""

    service: AttachmentService
    access: AttachmentProjectAccessProtocolV2
    user_id: str
    is_superuser: bool

    async def require_project_tenant(self, project_id: str) -> str:
        project_tenants = await self.access.accessible_project_tenants(
            project_ids=frozenset({project_id}),
            user_id=self.user_id,
            is_superuser=self.is_superuser,
        )
        tenant_id = project_tenants.get(project_id)
        if tenant_id is None:
            raise AttachmentProjectAccessDeniedV2
        return tenant_id

    async def get_authorized(self, attachment_id: str) -> Attachment:
        attachment = await self.service.get(attachment_id)
        if attachment is None:
            raise AttachmentNotFoundV2
        project_tenant_id = await self.require_project_tenant(attachment.project_id)
        if attachment.tenant_id != project_tenant_id:
            raise AttachmentAccessDeniedV2
        return attachment

    async def list_visible(
        self,
        *,
        conversation_id: str,
        status: AttachmentStatus | None,
    ) -> list[Attachment]:
        attachments = await self.service.get_by_conversation(
            conversation_id=conversation_id,
            status=status,
        )
        project_tenants = await self.access.accessible_project_tenants(
            project_ids=frozenset(attachment.project_id for attachment in attachments),
            user_id=self.user_id,
            is_superuser=self.is_superuser,
        )
        return [
            attachment
            for attachment in attachments
            if project_tenants.get(attachment.project_id) == attachment.tenant_id
        ]


@dataclass(frozen=True, kw_only=True)
class AttachmentApplicationServicesV2:
    """Operation-owned attachment seam consumed by HTTP handlers."""

    attachments: AttachmentApplicationServiceV2


@runtime_checkable
class AttachmentApplicationResolverProtocolV2(Protocol):
    """Resolve attachment services through Profile-declared aliases."""

    def resolve(self, operation: OperationContextV2) -> AttachmentApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class AttachmentApplicationResolverV2:
    """Consumer that never imports or selects a concrete persistence Provider."""

    provider: AttachmentPersistenceFactoryProtocolV2
    storage: ObjectStorageServiceV2
    upload_max_size_llm_mb: int
    upload_max_size_sandbox_mb: int

    def resolve(self, operation: OperationContextV2) -> AttachmentApplicationServicesV2:
        identity = operation.require(_OPERATION_IDENTITY_SERVICE_V2)
        if not isinstance(identity, Mapping):
            raise RuntimeV2Error(
                "invalid_operation_identity",
                "attachment services require a structured operation identity",
            )
        identity_values = cast(Mapping[str, object], identity)
        user_id = identity_values.get("user_id")
        is_superuser = identity_values.get("is_superuser")
        if not isinstance(user_id, str) or not user_id or not isinstance(is_superuser, bool):
            raise RuntimeV2Error(
                "invalid_operation_identity",
                "attachment services require user_id and is_superuser identity fields",
            )
        persistence = self.provider.build(operation)
        service = AttachmentService(
            storage_service=self.storage.storage_service,
            attachment_repository=persistence.attachments,
            upload_max_size_llm_mb=self.upload_max_size_llm_mb,
            upload_max_size_sandbox_mb=self.upload_max_size_sandbox_mb,
        )
        return AttachmentApplicationServicesV2(
            attachments=AttachmentApplicationServiceV2(
                service=service,
                access=persistence.access,
                user_id=user_id,
                is_superuser=is_superuser,
            )
        )


def attachment_persistence_provider_definition_v2() -> PluginDefinitionV2:
    """Publish the SQL Provider without exposing it to HTTP handlers."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "operation-async-session":
            raise ValueError("attachment provider requires strategy operation-async-session")
        _ = context.provide(
            ATTACHMENT_PROVIDER_SERVICE_V2,
            SqlAttachmentPersistenceFactoryV2(),
            label="attachment-provider",
        )

    return PluginDefinitionV2(
        module_ref=ATTACHMENT_PROVIDER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ATTACHMENT_PROVIDER_MODULE_V2),
        apply=apply,
    )


def attachment_application_service_definition_v2() -> PluginDefinitionV2:
    """Publish the attachment Consumer through explicit Provider and storage aliases."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "operation-scoped-provider":
            raise ValueError(
                "attachment application resolver requires strategy operation-scoped-provider"
            )
        if config.get("limits_from_settings") is not True:
            raise ValueError("attachment application resolver requires limits_from_settings")
        provider = context.require(ATTACHMENT_PROVIDER_INJECT_V2)
        storage = context.require(ATTACHMENT_STORAGE_INJECT_V2)
        if not isinstance(provider, AttachmentPersistenceFactoryProtocolV2):
            raise RuntimeV2Error(
                "invalid_attachment_provider",
                "attachment provider inject does not implement the factory contract",
            )
        if not isinstance(storage, ObjectStorageServiceV2):
            raise RuntimeV2Error(
                "invalid_attachment_storage",
                "attachment storage inject has an invalid implementation",
            )
        settings = get_settings()
        _ = context.provide(
            ATTACHMENT_APPLICATION_SERVICE_V2,
            AttachmentApplicationResolverV2(
                provider=provider,
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


def attachment_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the Provider before its application Consumer."""
    return (
        attachment_persistence_provider_definition_v2(),
        attachment_application_service_definition_v2(),
    )


__all__ = [
    "ATTACHMENT_APPLICATION_MODULE_V2",
    "ATTACHMENT_APPLICATION_SERVICE_V2",
    "ATTACHMENT_PROVIDER_INJECT_V2",
    "ATTACHMENT_PROVIDER_MODULE_V2",
    "ATTACHMENT_PROVIDER_SERVICE_V2",
    "ATTACHMENT_STORAGE_INJECT_V2",
    "AttachmentAccessDeniedV2",
    "AttachmentApplicationResolverProtocolV2",
    "AttachmentApplicationResolverV2",
    "AttachmentApplicationServiceV2",
    "AttachmentApplicationServicesV2",
    "AttachmentNotFoundV2",
    "AttachmentPersistenceFactoryProtocolV2",
    "AttachmentPersistenceServicesV2",
    "AttachmentProjectAccessDeniedV2",
    "AttachmentProjectAccessProtocolV2",
    "AttachmentServiceErrorV2",
    "SqlAttachmentPersistenceFactoryV2",
    "SqlAttachmentProjectAccessV2",
    "attachment_application_service_definition_v2",
    "attachment_persistence_provider_definition_v2",
    "attachment_service_definitions_v2",
]
