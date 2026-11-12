"""Typed tool policy envelopes at the trusted generation boundary."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from src.domain.model.plugins.generated_v2 import TrustKindV2

from .runtime import OperationContextV2, RuntimeV2Error

TOOLS_BEFORE_EXECUTE_EVENT_V2 = "tools.before_execute"
TOOLS_RESULT_TRANSFORM_EVENT_V2 = "tools.result_transform"

_IDENTITY_FIELDS = (
    "tenant_id",
    "project_id",
    "session_id",
    "operation_id",
    "generation_digest",
    "tool_name",
    "call_id",
)
_IDENTITY_PROPERTIES = {name: {"type": "string", "minLength": 1} for name in _IDENTITY_FIELDS}


def _schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": [*_IDENTITY_FIELDS, *properties],
        "properties": {**_IDENTITY_PROPERTIES, **properties},
    }


def _decision_schema(kinds: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind"],
        "properties": {
            "kind": {"enum": kinds},
            "reason": {"type": "string"},
            "request": {"type": "object"},
        },
    }


TOOLS_BEFORE_EXECUTE_SCHEMA_V2 = _schema(
    {
        "arguments": {"type": "object"},
        "decision": _decision_schema(["allow", "deny", "ask", "cancel"]),
    }
)
TOOLS_RESULT_TRANSFORM_SCHEMA_V2 = _schema(
    {
        "result": {
            "type": "object",
            "additionalProperties": False,
            "required": ["output", "is_error", "metadata"],
            "properties": {
                "output": {"type": "string"},
                "is_error": {"type": "boolean"},
                "metadata": {"type": "object"},
            },
        },
        "decision": _decision_schema(["accept", "block"]),
    }
)


async def dispatch_tool_policy_v2(
    operation: OperationContextV2,
    *,
    event: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Only bundled handlers may transform execution; identity cannot be rewritten."""
    trust = {
        manifest.plugin_id: manifest.trust for manifest in operation.generation.snapshot.manifests
    }
    for fiber in operation.generation.fibers:
        if any(item.event == event for item in fiber.contract.events.handles):
            if (
                not fiber.entry.module_ref.startswith("builtin://")
                or trust.get(fiber.entry.plugin_ref) != TrustKindV2.BUILTIN
            ):
                raise RuntimeV2Error(
                    "untrusted_tool_policy", "Tool policies require bundled modules"
                )
    scope = operation.context.scope
    identity = {
        "tenant_id": scope.tenant_id,
        "project_id": scope.project_id,
        "session_id": scope.session_id,
        "operation_id": operation.operation_id,
        "generation_digest": operation.generation.digest,
        "tool_name": payload.get("tool_name"),
        "call_id": payload.get("call_id"),
    }
    for name, value in identity.items():
        if not isinstance(value, str) or not value:
            raise RuntimeV2Error("invalid_tool_policy_identity", f"Tool policy requires {name}")
        supplied = payload.get(name)
        if supplied is not None and supplied != value:
            raise RuntimeV2Error("tool_policy_identity_mismatch", f"Tool policy changed {name}")
    if event == TOOLS_BEFORE_EXECUTE_EVENT_V2:
        envelope = {
            **identity,
            "arguments": deepcopy(payload["arguments"]),
            "decision": {"kind": "allow"},
        }
        result = await operation.dispatch(TOOLS_BEFORE_EXECUTE_EVENT_V2, envelope)
    elif event == TOOLS_RESULT_TRANSFORM_EVENT_V2:
        envelope = {
            **identity,
            "result": deepcopy(payload["result"]),
            "decision": {"kind": "accept"},
        }
        result = await operation.dispatch(TOOLS_RESULT_TRANSFORM_EVENT_V2, envelope)
    else:
        raise RuntimeV2Error("tool_policy_event", "tool policy event is not declared")
    if not isinstance(result, Mapping):
        raise RuntimeV2Error("invalid_tool_policy_result", "Tool policy must return an object")
    for name, value in identity.items():
        if result.get(name) != value:
            raise RuntimeV2Error("tool_policy_identity_mismatch", f"Tool policy changed {name}")
    return dict(result)
