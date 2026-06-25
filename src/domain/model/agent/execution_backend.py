"""Agent definition execution backend metadata helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, NotRequired, TypedDict, cast

ExecutionBackendType = Literal["memstack", "acp_external"]
EXECUTION_BACKEND_METADATA_KEY = "execution_backend"


class AgentExecutionBackend(TypedDict):
    """Normalized execution backend shape exposed by Agent Definition APIs."""

    type: ExecutionBackendType
    acp_agent_key: NotRequired[str]


DEFAULT_EXECUTION_BACKEND: AgentExecutionBackend = {"type": "memstack"}


def normalize_execution_backend(value: object) -> AgentExecutionBackend:
    """Normalize arbitrary metadata into the public execution backend shape."""
    if not isinstance(value, Mapping):
        return cast(AgentExecutionBackend, dict(DEFAULT_EXECUTION_BACKEND))

    backend_type = value.get("type")
    if backend_type in (None, "", "memstack"):
        return cast(AgentExecutionBackend, dict(DEFAULT_EXECUTION_BACKEND))
    if backend_type != "acp_external":
        raise ValueError("unsupported agent execution backend")

    raw_agent_key = value.get("acp_agent_key")
    if not isinstance(raw_agent_key, str) or not raw_agent_key.strip():
        raise ValueError("acp_external execution backend requires acp_agent_key")
    return {"type": "acp_external", "acp_agent_key": raw_agent_key.strip()}


def execution_backend_from_metadata(metadata: Mapping[str, Any] | None) -> AgentExecutionBackend:
    """Read a normalized execution backend from Agent.metadata."""
    if not metadata:
        return cast(AgentExecutionBackend, dict(DEFAULT_EXECUTION_BACKEND))
    return normalize_execution_backend(metadata.get(EXECUTION_BACKEND_METADATA_KEY))


def metadata_with_execution_backend(
    metadata: Mapping[str, Any] | None,
    execution_backend: object,
) -> dict[str, Any]:
    """Return metadata merged with a normalized execution backend."""
    normalized = normalize_execution_backend(execution_backend)
    merged = dict(metadata or {})
    if normalized["type"] == "memstack":
        merged.pop(EXECUTION_BACKEND_METADATA_KEY, None)
    else:
        merged[EXECUTION_BACKEND_METADATA_KEY] = cast(dict[str, Any], dict(normalized))
    return merged
