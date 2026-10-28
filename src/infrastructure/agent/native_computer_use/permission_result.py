"""Permission provenance accepted only at the authenticated device-result boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeGuard, cast

from src.infrastructure.agent.native_computer_use.contracts import TOOL_NAMES
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError, request_key
from src.infrastructure.plugins.v2.protocol import canonical_json_v2

if TYPE_CHECKING:
    from src.infrastructure.agent.native_computer_use.store import BridgeStore


def input_digest(input_json: str) -> str:
    """The witness digest is JCS; existing server receipt digests stay unchanged."""
    try:
        return hashlib.sha256(canonical_json_v2(json.loads(input_json))).hexdigest()
    except (TypeError, ValueError) as exc:
        raise DeviceBridgeError("computer_use_permission_input_invalid") from exc


@dataclass(frozen=True)
class PermissionRequired:
    """A validated, immutable record, independent of model-visible output text."""

    wire_json: str

    def to_wire(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.wire_json))

    @property
    def demand(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.to_wire()["demand"])


def _object(value: object) -> TypeGuard[dict[str, Any]]:
    return isinstance(value, dict)


def _identity(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 256


def decode_record(value: object) -> PermissionRequired | None:
    """Decode only the separate host-owned record; never pass tool output here."""
    if value is None:
        return None
    if not _object(value) or set(value) != {"kind", "binding", "demand"}:
        raise DeviceBridgeError("computer_use_permission_result_invalid")
    if value["kind"] not in ("native_consent", "cloud_execution_step"):
        raise DeviceBridgeError("computer_use_permission_source_invalid")
    binding = value["binding"]
    if (
        not _object(binding)
        or set(binding) != {"tool_name", "input_digest", "engine_session_id", "cell_id", "step_id"}
        or not _identity(binding["tool_name"])
        or not _identity(binding["engine_session_id"])
        or not isinstance(binding["input_digest"], str)
        or len(binding["input_digest"]) != 64
        or any(char not in "0123456789abcdef" for char in binding["input_digest"])
        or (binding["cell_id"] is None) != (binding["step_id"] is None)
        or (
            binding["cell_id"] is not None
            and (not _identity(binding["cell_id"]) or not _identity(binding["step_id"]))
        )
    ):
        raise DeviceBridgeError("computer_use_permission_binding_invalid")
    demand = value["demand"]
    request = demand.get("request") if _object(demand) else None
    if (
        not _object(request)
        or demand.get("error") != "cua_permission_required"
        or request.get("engine_session_id") != binding["engine_session_id"]
        or request.get("tool_name") != binding["tool_name"]
        or any(
            not isinstance(request.get(key), str) or not request[key]
            for key in (
                "request_id",
                "session_id",
                "app",
                "identity_digest",
                "capability",
                "tool_name",
                "input_digest",
            )
        )
        or not isinstance(demand.get("scopes"), list)
        or not demand["scopes"]
        or any(scope not in ("once", "session", "always") for scope in demand["scopes"])
    ):
        raise DeviceBridgeError("computer_use_permission_demand_invalid")
    if value["kind"] == "native_consent":
        if binding["tool_name"] not in TOOL_NAMES or request["capability"] in {
            "execution_step",
            "mcp_tool",
        }:
            raise DeviceBridgeError("computer_use_permission_source_invalid")
    elif (
        binding["cell_id"] is None
        or request["capability"] != "execution_step"
        or demand["scopes"] != ["once"]
    ):
        raise DeviceBridgeError("computer_use_permission_source_invalid")
    try:
        return PermissionRequired(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise DeviceBridgeError("computer_use_permission_result_invalid") from exc


async def validate_claim(
    broker: BridgeStore, value: dict[str, Any], permission: PermissionRequired
) -> None:
    """Revalidate the original claim and its server-owned inner step, when present."""
    wire = permission.to_wire()
    binding = wire["binding"]
    if binding["engine_session_id"] != value.get("session_id"):
        raise DeviceBridgeError("computer_use_permission_binding_invalid")
    if binding["cell_id"] is None:
        if (
            wire["kind"] != "native_consent"
            or binding["tool_name"] != value.get("tool_name")
            or binding["input_digest"] != input_digest(value["input_json"])
        ):
            raise DeviceBridgeError("computer_use_permission_binding_invalid")
        return
    if value.get("tool_name") != "cua_repl_js":
        raise DeviceBridgeError("computer_use_permission_binding_invalid")
    from src.infrastructure.agent.native_computer_use.steps import SCOPE_FIELDS, ExecutionSteps

    matches: list[dict[str, Any]] = []
    for key in await broker.members(f"{request_key(value['request_id'])}:steps"):
        step = await broker.read(key)
        if (
            step is None
            or step.get("cell_id") != binding["cell_id"]
            or step.get("step_id") != binding["step_id"]
        ):
            continue
        if (
            step.get("current_request_id") != value["request_id"]
            or step.get("authorization_revision") != value.get("authorization_revision")
            or step.get("tool_name") != binding["tool_name"]
            or step.get("permission_input_digest") != binding["input_digest"]
            or any(step.get(name) != value.get(name) for name in SCOPE_FIELDS)
        ):
            raise DeviceBridgeError("computer_use_permission_step_changed")
        if wire["kind"] == "cloud_execution_step":
            if (
                step.get("status") != "pending"
                or ExecutionSteps.pending(step) != wire["demand"]["request"]
            ):
                raise DeviceBridgeError("computer_use_permission_step_changed")
        elif step.get("status") != "released" or step.get("last_outcome") != "not_sent":
            raise DeviceBridgeError("computer_use_permission_step_not_released")
        matches.append(step)
    if len(matches) != 1:
        raise DeviceBridgeError("computer_use_permission_step_missing")
