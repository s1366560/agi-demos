"""Generation-owned persistence, judgment, and application seams for Workspace Context."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.workspace_context import (
    WorkspaceContextAccess,
    WorkspaceContextCandidate,
    WorkspaceContextError,
    WorkspaceContextErrorCode,
    WorkspaceContextSwitchOutcome,
    WorkspaceContextSwitchRequest,
)
from src.domain.ports.repositories.workspace_context_repository import (
    WorkspaceContextRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_desktop_workspace_context_repository import (
    SqlDesktopWorkspaceContextRepository,
)
from src.infrastructure.workspace_core.context_judge import (
    AgentWorkspaceContextJudge,
    WorkspaceContextCandidate as JudgeWorkspaceContextCandidate,
    WorkspaceContextCurrent,
    WorkspaceContextJudgePort,
    WorkspaceContextJudgeRequest,
    WorkspaceContextJudgeUnavailable,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

logger = logging.getLogger(__name__)

WORKSPACE_CONTEXT_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/workspace-context-provider"
WORKSPACE_CONTEXT_PROVIDER_SERVICE_V2 = "service:persistence.workspace-context-provider"
WORKSPACE_CONTEXT_JUDGE_MODULE_V2 = "builtin://memstack/judgment/workspace-context-selector"
WORKSPACE_CONTEXT_JUDGE_SERVICE_V2 = "service:judgment.workspace-context-selector"
WORKSPACE_CONTEXT_APPLICATION_MODULE_V2 = (
    "builtin://memstack/application/workspace-context-services"
)
WORKSPACE_CONTEXT_APPLICATION_SERVICE_V2 = "service:application.workspace-context-services"
WORKSPACE_CONTEXT_PROVIDER_INJECT_V2 = "provider"
WORKSPACE_CONTEXT_JUDGE_INJECT_V2 = "judge"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class WorkspaceContextPersistenceFactoryProtocolV2(Protocol):
    """Build persistence against the request's operation-owned DB session."""

    def build(self, operation: OperationContextV2) -> WorkspaceContextRepository: ...


@dataclass(frozen=True, kw_only=True)
class SqlWorkspaceContextPersistenceFactoryV2:
    """Bind the Workspace Context repository to one exact AsyncSession."""

    def build(self, operation: OperationContextV2) -> WorkspaceContextRepository:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "Workspace Context services require an AsyncSession operation service",
            )
        return SqlDesktopWorkspaceContextRepository(db)


@dataclass(frozen=True, kw_only=True)
class WorkspaceContextApplicationServiceV2:
    """Resolve and mutate Workspace Context without implicit semantic defaults."""

    persistence: WorkspaceContextRepository
    judge: WorkspaceContextJudgePort

    async def get_or_initialize(
        self,
        *,
        user_id: str,
        observed_at: datetime,
    ) -> WorkspaceContextAccess:
        accessible = await self.persistence.get_accessible(user_id)
        if accessible is not None:
            return accessible

        candidates = await self.persistence.list_candidates(user_id)
        if not candidates:
            raise WorkspaceContextError(WorkspaceContextErrorCode.UNAVAILABLE)
        selected = candidates[0] if len(candidates) == 1 else await self._judge(user_id, candidates)
        return await self.persistence.initialize(
            user_id,
            candidate=selected,
            observed_at=observed_at,
        )

    async def switch(
        self,
        *,
        user_id: str,
        actor_api_key_id: str | None,
        request: WorkspaceContextSwitchRequest,
        observed_at: datetime,
    ) -> WorkspaceContextSwitchOutcome:
        return await self.persistence.switch(
            user_id,
            actor_api_key_id=actor_api_key_id,
            request=request,
            observed_at=observed_at,
        )

    async def _judge(
        self,
        user_id: str,
        candidates: tuple[WorkspaceContextCandidate, ...],
    ) -> WorkspaceContextCandidate:
        current = await self.persistence.get_current(user_id)
        request = WorkspaceContextJudgeRequest(
            user_id=user_id,
            current=(
                WorkspaceContextCurrent(
                    tenant_id=current.tenant_id,
                    project_id=current.project_id,
                    revision=current.revision,
                )
                if current is not None
                else None
            ),
            candidates=[
                JudgeWorkspaceContextCandidate(
                    tenant_id=candidate.tenant_id,
                    project_id=candidate.project_id,
                    membership_role=candidate.membership_role,
                )
                for candidate in candidates
            ],
        )
        try:
            verdict = await self.judge.select(request)
        except WorkspaceContextJudgeUnavailable as exc:
            raise WorkspaceContextError(WorkspaceContextErrorCode.UNAVAILABLE) from exc

        logger.info(
            "Workspace Context judgment",
            extra={
                "agent_id": verdict.agent_id,
                "tool_name": verdict.tool_name,
                "input_json": verdict.input_json,
                "output_json": verdict.output_json,
                "rationale": verdict.rationale,
                "latency_ms": verdict.latency_ms,
            },
        )
        selected_key = (
            verdict.selected.tenant_id,
            verdict.selected.project_id,
            verdict.selected.membership_role,
        )
        selected = next(
            (
                candidate
                for candidate in candidates
                if (candidate.tenant_id, candidate.project_id, candidate.membership_role)
                == selected_key
            ),
            None,
        )
        if selected is None:
            raise WorkspaceContextError(WorkspaceContextErrorCode.UNAVAILABLE)
        return selected


