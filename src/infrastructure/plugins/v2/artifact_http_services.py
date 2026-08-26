"""Generation-owned persistence and application seams for Artifact HTTP routes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeGuard, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.artifact_content_authority_service import (
    ArtifactContentAuthorityService,
    ArtifactContentDownload,
    ArtifactContentSaveOutcome,
)
from src.application.services.artifact_service import ArtifactService
from src.domain.ports.repositories.artifact_content_authority_repository import (
    ArtifactContentScope,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import UserProject

from .artifact_content_persistence import ArtifactContentCommitReconcilerProtocolV2
from .artifact_content_services import (
    ArtifactContentApplicationResolverProtocolV2,
)
from .artifact_lifecycle_services import ArtifactLifecycleApplicationServiceV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

logger = logging.getLogger(__name__)

ARTIFACT_HTTP_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/artifact-http-provider"
ARTIFACT_HTTP_PROVIDER_SERVICE_V2 = "service:persistence.artifact-http-provider"
ARTIFACT_HTTP_APPLICATION_MODULE_V2 = "builtin://memstack/application/artifact-http-services"
ARTIFACT_HTTP_APPLICATION_SERVICE_V2 = "service:application.artifact-http-services"
ARTIFACT_HTTP_APPLICATION_PROVIDER_INJECT_V2 = "provider"
ARTIFACT_HTTP_APPLICATION_LIFECYCLE_INJECT_V2 = "lifecycle"
ARTIFACT_HTTP_APPLICATION_CONTENT_INJECT_V2 = "content"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"
_OPERATION_IDENTITY_SERVICE_V2 = "service:operation.identity"


class ArtifactHttpServiceErrorV2(Exception):
    """Base class for typed Artifact HTTP application failures."""


class ArtifactProjectAccessDeniedV2(ArtifactHttpServiceErrorV2):
    """The operation identity cannot access the requested project."""


@runtime_checkable
class ArtifactProjectAccessProtocolV2(Protocol):
    """Authorize one project against the operation identity."""

    async def require_project_access(
        self,
        *,
        project_id: str,
        user_id: str,
        is_superuser: bool,
    ) -> None: ...


@runtime_checkable
class ArtifactRequestTransactionProtocolV2(Protocol):
    """Commit or roll back the operation-owned persistence transaction."""

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


@dataclass(frozen=True, kw_only=True)
class SqlArtifactProjectAccessV2:
    """SQL membership checks bound to one operation-owned session."""

    _session: AsyncSession

    async def require_project_access(
        self,
        *,
        project_id: str,
        user_id: str,
        is_superuser: bool,
    ) -> None:
        if is_superuser:
            return
        result = await self._session.execute(
            refresh_select_statement(
                select(UserProject.id).where(
                    UserProject.user_id == user_id,
                    UserProject.project_id == project_id,
                )
            )
        )
        if result.scalar_one_or_none() is None:
            raise ArtifactProjectAccessDeniedV2


@dataclass(frozen=True, kw_only=True)
class SqlArtifactRequestTransactionV2:
    """Transaction seam backed by the same operation-owned SQL session."""

    _session: AsyncSession

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


@dataclass(frozen=True, kw_only=True)
class ArtifactHttpPersistenceServicesV2:
    """Persistence-neutral request resources selected by one Provider."""

    access: ArtifactProjectAccessProtocolV2
    transaction: ArtifactRequestTransactionProtocolV2


@runtime_checkable
class ArtifactHttpPersistenceFactoryProtocolV2(Protocol):
    """Build Artifact HTTP persistence from an operation-owned session."""

    def build(self, operation: OperationContextV2) -> ArtifactHttpPersistenceServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlArtifactHttpPersistenceFactoryV2:
    """Trusted SQL Provider selected only by the active Profile."""

    def build(self, operation: OperationContextV2) -> ArtifactHttpPersistenceServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "Artifact HTTP services require an AsyncSession operation service",
            )
        return ArtifactHttpPersistenceServicesV2(
            access=SqlArtifactProjectAccessV2(_session=db),
            transaction=SqlArtifactRequestTransactionV2(_session=db),
        )


@dataclass(frozen=True, kw_only=True)
class ArtifactHttpApplicationServicesV2:
    """Complete Artifact HTTP behavior for one pinned request operation."""

    artifacts: ArtifactService
    content: ArtifactContentAuthorityService
    reconciler: ArtifactContentCommitReconcilerProtocolV2
    access: ArtifactProjectAccessProtocolV2
    transaction: ArtifactRequestTransactionProtocolV2
    user_id: str
    is_superuser: bool

    async def require_project_access(self, project_id: str) -> None:
        await self.access.require_project_access(
            project_id=project_id,
            user_id=self.user_id,
            is_superuser=self.is_superuser,
        )

    async def resolve_content_scope(self, artifact_id: str) -> ArtifactContentScope | None:
        scope = await self.content.resolve_scope(artifact_id)
        if scope is not None:
            await self.require_project_access(scope.project_id)
        return scope

    async def commit(self) -> None:
        await self.transaction.commit()

    async def rollback(self) -> None:
        await self.transaction.rollback()

    async def commit_staged_download(
        self,
        download: ArtifactContentDownload,
    ) -> ArtifactContentDownload:
        try:
            commit_error, cancellation = await _settle_artifact_side_effect(
                self.transaction.commit()
            )
            if cancellation is not None:
                raise cancellation
            if commit_error is not None:
                raise commit_error
        except BaseException:
            discard_error, _discard_cancellation = await _settle_artifact_side_effect(
                download.discard()
            )
            if discard_error is not None:
                logger.warning(
                    "Failed to discard staged Artifact download",
                    exc_info=(
                        type(discard_error),
                        discard_error,
                        discard_error.__traceback__,
                    ),
                )
            raise
        return download

    async def commit_content_outcome(self, outcome: ArtifactContentSaveOutcome) -> None:
        commit_error, cancellation = await _settle_artifact_side_effect(self.transaction.commit())
        if commit_error is not None:
            if isinstance(commit_error, asyncio.CancelledError):
                logger.warning(
                    "Artifact content commit was cancelled after dispatch",
                    exc_info=(type(commit_error), commit_error, commit_error.__traceback__),
                )
            else:
                logger.error(
                    "Artifact content request transaction commit failed",
                    exc_info=(type(commit_error), commit_error, commit_error.__traceback__),
                )
            rollback_error, rollback_cancellation = await _settle_artifact_side_effect(
                self.transaction.rollback()
            )
            cancellation = cancellation or rollback_cancellation
            if rollback_error is not None:
                logger.warning(
                    "Failed request transaction rollback before Artifact reconciliation",
                    exc_info=(
                        type(rollback_error),
                        rollback_error,
                        rollback_error.__traceback__,
                    ),
                )
            reconcile_error, reconcile_cancellation = await _settle_artifact_side_effect(
                self.reconciler.reconcile(outcome)
            )
            cancellation = cancellation or reconcile_cancellation
            if reconcile_error is not None:
                logger.error(
                    "Failed Artifact reconciliation after request transaction failure",
                    exc_info=(
                        type(reconcile_error),
                        reconcile_error,
                        reconcile_error.__traceback__,
                    ),
                )
        if cancellation is not None:
            raise cancellation
        if commit_error is not None:
            raise commit_error


@runtime_checkable
class ArtifactHttpApplicationResolverProtocolV2(Protocol):
    """Resolve complete Artifact HTTP services through Profile aliases."""

    def resolve(self, operation: OperationContextV2) -> ArtifactHttpApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class ArtifactHttpApplicationResolverV2:
    """Consumer that never imports or selects concrete persistence implementations."""

    provider: ArtifactHttpPersistenceFactoryProtocolV2
    lifecycle: ArtifactLifecycleApplicationServiceV2
    content: ArtifactContentApplicationResolverProtocolV2

    def resolve(self, operation: OperationContextV2) -> ArtifactHttpApplicationServicesV2:
        identity = operation.require(_OPERATION_IDENTITY_SERVICE_V2)
        if not _is_object_mapping_v2(identity):
            raise RuntimeV2Error(
                "invalid_operation_identity",
                "Artifact HTTP services require a structured operation identity",
            )
        user_id = identity.get("user_id")
        is_superuser = identity.get("is_superuser")
        if not isinstance(user_id, str) or not user_id or not isinstance(is_superuser, bool):
            raise RuntimeV2Error(
                "invalid_operation_identity",
                "Artifact HTTP services require user_id and is_superuser identity fields",
            )
        persistence = self.provider.build(operation)
        content = self.content.resolve(operation)
        return ArtifactHttpApplicationServicesV2(
            artifacts=self.lifecycle.artifact,
            content=content.content,
            reconciler=content.reconciler,
            access=persistence.access,
            transaction=persistence.transaction,
            user_id=user_id,
            is_superuser=is_superuser,
        )


async def _settle_artifact_side_effect(
    operation: Awaitable[None],
) -> tuple[BaseException | None, asyncio.CancelledError | None]:
    """Observe a side effect to a definitive outcome without losing cancellation."""
    task = asyncio.ensure_future(operation)
    caller_cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if task.cancelled():
                return exc, caller_cancellation or exc
            caller_cancellation = caller_cancellation or exc
        except BaseException as exc:
            return exc, caller_cancellation
    if task.cancelled():
        cancelled = asyncio.CancelledError()
        return cancelled, caller_cancellation or cancelled
    return task.exception(), caller_cancellation


def _is_object_mapping_v2(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


def artifact_http_persistence_provider_definition_v2() -> PluginDefinitionV2:
    """Publish the SQL Provider without exposing it to HTTP handlers."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "operation-async-session":
            raise ValueError("Artifact HTTP provider requires strategy operation-async-session")
        _ = context.provide(
            ARTIFACT_HTTP_PROVIDER_SERVICE_V2,
            SqlArtifactHttpPersistenceFactoryV2(),
            label="artifact-http-provider",
        )

    return PluginDefinitionV2(
        module_ref=ARTIFACT_HTTP_PROVIDER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ARTIFACT_HTTP_PROVIDER_MODULE_V2),
        apply=apply,
    )


