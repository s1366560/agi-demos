"""Ordinary-chat CI/CD pipeline orchestration."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import CicdPipelineRunModel
from src.infrastructure.adapters.secondary.persistence.plugin_config_repository import (
    PluginConfigRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_cicd_pipeline import (
    SqlCicdPipelineRepository,
)
from src.infrastructure.agent.workspace_plan.pipeline import (
    DRONE_PROVIDER,
    PipelineContractSpec,
    PipelineRunResult,
)
from src.infrastructure.agent.workspace_plan.pipeline_provider_registry import (
    PipelineProviderUnavailableError,
    require_pipeline_provider,
)

DRONE_PLUGIN_NAME = "drone-pipeline-plugin"


class CicdPipelineError(ValueError):
    """Raised when an ordinary chat cannot run CI/CD."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "cicd_pipeline_error",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.metadata = dict(metadata or {})


@dataclass(frozen=True)
class CicdPipelineRunRequest:
    """Input for ordinary-chat CI/CD execution."""

    conversation_id: str
    project_id: str
    tenant_id: str
    user_id: str
    repository: str | None = None
    provider: str = DRONE_PROVIDER
    branch: str | None = None
    commit: str | None = None
    target: str | None = None
    params: Mapping[str, str] | None = None
    wait: bool = True
    reason: str | None = None


@dataclass(frozen=True)
class CicdPipelineRunSummary:
    """Structured summary returned to the agent tool."""

    provider: str
    repository: str
    run_id: str
    status: str
    reason: str | None
    evidence_refs: tuple[str, ...]
    branch: str | None = None
    commit: str | None = None
    external_id: str | None = None
    external_url: str | None = None
    preview_url: str | None = None
    health_url: str | None = None
    stage_count: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "repository": self.repository,
            "run_id": self.run_id,
            "status": self.status,
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
            "branch": self.branch,
            "commit": self.commit,
            "external_id": self.external_id,
            "external_url": self.external_url,
            "preview_url": self.preview_url,
            "health_url": self.health_url,
            "stage_count": self.stage_count,
        }


class PipelineProvider(Protocol):
    def run(self, contract: PipelineContractSpec) -> Awaitable[PipelineRunResult]: ...


PipelineProviderFactory = Callable[[], PipelineProvider | Awaitable[PipelineProvider]]


