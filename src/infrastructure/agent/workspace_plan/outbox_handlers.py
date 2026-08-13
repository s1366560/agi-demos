"""Fail-closed boundary for the retired Python Workspace Plan outbox runtime.

Avernet Workspace Core is the sole authority for Plan progression, attempts,
pipelines, and Workspace events.  The historical event constants and handler
factory names remain import-compatible while callers migrate, but invoking a
legacy handler cannot read or mutate platform persistence.

Pure pipeline-formatting helpers remain here temporarily because they are used
by side-effect-free domain tests.  They do not compose persistence or runtime
workers.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

from src.domain.model.workspace_plan import PlanNode, TaskExecution, TaskIntent
from src.infrastructure.agent.tools.workspace_planning_contract import PLANNING_CONTRACT_SOURCE
from src.infrastructure.agent.workspace_plan.pipeline import (
    DRONE_DOCKER_DEPLOY_VALIDATION,
    DRONE_PROVIDER,
    SANDBOX_NATIVE_PROVIDER,
    PipelineContractSpec,
    PipelineRunResult,
    PipelineStageResult,
)

SUPERVISOR_TICK_EVENT = "supervisor_tick"
WORKER_LAUNCH_EVENT = "worker_launch"
HANDOFF_RESUME_EVENT = "handoff_resume"
ATTEMPT_RETRY_EVENT = "attempt_retry"
PIPELINE_RUN_REQUESTED_EVENT = "pipeline_run_requested"
PIPELINE_STAGE_EXECUTE_EVENT = "pipeline_stage_execute"
DEPLOYMENT_REQUESTED_EVENT = "deployment_requested"
DEPLOYMENT_HEALTH_CHECK_EVENT = "deployment_health_check"
PIPELINE_LOGS_SYNC_EVENT = "pipeline_logs_sync"

_AUTO_TEAM_ROLES = (
    {
        "key": "architect",
        "display_name": "Workspace Architect",
        "label": "Architect",
        "description": "Researches requirements and produces architecture or implementation plans.",
        "capabilities": ["architecture", "research", "planning", "web_search"],
    },
    {
        "key": "builder",
        "display_name": "Workspace Builder",
        "label": "Builder",
        "description": "Implements backend, frontend, tests, and project artifacts.",
        "capabilities": [
            "software_development",
            "backend",
            "frontend",
            "codegen",
            "file_edit",
            "shell",
            "testing",
        ],
    },
    {
        "key": "verifier",
        "display_name": "Workspace Verifier",
        "label": "Verifier",
        "description": "Runs verification, browser checks, and evidence synthesis.",
        "capabilities": ["verification", "browser_e2e", "testing", "evidence", "shell"],
    },
)


class LegacyWorkspacePlanRuntimeRetiredError(RuntimeError):
    """Raised when a legacy Python Plan job is invoked."""


LegacyHandler = Callable[[object, object], Awaitable[None]]


def _retired_handler(operation: str) -> LegacyHandler:
    async def handler(_item: object, _session: object) -> None:
        raise LegacyWorkspacePlanRuntimeRetiredError(
            f"Python Workspace Plan {operation} is retired; use Avernet Workspace Core"
        )

    return handler


def make_supervisor_tick_handler(**_kwargs: object) -> LegacyHandler:
    return _retired_handler("supervisor tick")


def make_worker_launch_handler(**_kwargs: object) -> LegacyHandler:
    return _retired_handler("worker launch")


def make_handoff_resume_handler(**_kwargs: object) -> LegacyHandler:
    return _retired_handler("handoff resume")


def make_attempt_retry_handler(**_kwargs: object) -> LegacyHandler:
    return _retired_handler("attempt retry")


def make_pipeline_run_requested_handler(**_kwargs: object) -> LegacyHandler:
    return _retired_handler("pipeline execution")


def _needs_agent_managed_pipeline_proposal(contract: PipelineContractSpec) -> bool:
    if contract.provider != SANDBOX_NATIVE_PROVIDER:
        return False
    if not contract.agent_managed or not contract.auto_deploy:
        return False
    if contract.contract_source != PLANNING_CONTRACT_SOURCE:
        return True
    return not contract.services and not contract.deploy_command and not contract.health_url


def _requires_preview_deployment(contract: PipelineContractSpec) -> bool:
    return contract.provider == SANDBOX_NATIVE_PROVIDER and contract.auto_deploy


def _node_has_required_deployment_health(
    node: PlanNode,
    *,
    contract: PipelineContractSpec,
) -> bool:
    refs = _merge_string_values(node.metadata.get("pipeline_evidence_refs"), [])
    required_service_ids = [service.service_id for service in contract.services if service.required]
    if required_service_ids:
        return all(
            f"deployment_health:passed:{service_id}" in refs for service_id in required_service_ids
        )
    return "deployment_health:passed" in refs or any(
        ref.startswith("deployment_health:passed:") for ref in refs
    )


def _workspace_scoped_pipeline_contract(
    contract: PipelineContractSpec,
    *,
    workspace_id: str,
) -> PipelineContractSpec:
    if not contract.services:
        return contract
    service_id_map = {
        service.service_id: _workspace_proxy_service_id(
            workspace_id=workspace_id,
            service_id=service.service_id,
        )
        for service in contract.services
    }
    services = tuple(
        replace(service, service_id=service_id_map[service.service_id])
        for service in contract.services
    )
    stages = tuple(
        replace(stage, service_id=service_id_map.get(stage.service_id, stage.service_id))
        if stage.service_id
        else stage
        for stage in contract.stages
    )
    return replace(contract, services=services, stages=stages)


def _workspace_proxy_service_id(*, workspace_id: str, service_id: str) -> str:
    prefix = _workspace_proxy_service_prefix(workspace_id)
    if service_id.startswith(f"{prefix}-"):
        return service_id
    fragment = re.sub(r"[^a-z0-9-]+", "-", service_id.lower()).strip("-") or "service"
    digest = hashlib.sha1(f"{workspace_id}:{service_id}".encode()).hexdigest()[:8]
    return f"{prefix}-{fragment[:24].strip('-') or 'service'}-{digest}"


def _workspace_proxy_service_prefix(workspace_id: str) -> str:
    fragment = re.sub(r"[^a-z0-9]+", "", workspace_id.lower())[:8]
    return f"ws-{fragment or 'workspace'}"


def _can_reflect_existing_pipeline_run(
    *,
    run: object,
    contract: PipelineContractSpec,
    node: PlanNode,
) -> bool:
    status = getattr(run, "status", None)
    if status != "success":
        return False
    if _requires_drone_docker_deploy_validation(contract):
        raw_metadata = getattr(run, "metadata_json", None)
        metadata = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
        if metadata.get("deploy_validation") != DRONE_DOCKER_DEPLOY_VALIDATION:
            return False
    return not _requires_preview_deployment(contract) or _node_has_required_deployment_health(
        node,
        contract=contract,
    )


def _requires_drone_docker_deploy_validation(contract: PipelineContractSpec) -> bool:
    deploy = contract.deploy
    return (
        contract.provider == DRONE_PROVIDER
        and deploy is not None
        and deploy.enabled
        and deploy.required
        and deploy.mode == "docker"
    )


def _pipeline_result_summary(result: PipelineRunResult) -> str:
    if result.status == "success":
        return result.reason or "harness-native CI/CD pipeline passed"
    failed_stage = _first_failed_pipeline_stage(result.stage_results)
    if failed_stage is None:
        return result.reason or "harness-native CI/CD pipeline failed"
    parts = [result.reason or "harness-native CI/CD pipeline failed"]
    stage_label = f"failing stage {failed_stage.stage}"
    if failed_stage.exit_code is not None:
        stage_label += f" exited {failed_stage.exit_code}"
    parts.append(stage_label)
    stage_preview = _pipeline_stage_failure_preview(failed_stage)
    if stage_preview:
        parts.append(stage_preview)
    return _compact_pipeline_failure_text("; ".join(parts), limit=1800)


def _first_failed_pipeline_stage(
    stage_results: Iterable[PipelineStageResult],
) -> PipelineStageResult | None:
    for stage_result in stage_results:
        if not stage_result.passed:
            return stage_result
    return None


def _pipeline_stage_failure_preview(stage_result: PipelineStageResult) -> str:
    previews = []
    drone_error = stage_result.metadata.get("drone_error")
    if isinstance(drone_error, str) and drone_error.strip():
        previews.append(drone_error.strip())
    preview = (stage_result.stderr_preview or stage_result.stdout_preview or "").strip()
    if preview and preview not in previews:
        previews.append(preview)
    if not previews:
        return ""
    return _compact_pipeline_failure_text("; ".join(previews), limit=1200)


def _compact_pipeline_failure_text(value: str, *, limit: int) -> str:
    compacted = value.strip().replace("\n", "\\n")
    if len(compacted) <= limit:
        return compacted
    marker = "...[truncated]..."
    head_size = max(1, (limit - len(marker)) // 2)
    tail_size = max(1, limit - len(marker) - head_size)
    return f"{compacted[:head_size]}{marker}{compacted[-tail_size:]}"


def _pipeline_completion_node_state(
    *,
    node: PlanNode,
    status: str,
) -> tuple[TaskIntent, TaskExecution]:
    if status != "success":
        return TaskIntent.IN_PROGRESS, TaskExecution.REPORTED
    phase = _metadata_string(dict(node.metadata or {}).get("iteration_phase"))
    if phase in {"test", "deploy", "review"} or node.current_attempt_id:
        return TaskIntent.DONE, TaskExecution.IDLE
    return TaskIntent.IN_PROGRESS, TaskExecution.REPORTED


def _metadata_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _merge_string_values(existing: object, values: Iterable[str]) -> list[str]:
    merged: list[str] = []
    candidates = existing if isinstance(existing, (list, tuple, set)) else []
    for value in [*candidates, *values]:
        if isinstance(value, str) and value and value not in merged:
            merged.append(value)
    return merged


def _source_control_token(token_env: str | None) -> str | None:
    if not token_env:
        return None
    value = _metadata_string(os.getenv(token_env))
    if value:
        return value
    dotenv = _source_publish_dotenv_values(_source_publish_dotenv_path())
    return _metadata_string(dotenv.get(token_env))


def _source_publish_dotenv_path() -> str:
    return os.getenv("MEMSTACK_DRONE_DOTENV_PATH", ".env")


@lru_cache(maxsize=8)
def _source_publish_dotenv_values(path: str) -> Mapping[str, str | None]:
    dotenv_path = Path(path)
    if not dotenv_path.exists() or not dotenv_path.is_file():
        return {}
    return dotenv_values(dotenv_path)


__all__ = [
    "ATTEMPT_RETRY_EVENT",
    "DEPLOYMENT_HEALTH_CHECK_EVENT",
    "DEPLOYMENT_REQUESTED_EVENT",
    "HANDOFF_RESUME_EVENT",
    "PIPELINE_LOGS_SYNC_EVENT",
    "PIPELINE_RUN_REQUESTED_EVENT",
    "PIPELINE_STAGE_EXECUTE_EVENT",
    "SUPERVISOR_TICK_EVENT",
    "WORKER_LAUNCH_EVENT",
    "LegacyWorkspacePlanRuntimeRetiredError",
    "_can_reflect_existing_pipeline_run",
    "_needs_agent_managed_pipeline_proposal",
    "_pipeline_completion_node_state",
    "_pipeline_result_summary",
    "_source_control_token",
    "_workspace_scoped_pipeline_contract",
    "make_attempt_retry_handler",
    "make_handoff_resume_handler",
    "make_pipeline_run_requested_handler",
    "make_supervisor_tick_handler",
    "make_worker_launch_handler",
]