def artifact_http_application_definition_v2() -> PluginDefinitionV2:
    """Publish the Artifact HTTP Consumer through explicit service aliases."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "operation-scoped-provider":
            raise ValueError(
                "Artifact HTTP application resolver requires strategy operation-scoped-provider"
            )
        provider = context.require(ARTIFACT_HTTP_APPLICATION_PROVIDER_INJECT_V2)
        lifecycle = context.require(ARTIFACT_HTTP_APPLICATION_LIFECYCLE_INJECT_V2)
        content = context.require(ARTIFACT_HTTP_APPLICATION_CONTENT_INJECT_V2)
        if not isinstance(provider, ArtifactHttpPersistenceFactoryProtocolV2):
            raise RuntimeV2Error(
                "invalid_artifact_http_provider",
                "Artifact HTTP provider inject does not implement the factory contract",
            )
        if not isinstance(lifecycle, ArtifactLifecycleApplicationServiceV2):
            raise RuntimeV2Error(
                "invalid_artifact_http_lifecycle",
                "Artifact HTTP lifecycle inject has an invalid implementation",
            )
        if not isinstance(content, ArtifactContentApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_artifact_http_content",
                "Artifact HTTP content inject has an invalid implementation",
            )
        _ = context.provide(
            ARTIFACT_HTTP_APPLICATION_SERVICE_V2,
            ArtifactHttpApplicationResolverV2(
                provider=provider,
                lifecycle=lifecycle,
                content=content,
            ),
            label="artifact-http-application",
        )

    return PluginDefinitionV2(
        module_ref=ARTIFACT_HTTP_APPLICATION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ARTIFACT_HTTP_APPLICATION_MODULE_V2),
        apply=apply,
    )


def artifact_http_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the Artifact HTTP Provider before its application Consumer."""
    return (
        artifact_http_persistence_provider_definition_v2(),
        artifact_http_application_definition_v2(),
    )


