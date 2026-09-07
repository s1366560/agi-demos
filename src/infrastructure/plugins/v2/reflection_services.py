"""Generation-owned reflection repository Provider and application Consumer seams."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.repositories.playbook_repository import PlaybookRepository
from src.domain.ports.repositories.reflection_verdict_repository import (
    ReflectionVerdictRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import UserProject
from src.infrastructure.adapters.secondary.persistence.sql_playbook_repository import (
    SqlPlaybookRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_reflection_verdict_repository import (
    SqlReflectionVerdictRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

REFLECTION_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/reflection-provider"
REFLECTION_PROVIDER_SERVICE_V2 = "service:persistence.reflection-provider"
REFLECTION_APPLICATION_MODULE_V2 = "builtin://memstack/application/reflection-services"
REFLECTION_APPLICATION_SERVICE_V2 = "service:application.reflection-services"
REFLECTION_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class ProjectMembershipReaderProtocolV2(Protocol):
    """Read the structural project membership relation for authorization."""

    async def contains(self, *, user_id: str, project_id: str) -> bool: ...


@dataclass(frozen=True, kw_only=True)
class SqlProjectMembershipReaderV2:
    """SQL membership reader hidden behind the reflection Provider seam."""

    _session: AsyncSession

    async def contains(self, *, user_id: str, project_id: str) -> bool:
        result = await self._session.execute(
            refresh_select_statement(
                select(UserProject).where(
                    and_(
                        UserProject.user_id == user_id,
                        UserProject.project_id == project_id,
                    )
                )
            )
        )
        return result.scalar_one_or_none() is not None


@dataclass(frozen=True, kw_only=True)
class ReflectionApplicationServicesV2:
    """One operation-owned reflection read service set."""

    membership: ProjectMembershipReaderProtocolV2
    playbooks: PlaybookRepository
    verdicts: ReflectionVerdictRepository


@runtime_checkable
class ReflectionServiceFactoryProtocolV2(Protocol):
    """Provider contract hiding concrete persistence implementations."""

    def build(self, operation: OperationContextV2) -> ReflectionApplicationServicesV2: ...


@runtime_checkable
class ReflectionApplicationResolverProtocolV2(Protocol):
    """Application-facing resolver injected through a declared service alias."""

    def resolve(self, operation: OperationContextV2) -> ReflectionApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlReflectionServiceFactoryV2:
    """Build reflection services from the operation's exact AsyncSession."""

    strategy: str

    def build(self, operation: OperationContextV2) -> ReflectionApplicationServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "reflection services require an AsyncSession operation service",
            )
        return ReflectionApplicationServicesV2(
            membership=SqlProjectMembershipReaderV2(_session=db),
            playbooks=SqlPlaybookRepository(db),
            verdicts=SqlReflectionVerdictRepository(db),
        )


@dataclass(frozen=True, kw_only=True)
class ReflectionApplicationResolverV2:
    """Resolve operation-owned services without exposing the Provider implementation."""

    provider: ReflectionServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> ReflectionApplicationServicesV2:
        return self.provider.build(operation)


def _apply_reflection_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("reflection provider requires strategy request-async-session")
    _ = context.provide(
        REFLECTION_PROVIDER_SERVICE_V2,
        SqlReflectionServiceFactoryV2(strategy=strategy),
        label="reflection-provider",
    )


def _apply_reflection_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "operation-scoped-provider":
        raise ValueError(
            "reflection application resolver requires strategy operation-scoped-provider"
        )
    provider = context.require(REFLECTION_PROVIDER_INJECT_V2)
    if not isinstance(provider, ReflectionServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_reflection_provider",
            "reflection provider inject does not implement the factory contract",
        )
    _ = context.provide(
        REFLECTION_APPLICATION_SERVICE_V2,
        ReflectionApplicationResolverV2(provider=provider),
        label="reflection-application",
    )


def reflection_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    return (
        PluginDefinitionV2(
            module_ref=REFLECTION_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(REFLECTION_PROVIDER_MODULE_V2),
            apply=_apply_reflection_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=REFLECTION_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(REFLECTION_APPLICATION_MODULE_V2),
            apply=_apply_reflection_application_v2,
        ),
    )


__all__ = [
    "REFLECTION_APPLICATION_MODULE_V2",
    "REFLECTION_APPLICATION_SERVICE_V2",
    "REFLECTION_PROVIDER_INJECT_V2",
    "REFLECTION_PROVIDER_MODULE_V2",
    "REFLECTION_PROVIDER_SERVICE_V2",
    "ProjectMembershipReaderProtocolV2",
    "ReflectionApplicationResolverProtocolV2",
    "ReflectionApplicationResolverV2",
    "ReflectionApplicationServicesV2",
    "ReflectionServiceFactoryProtocolV2",
    "SqlProjectMembershipReaderV2",
    "SqlReflectionServiceFactoryV2",
    "reflection_service_definitions_v2",
]