@dataclass(frozen=True, kw_only=True)
class WorkspaceContextApplicationServicesV2:
    """Operation-owned Workspace Context seam consumed by HTTP handlers."""

    context: WorkspaceContextApplicationServiceV2


@runtime_checkable
class WorkspaceContextApplicationResolverProtocolV2(Protocol):
    """Resolve application services through Profile-declared aliases."""

    def resolve(self, operation: OperationContextV2) -> WorkspaceContextApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class WorkspaceContextApplicationResolverV2:
    """Consumer that never imports or selects a concrete Provider implementation."""

    provider: WorkspaceContextPersistenceFactoryProtocolV2
    judge: WorkspaceContextJudgePort

    def resolve(self, operation: OperationContextV2) -> WorkspaceContextApplicationServicesV2:
        return WorkspaceContextApplicationServicesV2(
            context=WorkspaceContextApplicationServiceV2(
                persistence=self.provider.build(operation),
                judge=self.judge,
            )
        )


def _apply_workspace_context_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-async-session":
        raise ValueError("Workspace Context provider requires strategy operation-async-session")
    _ = context.provide(
        WORKSPACE_CONTEXT_PROVIDER_SERVICE_V2,
        SqlWorkspaceContextPersistenceFactoryV2(),
        label="workspace-context-provider",
    )


def _apply_workspace_context_judge_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "agent-structured-tool":
        raise ValueError("Workspace Context judge requires strategy agent-structured-tool")
    _ = context.provide(
        WORKSPACE_CONTEXT_JUDGE_SERVICE_V2,
        AgentWorkspaceContextJudge(),
        label="workspace-context-judge",
    )


def _apply_workspace_context_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider-and-judge":
        raise ValueError(
            "Workspace Context resolver requires strategy operation-scoped-provider-and-judge"
        )
    provider = context.require(WORKSPACE_CONTEXT_PROVIDER_INJECT_V2)
    judge = context.require(WORKSPACE_CONTEXT_JUDGE_INJECT_V2)
    if not isinstance(provider, WorkspaceContextPersistenceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_workspace_context_provider",
            "Workspace Context provider inject does not implement the factory contract",
        )
    if not isinstance(judge, WorkspaceContextJudgePort):
        raise RuntimeV2Error(
            "invalid_workspace_context_judge",
            "Workspace Context judge inject does not implement the judgment contract",
        )
    _ = context.provide(
        WORKSPACE_CONTEXT_APPLICATION_SERVICE_V2,
        WorkspaceContextApplicationResolverV2(provider=provider, judge=judge),
        label="workspace-context-application",
    )


def workspace_context_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent persistence, judgment, and application definitions."""
    return (
        PluginDefinitionV2(
            module_ref=WORKSPACE_CONTEXT_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(WORKSPACE_CONTEXT_PROVIDER_MODULE_V2),
            apply=_apply_workspace_context_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=WORKSPACE_CONTEXT_JUDGE_MODULE_V2,
            contract_digest=generated_contract_digest_v2(WORKSPACE_CONTEXT_JUDGE_MODULE_V2),
            apply=_apply_workspace_context_judge_v2,
        ),
        PluginDefinitionV2(
            module_ref=WORKSPACE_CONTEXT_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(WORKSPACE_CONTEXT_APPLICATION_MODULE_V2),
            apply=_apply_workspace_context_application_v2,
        ),
    )


__all__ = [
    "WORKSPACE_CONTEXT_APPLICATION_MODULE_V2",
    "WORKSPACE_CONTEXT_APPLICATION_SERVICE_V2",
    "WORKSPACE_CONTEXT_JUDGE_INJECT_V2",
    "WORKSPACE_CONTEXT_JUDGE_MODULE_V2",
    "WORKSPACE_CONTEXT_JUDGE_SERVICE_V2",
    "WORKSPACE_CONTEXT_PROVIDER_INJECT_V2",
    "WORKSPACE_CONTEXT_PROVIDER_MODULE_V2",
    "WORKSPACE_CONTEXT_PROVIDER_SERVICE_V2",
    "SqlWorkspaceContextPersistenceFactoryV2",
    "WorkspaceContextApplicationResolverProtocolV2",
    "WorkspaceContextApplicationResolverV2",
    "WorkspaceContextApplicationServiceV2",
    "WorkspaceContextApplicationServicesV2",
    "WorkspaceContextPersistenceFactoryProtocolV2",
    "workspace_context_service_definitions_v2",
]