__all__ = [
    "ARTIFACT_HTTP_APPLICATION_CONTENT_INJECT_V2",
    "ARTIFACT_HTTP_APPLICATION_LIFECYCLE_INJECT_V2",
    "ARTIFACT_HTTP_APPLICATION_MODULE_V2",
    "ARTIFACT_HTTP_APPLICATION_PROVIDER_INJECT_V2",
    "ARTIFACT_HTTP_APPLICATION_SERVICE_V2",
    "ARTIFACT_HTTP_PROVIDER_MODULE_V2",
    "ARTIFACT_HTTP_PROVIDER_SERVICE_V2",
    "ArtifactHttpApplicationResolverProtocolV2",
    "ArtifactHttpApplicationResolverV2",
    "ArtifactHttpApplicationServicesV2",
    "ArtifactHttpPersistenceFactoryProtocolV2",
    "ArtifactHttpPersistenceServicesV2",
    "ArtifactHttpServiceErrorV2",
    "ArtifactProjectAccessDeniedV2",
    "ArtifactProjectAccessProtocolV2",
    "ArtifactRequestTransactionProtocolV2",
    "SqlArtifactHttpPersistenceFactoryV2",
    "SqlArtifactProjectAccessV2",
    "SqlArtifactRequestTransactionV2",
    "artifact_http_application_definition_v2",
    "artifact_http_persistence_provider_definition_v2",
    "artifact_http_service_definitions_v2",
]
