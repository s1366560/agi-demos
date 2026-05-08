"""Workspace planner terminal tool for durable planning contracts."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.events.types import AgentEventType
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import WorkspaceModel
from src.infrastructure.agent.sisyphus.builtin_agent import BUILTIN_WORKSPACE_PLANNER_ID
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_WORKER,
    require_workspace_session_role,
    runtime_context_string,
)

logger = logging.getLogger(__name__)

PLANNING_CONTRACT_SOURCE = "planner_agent_code_analysis"
WORKSPACE_SUBMIT_PLANNING_CONTRACT_TOOL_NAME = "workspace_submit_planning_contract"

WORKSPACE_PLANNING_CONTRACT_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_graph": {
            "type": "object",
            "properties": {
                "subtasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "description": {"type": "string"},
                            "target_agent": {"type": "string"},
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "priority": {"type": "integer"},
                        },
                        "required": ["id", "description"],
                    },
                }
            },
            "required": ["subtasks"],
        },
        "delivery_cicd": {
            "type": "object",
            "description": "Sandbox-native delivery contract inferred from code evidence.",
            "properties": {
                "provider": {"type": "string"},
                "auto_deploy": {"type": "boolean"},
                "code_root": {"type": "string"},
                "services": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "service_id": {"type": "string"},
                            "name": {"type": "string"},
                            "start_command": {"type": "string"},
                            "internal_port": {"type": "integer"},
                            "internal_scheme": {"type": "string"},
                            "path_prefix": {"type": "string"},
                            "health_path": {"type": "string"},
                            "required": {"type": "boolean"},
                            "auto_open": {"type": "boolean"},
                        },
                        "required": [
                            "service_id",
                            "name",
                            "start_command",
                            "internal_port",
                            "health_path",
                        ],
                    },
                },
            },
        },
        "reasoning": {"type": "string"},
        "evidence_refs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Files and commands read by the planner, e.g. read:package.json.",
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["task_graph", "delivery_cicd", "reasoning", "evidence_refs", "confidence"],
}

_SERVICE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,80}$")


class WorkspacePlanningContractValidationError(ValueError):
    """Raised when a planner-submitted contract is structurally invalid."""


def normalize_workspace_planning_contract(
    *,
    task_graph: Mapping[str, Any],
    delivery_cicd: Mapping[str, Any] | None,
    reasoning: str,
    evidence_refs: Sequence[str],
    confidence: float,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    """Validate and normalize a planner-submitted planning contract."""

    normalized_evidence = _normalize_string_list(evidence_refs)
    if not normalized_evidence:
        raise WorkspacePlanningContractValidationError(
            "workspace planning contract requires at least one evidence_ref"
        )
    normalized_reasoning = _required_string(reasoning, "reasoning")
    normalized_confidence = _confidence(confidence)
    normalized_task_graph = _normalize_task_graph(task_graph)
    normalized_delivery = _normalize_delivery_cicd(
        delivery_cicd or {},
        confidence=normalized_confidence,
        reasoning=normalized_reasoning,
        evidence_refs=normalized_evidence,
        actor_user_id=actor_user_id,
    )
    return {
        "task_graph": normalized_task_graph,
        "delivery_cicd": normalized_delivery,
        "reasoning": normalized_reasoning,
        "evidence_refs": normalized_evidence,
        "confidence": normalized_confidence,
    }


async def persist_workspace_planning_contract(
    *,
    workspace_id: str,
    task_graph: Mapping[str, Any],
    delivery_cicd: Mapping[str, Any] | None,
    reasoning: str,
    evidence_refs: Sequence[str],
    confidence: float,
    actor_user_id: str | None = None,
    session: AsyncSession | None = None,
    commit: bool = True,
    publish: bool = True,
) -> dict[str, Any]:
    """Persist planner delivery metadata when services are present."""

    payload = normalize_workspace_planning_contract(
        task_graph=task_graph,
        delivery_cicd=delivery_cicd,
        reasoning=reasoning,
        evidence_refs=evidence_refs,
        confidence=confidence,
        actor_user_id=actor_user_id,
    )
    services = payload["delivery_cicd"].get("services")
    if not services:
        payload["metadata_written"] = False
        return payload

    if session is None:
        async with _session_scope() as scoped_session:
            await _write_workspace_metadata(
                scoped_session,
                workspace_id=workspace_id,
                payload=payload,
                commit=commit,
            )
    else:
        await _write_workspace_metadata(
            session,
            workspace_id=workspace_id,
            payload=payload,
            commit=commit,
        )

    payload["metadata_written"] = True
    if publish:
        await _publish_workspace_updated_event(
            workspace_id=workspace_id,
            payload={
                "workspace_id": workspace_id,
                "metadata": {"delivery_cicd": payload["delivery_cicd"]},
                "source": PLANNING_CONTRACT_SOURCE,
            },
        )
    return payload


@asynccontextmanager
async def _session_scope() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


async def _write_workspace_metadata(
    session: AsyncSession,
    *,
    workspace_id: str,
    payload: dict[str, Any],
    commit: bool,
) -> None:
    workspace_model = await session.get(WorkspaceModel, workspace_id)
    if workspace_model is None:
        raise WorkspacePlanningContractValidationError(f"workspace {workspace_id} not found")
    metadata = dict(workspace_model.metadata_json or {})
    metadata["delivery_cicd"] = payload["delivery_cicd"]
    workspace_model.metadata_json = metadata
    workspace_model.updated_at = datetime.now(UTC)
    await session.flush()
    if commit:
        await session.commit()


async def _publish_workspace_updated_event(
    *,
    workspace_id: str,
    payload: dict[str, Any],
) -> None:
    try:
        from src.infrastructure.adapters.primary.web.routers.workspace_events import (
            publish_workspace_event_with_retry,
        )
        from src.infrastructure.adapters.primary.web.startup.container import get_app_container

        redis_client = getattr(get_app_container(), "redis_client", None)
        await publish_workspace_event_with_retry(
            redis_client,
            workspace_id=workspace_id,
            event_type=AgentEventType.WORKSPACE_UPDATED,
            payload=payload,
        )
    except Exception:
        logger.warning(
            "workspace_planner_contract: failed to publish workspace_updated",
            extra={"workspace_id": workspace_id},
            exc_info=True,
        )


def _normalize_task_graph(task_graph: Mapping[str, Any]) -> dict[str, Any]:
    raw_subtasks = task_graph.get("subtasks")
    if not isinstance(raw_subtasks, list) or not raw_subtasks:
        raise WorkspacePlanningContractValidationError(
            "task_graph.subtasks must contain at least one subtask"
        )

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_subtasks, start=1):
        if not isinstance(item, Mapping):
            raise WorkspacePlanningContractValidationError(
                f"task_graph.subtasks[{index}] must be an object"
            )
        subtask_id = _required_string(item.get("id"), f"task_graph.subtasks[{index}].id")
        if subtask_id in seen:
            raise WorkspacePlanningContractValidationError(f"duplicate subtask id: {subtask_id}")
        seen.add(subtask_id)
        description = _required_string(
            item.get("description"),
            f"task_graph.subtasks[{index}].description",
        )
        depends_on = _normalize_string_list(item.get("depends_on") or [])
        priority = item.get("priority", 0)
        if not isinstance(priority, int):
            raise WorkspacePlanningContractValidationError(
                f"task_graph.subtasks[{index}].priority must be an integer"
            )
        subtask: dict[str, Any] = {
            "id": subtask_id,
            "description": description,
            "depends_on": depends_on,
            "priority": priority,
        }
        target_agent = _optional_string(item.get("target_agent"))
        if target_agent:
            subtask["target_agent"] = target_agent
        normalized.append(subtask)

    ids = {item["id"] for item in normalized}
    for item in normalized:
        for dependency in item["depends_on"]:
            if dependency == item["id"]:
                raise WorkspacePlanningContractValidationError(
                    f"subtask {item['id']} cannot depend on itself"
                )
            if dependency not in ids:
                raise WorkspacePlanningContractValidationError(
                    f"subtask {item['id']} depends on unknown subtask {dependency}"
                )
    _assert_acyclic(normalized)
    return {"subtasks": normalized}


def _normalize_delivery_cicd(
    delivery_cicd: Mapping[str, Any],
    *,
    confidence: float,
    reasoning: str,
    evidence_refs: list[str],
    actor_user_id: str | None,
) -> dict[str, Any]:
    delivery = dict(delivery_cicd)
    raw_services = delivery.get("services")
    if raw_services is not None:
        if not isinstance(raw_services, list):
            raise WorkspacePlanningContractValidationError("delivery_cicd.services must be a list")
        delivery["services"] = [
            _normalize_service(service, index=index)
            for index, service in enumerate(raw_services, start=1)
        ]
    delivery["provider"] = _optional_string(delivery.get("provider")) or "sandbox_native"
    delivery["auto_deploy"] = _bool(delivery.get("auto_deploy"), default=True)
    delivery["agent_managed"] = True
    delivery["contract_source"] = PLANNING_CONTRACT_SOURCE
    delivery["contract_confidence"] = confidence
    delivery["planning_reasoning"] = reasoning
    delivery["planning_evidence_refs"] = evidence_refs
    delivery["updated_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if actor_user_id:
        delivery["updated_by"] = actor_user_id
    return delivery


def _normalize_service(service: object, *, index: int) -> dict[str, Any]:
    if not isinstance(service, Mapping):
        raise WorkspacePlanningContractValidationError(
            f"delivery_cicd.services[{index}] must be an object"
        )
    service_id = _required_string(service.get("service_id"), f"services[{index}].service_id")
    if not _SERVICE_ID_RE.match(service_id):
        raise WorkspacePlanningContractValidationError(
            f"delivery_cicd.services[{index}].service_id is invalid"
        )
    port = _positive_port(service.get("internal_port"))
    if port is None:
        raise WorkspacePlanningContractValidationError(
            f"delivery_cicd.services[{index}].internal_port must be between 1 and 65535"
        )
    scheme = _optional_string(service.get("internal_scheme")) or "http"
    if scheme not in {"http", "https"}:
        raise WorkspacePlanningContractValidationError(
            f"delivery_cicd.services[{index}].internal_scheme must be http or https"
        )
    return {
        "service_id": service_id,
        "name": _required_string(service.get("name"), f"services[{index}].name"),
        "start_command": _required_string(
            service.get("start_command"),
            f"services[{index}].start_command",
        ),
        "internal_port": port,
        "internal_scheme": scheme,
        "path_prefix": _normalize_path(_optional_string(service.get("path_prefix")) or "/"),
        "health_path": _normalize_path(_required_string(service.get("health_path"), "health_path")),
        "required": _bool(service.get("required"), default=True),
        "auto_open": _bool(service.get("auto_open"), default=True),
    }


def _assert_acyclic(subtasks: list[dict[str, Any]]) -> None:
    dependencies = {item["id"]: set(item["depends_on"]) for item in subtasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            raise WorkspacePlanningContractValidationError(
                f"task_graph contains a dependency cycle at {node_id}"
            )
        visiting.add(node_id)
        for dependency in dependencies.get(node_id, set()):
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in dependencies:
        visit(node_id)


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise WorkspacePlanningContractValidationError("expected a list of strings")
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _required_string(value: object, label: str) -> str:
    normalized = _optional_string(value)
    if not normalized:
        raise WorkspacePlanningContractValidationError(f"{label} is required")
    return normalized


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _positive_port(value: object) -> int | None:
    if isinstance(value, int) and 0 < value <= 65535:
        return value
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        if 0 < parsed <= 65535:
            return parsed
    return None


def _confidence(value: object) -> float:
    if not isinstance(value, int | float):
        raise WorkspacePlanningContractValidationError("confidence must be a number between 0 and 1")
    parsed = float(value)
    if parsed < 0 or parsed > 1:
        raise WorkspacePlanningContractValidationError("confidence must be between 0 and 1")
    return parsed


def _bool(value: object, *, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _normalize_path(value: str) -> str:
    normalized = value.strip()
    return normalized if normalized.startswith("/") else f"/{normalized}"


def _deny(error: str, **extra: Any) -> ToolResult:
    payload: dict[str, Any] = {"error": error}
    payload.update(extra)
    return ToolResult(output=json.dumps(payload, ensure_ascii=False), is_error=True)


@tool_define(
    name=WORKSPACE_SUBMIT_PLANNING_CONTRACT_TOOL_NAME,
    description=(
        "Terminal workspace planning tool. The builtin workspace planner calls this exactly once "
        "after reading code evidence to submit the sprint DAG and sandbox-native delivery contract."
    ),
    parameters=WORKSPACE_PLANNING_CONTRACT_TOOL_PARAMETERS,
    permission=None,
    category="workspace",
)
async def workspace_submit_planning_contract_tool(
    ctx: ToolContext,
    *,
    task_graph: dict[str, Any],
    delivery_cicd: dict[str, Any],
    reasoning: str,
    evidence_refs: list[str],
    confidence: float,
) -> ToolResult:
    role_error = require_workspace_session_role(
        ctx,
        expected_role=WORKSPACE_ROLE_WORKER,
        action_label=WORKSPACE_SUBMIT_PLANNING_CONTRACT_TOOL_NAME,
    )
    if role_error:
        return _deny(role_error)
    selected_agent_id = runtime_context_string(ctx, "selected_agent_id")
    if selected_agent_id != BUILTIN_WORKSPACE_PLANNER_ID:
        return _deny(
            "workspace_submit_planning_contract may only be called by builtin:workspace-planner",
            selected_agent_id=selected_agent_id or None,
        )
    workspace_id = runtime_context_string(ctx, "workspace_id")
    actor_user_id = runtime_context_string(ctx, "user_id") or ctx.user_id or None
    try:
        payload = await persist_workspace_planning_contract(
            workspace_id=workspace_id,
            task_graph=task_graph,
            delivery_cicd=delivery_cicd,
            reasoning=reasoning,
            evidence_refs=evidence_refs,
            confidence=confidence,
            actor_user_id=actor_user_id,
        )
    except WorkspacePlanningContractValidationError as exc:
        return _deny(str(exc))
    return ToolResult(
        output=json.dumps(
            {
                "captured": True,
                "metadata_written": payload.get("metadata_written") is True,
                "contract_source": PLANNING_CONTRACT_SOURCE,
            },
            ensure_ascii=False,
        ),
        metadata={"planning_contract": payload},
    )


__all__ = [
    "PLANNING_CONTRACT_SOURCE",
    "WORKSPACE_PLANNING_CONTRACT_TOOL_PARAMETERS",
    "WORKSPACE_SUBMIT_PLANNING_CONTRACT_TOOL_NAME",
    "WorkspacePlanningContractValidationError",
    "normalize_workspace_planning_contract",
    "persist_workspace_planning_contract",
    "workspace_submit_planning_contract_tool",
]
