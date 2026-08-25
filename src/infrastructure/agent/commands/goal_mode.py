"""Workspace-backed /goal command implementation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from src.application.services.workspace_agent_autonomy import (
    build_workspace_harness_contract,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    AUTONOMY_SCHEMA_VERSION_KEY,
    PREFERRED_LANGUAGE,
    REPLAN_ATTEMPT_COUNT,
    TASK_ROLE,
    WORKSPACE_HARNESS,
)
from src.infrastructure.workspace_core.legacy_runtime import legacy_workspace_runtime_retired


@dataclass(frozen=True, slots=True)
class GoalCommandOutcome:
    """Result of applying a workspace-backed goal command."""

    root_task_id: str
    workspace_id: str
    scheduled: bool


@dataclass(frozen=True, slots=True)
class GoalStatusItem:
    """Projected workspace root goal status for the slash command reply."""

    root_task_id: str
    title: str
    status: str


def resolve_workspace_id(context: Mapping[str, Any]) -> str | None:
    """Read the current workspace id from command/runtime context."""

    runtime_context = _string_mapping(context.get("runtime_context"))
    if isinstance(runtime_context, Mapping):
        workspace_id = _clean_string(runtime_context.get("workspace_id"))
        if workspace_id:
            return workspace_id
        binding = _string_mapping(runtime_context.get("workspace_binding"))
        if isinstance(binding, Mapping):
            workspace_id = _clean_string(binding.get("workspace_id"))
            if workspace_id:
                return workspace_id

    return _clean_string(context.get("workspace_id"))


def resolve_tenant_id(context: Mapping[str, Any]) -> str | None:
    """Read the current tenant id from command/runtime context."""

    return _resolve_context_string(context, "tenant_id")


def resolve_project_id(context: Mapping[str, Any]) -> str | None:
    """Read the current project id from command/runtime context."""

    return _resolve_context_string(context, "project_id")


def resolve_preferred_language(context: Mapping[str, Any]) -> str | None:
    runtime_context = _string_mapping(context.get("runtime_context"))
    if isinstance(runtime_context, Mapping):
        preferred_language = _clean_string(runtime_context.get(PREFERRED_LANGUAGE))
        if preferred_language in {"en-US", "zh-CN"}:
            return preferred_language
    preferred_language = _clean_string(context.get(PREFERRED_LANGUAGE))
    return preferred_language if preferred_language in {"en-US", "zh-CN"} else None


async def create_workspace_for_goal(
    *,
    tenant_id: str,
    project_id: str,
    actor_user_id: str,
    goal_text: str,
    conversation_id: str | None = None,
) -> str:
    """Reject the retired local data path for an unbound /goal command."""
    legacy_workspace_runtime_retired("goal command")


async def create_workspace_goal(
    *,
    workspace_id: str,
    actor_user_id: str,
    goal_text: str,
    conversation_id: str | None = None,
    preferred_language: str | None = None,
) -> GoalCommandOutcome:
    """Reject the retired local data path for creating a Workspace goal."""
    legacy_workspace_runtime_retired("goal command")


async def list_workspace_goals(
    *,
    workspace_id: str,
    actor_user_id: str,
    limit: int = 5,
) -> list[GoalStatusItem]:
    """Reject the retired local data path for listing Workspace goals."""
    legacy_workspace_runtime_retired("goal command")


def build_human_goal_metadata(
    *,
    goal_text: str,
    conversation_id: str | None,
    preferred_language: str | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        AUTONOMY_SCHEMA_VERSION_KEY: 1,
        TASK_ROLE: "goal_root",
        "goal_origin": "human_defined",
        "goal_source_refs": [f"conversation:{conversation_id}"] if conversation_id else [],
        "goal_formalization_reason": "explicit /goal command",
        "root_goal_policy": {
            "mutable_by_agent": False,
            "completion_requires_external_proof": True,
        },
        "goal_health": "healthy",
        REPLAN_ATTEMPT_COUNT: 0,
        WORKSPACE_HARNESS: build_workspace_harness_contract(goal_title=goal_text),
    }
    if preferred_language in {"en-US", "zh-CN"}:
        metadata[PREFERRED_LANGUAGE] = preferred_language
    return metadata


def _resolve_context_string(context: Mapping[str, Any], key: str) -> str | None:
    runtime_context = _string_mapping(context.get("runtime_context"))
    if isinstance(runtime_context, Mapping):
        value = _clean_string(runtime_context.get(key))
        if value:
            return value
    return _clean_string(context.get(key))


def _clean_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _string_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast("Mapping[str, object]", value)
