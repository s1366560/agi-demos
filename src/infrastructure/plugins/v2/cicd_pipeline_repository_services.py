"""Generation-owned persistence seam for CI/CD pipeline runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.sql_cicd_pipeline import (
    SqlCicdPipelineRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

if TYPE_CHECKING:
    from src.application.services.cicd_pipeline_service import CicdPipelineRepositoryProtocol

CICD_PIPELINE_REPOSITORY_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/cicd-pipeline-repository-provider"
)
CICD_PIPELINE_REPOSITORY_PROVIDER_SERVICE_V2 = (
    "service:persistence.cicd-pipeline-repository-provider"
)
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class CicdPipelineRepositoryProviderProtocolV2(Protocol):
    """Build a CI/CD pipeline repository from one operation boundary."""

    def build(self, operation: OperationContextV2) -> CicdPipelineRepositoryProtocol: ...


@dataclass(frozen=True, kw_only=True)
class SqlCicdPipelineRepositoryProviderV2:
    """Construct SQL pipeline repositories from operation-owned sessions."""

    strategy: str

    def build(self, operation: OperationContextV2) -> CicdPipelineRepositoryProtocol:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "CI/CD pipeline repository Provider requires an AsyncSession operation service",
            )
        return SqlCicdPipelineRepository(db)


def _apply_cicd_pipeline_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError(
            "CI/CD pipeline repository Provider requires strategy request-async-session"
        )
    _ = context.provide(
        CICD_PIPELINE_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlCicdPipelineRepositoryProviderV2(strategy=strategy),
        label="cicd-pipeline-repository-provider",
    )


def cicd_pipeline_repository_definition_v2() -> PluginDefinitionV2:
    """Return the CI/CD pipeline persistence Provider definition."""
    return PluginDefinitionV2(
        module_ref=CICD_PIPELINE_REPOSITORY_PROVIDER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(CICD_PIPELINE_REPOSITORY_PROVIDER_MODULE_V2),
        apply=_apply_cicd_pipeline_repository_provider_v2,
    )


__all__ = [
    "CICD_PIPELINE_REPOSITORY_PROVIDER_MODULE_V2",
    "CICD_PIPELINE_REPOSITORY_PROVIDER_SERVICE_V2",
    "CicdPipelineRepositoryProviderProtocolV2",
    "SqlCicdPipelineRepositoryProviderV2",
    "cicd_pipeline_repository_definition_v2",
]