class CicdPipelineService:
    """Runs configured repository CI/CD from ordinary chat turns."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        provider_factory: PipelineProviderFactory | None = None,
    ) -> None:
        self._session = session
        self._pipeline_repo = SqlCicdPipelineRepository(session)
        self._provider_factory = provider_factory

    async def run_pipeline(self, request: CicdPipelineRunRequest) -> CicdPipelineRunSummary:
        provider = _normalize_provider(request.provider)
        if provider != DRONE_PROVIDER:
            raise CicdPipelineError(
                f"Unsupported CI/CD provider: {request.provider}",
                code="unsupported_provider",
                metadata={"provider": request.provider},
            )
        if not request.wait:
            raise CicdPipelineError(
                "Asynchronous CI/CD trigger is not available from ordinary chat yet; use wait=true.",
                code="async_trigger_unsupported",
            )

        repository = _normalize_repository(request.repository)
        if repository is None:
            raise CicdPipelineError(
                "Repository is required for ordinary chat CI/CD. Use '<owner>/<repo>'.",
                code="repo_required",
            )

        contract = self._contract_for_repository(repository=repository, request=request)
        contract = await self._merge_tenant_plugin_config(contract, request)
        run = await self._pipeline_repo.create_run(
            tenant_id=request.tenant_id,
            project_id=request.project_id,
            conversation_id=request.conversation_id,
            provider=contract.provider,
            repository=repository,
            branch=_contract_branch(contract),
            commit_ref=_commit_ref(contract),
            metadata={
                "source": "ordinary_chat.cicd_run_pipeline",
                "reason": request.reason or "ordinary_chat_cicd_request",
                "provider_config": _redacted_provider_config(contract.provider_config),
            },
        )
        await self._session.flush()

        provider_impl = await self._provider_for(contract.provider)
        result = await provider_impl.run(contract)
        evidence_refs = await self._persist_result(run=run, contract=contract, result=result)
        await self._session.commit()
        return CicdPipelineRunSummary(
            provider=contract.provider,
            repository=repository,
            run_id=run.id,
            status=result.status,
            reason=_result_summary(result),
            evidence_refs=tuple(evidence_refs),
            branch=_contract_branch(contract),
            commit=_contract_commit(contract),
            external_id=result.external_id,
            external_url=result.external_url,
            preview_url=result.preview_url,
            health_url=result.health_url,
            stage_count=len(result.stage_results),
        )

    async def _provider_for(self, provider: str) -> PipelineProvider:
        if self._provider_factory is not None:
            resolved = self._provider_factory()
            if inspect.isawaitable(resolved):
                resolved = await resolved
            return resolved
        try:
            return await require_pipeline_provider(provider)
        except PipelineProviderUnavailableError as exc:
            raise CicdPipelineError(
                str(exc),
                code="pipeline_provider_plugin_disabled",
                metadata={"provider": exc.provider},
            ) from exc

    def _contract_for_repository(
        self,
        *,
        repository: str,
        request: CicdPipelineRunRequest,
    ) -> PipelineContractSpec:
        provider_config: dict[str, Any] = {"repo": repository}
        if request.branch:
            provider_config["branch"] = request.branch
        if request.commit:
            provider_config["commit"] = request.commit
        if request.target:
            provider_config["target"] = request.target
        if request.params:
            provider_config["params"] = {
                str(key): str(value) for key, value in request.params.items()
            }
        return PipelineContractSpec(
            provider=DRONE_PROVIDER,
            auto_deploy=False,
            agent_managed=False,
            contract_source="ordinary_chat.tool_args",
            contract_confidence=1.0,
            provider_config=provider_config,
        )

    async def _merge_tenant_plugin_config(
        self,
        contract: PipelineContractSpec,
        request: CicdPipelineRunRequest,
    ) -> PipelineContractSpec:
        if contract.provider != DRONE_PROVIDER:
            return contract
        plugin_config = await PluginConfigRepository(self._session).get_by_tenant_and_plugin(
            request.tenant_id, DRONE_PLUGIN_NAME
        )
        if plugin_config is None:
            return contract
        provider_config = {
            **dict(plugin_config.config),
            **dict(contract.provider_config or {}),
        }
        return replace(contract, provider_config=provider_config)

    async def _persist_result(
        self,
        *,
        run: CicdPipelineRunModel,
        contract: PipelineContractSpec,
        result: PipelineRunResult,
    ) -> list[str]:
        for stage_result in result.stage_results:
            stage_run = await self._pipeline_repo.create_stage_run(
                run_id=run.id,
                stage=stage_result.stage,
                command=stage_result.command,
                metadata={"provider": contract.provider, **dict(stage_result.metadata or {})},
            )
            _ = await self._pipeline_repo.finish_stage_run(
                stage_run,
                status=stage_result.status,
                exit_code=stage_result.exit_code,
                stdout_preview=stage_result.stdout_preview,
                stderr_preview=stage_result.stderr_preview,
                log_ref=stage_result.log_ref,
                artifact_refs=list(stage_result.artifact_refs),
                duration_ms=stage_result.duration_ms,
                metadata=dict(stage_result.metadata or {}),
            )

        summary = _result_summary(result)
        _ = await self._pipeline_repo.finish_run(
            run,
            status=result.status,
            reason=summary,
            external_id=result.external_id,
            external_url=result.external_url,
            metadata={
                "stage_count": len(result.stage_results),
                "external_id": result.external_id,
                "external_url": result.external_url,
                "deployment_status": result.deployment_status,
                "pipeline_last_summary": summary,
                **dict(result.metadata or {}),
            },
        )
        evidence_refs = list(result.evidence_refs)
        evidence_refs.append(f"pipeline_run:{result.status}:{run.id}")
        if result.external_id:
            evidence_refs.append(f"pipeline_run_external:{contract.provider}:{result.external_id}")
        return list(dict.fromkeys(evidence_refs))


def _normalize_provider(provider: str | None) -> str:
    return (provider or DRONE_PROVIDER).strip().lower().replace("-", "_")


def _strip(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_repository(repository: str | None) -> str | None:
    value = _strip(repository)
    if value is None:
        return None
    parts = value.split("/")
    if len(parts) != 2:
        return None
    owner, repo = parts
    owner = owner.strip()
    repo = repo.strip()
    if not owner or not repo:
        return None
    return f"{owner}/{repo}"


def _commit_ref(contract: PipelineContractSpec) -> str | None:
    value = contract.provider_config.get("commit") or contract.provider_config.get("branch")
    return str(value).strip() if value else None


def _contract_branch(contract: PipelineContractSpec) -> str | None:
    value = contract.provider_config.get("branch")
    return str(value).strip() if value else None


def _contract_commit(contract: PipelineContractSpec) -> str | None:
    value = contract.provider_config.get("commit")
    return str(value).strip() if value else None


def _result_summary(result: PipelineRunResult) -> str | None:
    if result.reason:
        return result.reason
    failed = next((stage for stage in result.stage_results if not stage.passed), None)
    if failed is not None:
        return failed.stderr_preview or failed.stdout_preview or f"{failed.stage} failed"
    return f"Pipeline {result.status}"


def _redacted_provider_config(provider_config: Mapping[str, Any]) -> dict[str, Any]:
    redacted = dict(provider_config)
    for key in ("token", "drone_token", "access_token"):
        if key in redacted:
            redacted[key] = "__REDACTED__"
    return redacted


__all__ = [
    "CicdPipelineError",
    "CicdPipelineRunRequest",
    "CicdPipelineRunSummary",
    "CicdPipelineService",
]
