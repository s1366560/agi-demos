"""Structured native consent bound to a genuine completed device invocation."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.infrastructure.agent.native_computer_use.broker import NativeComputerBroker

from src.domain.events.agent_events import (
    AgentDomainEvent,
    AgentObserveEvent,
    AgentPermissionAskedEvent,
    AgentPermissionRepliedEvent,
)
from src.domain.model.agent.hitl_types import HITLType
from src.infrastructure.agent.core.message import ToolPart, ToolState
from src.infrastructure.agent.hitl.coordinator import HITLCoordinator
from src.infrastructure.agent.native_computer_use.permission_result import (
    decode_record,
    validate_claim,
)
from src.infrastructure.agent.native_computer_use.store import (
    DeviceBridgeError,
    request_key,
    run_key,
)
from src.infrastructure.agent.processor.hitl_tool_handler import queue_tool_part_hitl_completion
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

TEXT = {"type": "string", "minLength": 1, "maxLength": 4096}
IDENTITY = {"type": "string", "minLength": 1, "maxLength": 256}


def object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


DECISION_SCHEMA = object_schema(
    {
        "action": object_schema({"name": IDENTITY, "label": TEXT}, ["name", "label"]),
        "target": object_schema(
            {"kind": {"const": "computer_app"}, "id": IDENTITY}, ["kind", "id"]
        ),
        "data": object_schema(
            {
                "summary": TEXT,
                "redacted_fields": {"type": "array", "items": IDENTITY, "maxItems": 30},
            },
            ["summary"],
        ),
        "reason": TEXT,
        "risk": object_schema(
            {"level": {"enum": ["low", "medium", "high"]}, "rationale": TEXT},
            ["level", "rationale"],
        ),
        "reversibility": object_schema(
            {"mode": {"enum": ["reversible", "partial", "irreversible"]}, "recovery": TEXT},
            ["mode"],
        ),
        "scope": object_schema(
            {
                "kind": IDENTITY,
                "ids": {"type": "array", "items": IDENTITY, "minItems": 1, "maxItems": 30},
            },
            ["kind", "ids"],
        ),
        "evidence": {
            "type": "array",
            "minItems": 1,
            "maxItems": 30,
            "items": object_schema(
                {
                    "kind": IDENTITY,
                    "id": IDENTITY,
                    "label": TEXT,
                    "uri": TEXT,
                    "digest": IDENTITY,
                },
                ["kind", "id", "label"],
            ),
        },
    },
    ["action", "target", "data", "reason", "risk", "reversibility", "scope", "evidence"],
)
PERMISSION_SCHEMA = object_schema({"decision": DECISION_SCHEMA}, ["decision"])


async def _target_permission(
    broker: NativeComputerBroker, value: dict[str, Any], target_id: str
) -> dict[str, Any] | None:
    try:
        permission = decode_record(value.get("permission_required"))
        if permission is None or permission.demand["request"]["request_id"] != target_id:
            return None
        await validate_claim(broker, value, permission)
        return permission.demand
    except DeviceBridgeError as exc:
        raise RuntimeV2Error(
            "computer_use_pending_invalid", "Native pending consent is invalid"
        ) from exc


def native_permission_tool() -> ToolInfo:
    async def execute(_ctx: ToolContext, **_arguments: object) -> ToolResult:
        raise RuntimeV2Error(
            "native_permission_processor_required",
            "Native permission requires the cooperative HITL processor",
        )

    return ToolInfo(
        name="request_permission",
        description=(
            "Request human consent for an existing Computer Use permission request. Supply a complete "
            "structured decision with target.kind=computer_app and target.id equal to the genuine "
            "request.request_id returned by a native tool. Describe risk and reversibility explicitly; "
            "the host binds user, run, session and device, then waits for the user's response."
        ),
        parameters=PERMISSION_SCHEMA,
        execute=execute,
        permission="conversation_progress",
        category="human",
        tags=frozenset({"native", "hitl"}),
    )


async def bind_native_permission(
    ctx: ToolContext, decision: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    from src.application.services.approved_run_tool_permission_v2 import (
        ApprovedRunToolPermissionV2,
        _identity,
        _read_run,
        current_approved_run_guard_v2,
    )
    from src.application.services.chat_run_tool_permission_v2 import current_chat_run_guard_v2
    from src.infrastructure.agent.native_computer_use.schema import validator
    from src.infrastructure.agent.tools.native_computer_use import (
        current_native_computer_broker,
        native_session_id,
    )

    if (
        not validator(DECISION_SCHEMA).is_valid(decision)
        or len(json.dumps(decision).encode()) > 32 * 1024
    ):
        raise RuntimeV2Error(
            "computer_use_decision_invalid",
            "Native permission requires a complete structured decision",
        )
    guard = current_approved_run_guard_v2() or current_chat_run_guard_v2()
    identity = (ctx.tenant_id, ctx.project_id, ctx.conversation_id, ctx.user_id)
    if guard is None or guard.identity != identity or _identity(guard.operation) != identity:
        raise RuntimeV2Error("computer_use_identity_mismatch", "Native permission scope changed")
    if isinstance(guard, ApprovedRunToolPermissionV2):
        await guard.require("conversation_progress")
    else:
        await guard.revalidate_current_authority("conversation_progress")
    broker = current_native_computer_broker()
    if broker is None:
        raise DeviceBridgeError("computer_use_transport_unavailable")
    session_id = native_session_id(ctx.session_id, guard.child_run_id or guard.run_id)
    found: list[tuple[dict[str, Any], list[str]]] = []
    for cloud_id in await broker.members(
        run_key(ctx.user_id, ctx.tenant_id, ctx.project_id, guard.run_id)
    ):
        value = await broker.read(request_key(cloud_id))
        if (
            value is None
            or value.get("status") != "completed"
            or any(
                value.get(k) != v
                for k, v in {
                    "user_id": ctx.user_id,
                    "tenant_id": ctx.tenant_id,
                    "project_id": ctx.project_id,
                    "conversation_id": ctx.conversation_id,
                    "run_id": guard.run_id,
                    "session_id": session_id,
                }.items()
            )
        ):
            continue
        output = await _target_permission(broker, value, decision["target"]["id"])
        if output is None:
            continue
        pending = output["request"]
        if pending.get("engine_session_id") != session_id or any(
            not isinstance(pending.get(k), str) or not pending[k]
            for k in (
                "request_id",
                "session_id",
                "app",
                "identity_digest",
                "capability",
                "tool_name",
                "input_digest",
            )
        ):
            raise RuntimeV2Error(
                "computer_use_pending_invalid", "Native pending consent is invalid"
            )
        scopes = output.get("scopes")
        if (
            not isinstance(scopes, list)
            or not scopes
            or not all(isinstance(scope, str) for scope in scopes)
            or not set(scopes).issubset({"once", "session", "always"})
        ):
            raise RuntimeV2Error(
                "computer_use_pending_invalid", "Native consent scopes are invalid"
            )
        binding = {
            k: value[k]
            for k in (
                "user_id",
                "tenant_id",
                "project_id",
                "conversation_id",
                "run_id",
                "session_id",
                "device_id",
            )
        }
        binding.update(
            {
                k: pending[k]
                for k in ("app", "identity_digest", "capability", "tool_name", "input_digest")
            }
        )
        binding.update(
            {
                "cloud_request_id": cloud_id,
                "native_request_id": pending["request_id"],
                "native_session_id": pending["session_id"],
            }
        )
        await _bind_execution_step(broker, pending, binding, scopes, cloud_id)
        found.append((binding, scopes))
    row = await _read_run(guard.sessions, guard.run_id, guard.identity, guard.child_run_id)
    if len(found) != 1:
        raise RuntimeV2Error(
            "computer_use_pending_not_owned",
            "Native permission target is not pending in this session",
        )
    binding, scopes = found[0]
    binding["authorization_revision"] = row.revision
    return binding, scopes


async def handle_native_permission(
    coordinator: HITLCoordinator,
    ctx: ToolContext,
    decision: object,
    tool_part: ToolPart,
) -> AsyncIterator[AgentDomainEvent]:
    if not isinstance(decision, dict):
        raise RuntimeV2Error(
            "computer_use_decision_invalid",
            "Native permission requires a complete structured decision",
        )
    binding, scopes = await bind_native_permission(ctx, decision)
    request_data = {
        "tool_name": binding["tool_name"],
        "action": decision["action"]["name"],
        "description": decision["data"]["summary"],
        "risk_level": decision["risk"]["level"],
        "allow_remember": "always" in scopes,
        "decision": decision,
        "authority_revision": 1,
        "native_binding": binding,
        "scopes": scopes,
        "actions": [{"id": "allow", "label": _("Allow")}, {"id": "deny", "label": _("Deny")}],
    }
    request_id = await coordinator.prepare_request(HITLType.PERMISSION, request_data, 300)
    yield AgentPermissionAskedEvent(
        request_id=request_id,
        permission="computer_use",
        patterns=[binding["app"]],
        metadata=request_data,
    )
    granted = await coordinator.wait_for_response(
        request_id=request_id, hitl_type=HITLType.PERMISSION, timeout_seconds=300
    )
    if "execution_step" in binding:
        from src.application.services.approved_run_tool_permission_v2 import (
            _read_run,
            current_approved_run_guard_v2,
        )
        from src.application.services.chat_run_tool_permission_v2 import current_chat_run_guard_v2
        from src.infrastructure.agent.native_computer_use.steps import ExecutionSteps
        from src.infrastructure.agent.tools.native_computer_use import (
            current_native_computer_broker,
        )

        guard = current_approved_run_guard_v2() or current_chat_run_guard_v2()
        broker = current_native_computer_broker()
        if guard is None or broker is None:
            raise RuntimeV2Error(
                "computer_use_authority_missing", "Execution step authority expired"
            )
        row = await _read_run(guard.sessions, guard.run_id, guard.identity, guard.child_run_id)
        binding = {**binding, "authorization_revision": row.revision}
        await ExecutionSteps(broker.redis).resolve_permission(
            binding, bool(granted), hitl_request_id=request_id
        )
    queue_tool_part_hitl_completion(tool_part, request_id)
    yield AgentPermissionRepliedEvent(request_id=request_id, granted=bool(granted))
    tool_part.status = ToolState.COMPLETED
    tool_part.output = json.dumps({"granted": bool(granted), "target": decision["target"]})
    tool_part.end_time = time.time()
    yield AgentObserveEvent(
        tool_name="request_permission",
        result=tool_part.output,
        call_id=ctx.call_id,
        tool_execution_id=tool_part.tool_execution_id,
    )


async def _bind_execution_step(
    broker: NativeComputerBroker,
    pending: dict[str, Any],
    binding: dict[str, Any],
    scopes: list[str],
    cloud_id: str,
) -> None:
    step = pending.get("execution_step")
    if step is not None:
        from src.infrastructure.agent.native_computer_use.steps import ExecutionSteps

        if not isinstance(step, dict) or not isinstance(step.get("key"), str):
            raise RuntimeV2Error("computer_use_pending_invalid", "Execution step is invalid")
        stored_step = await broker.read(step["key"])
        if (
            stored_step is None
            or stored_step.get("status") != "pending"
            or stored_step.get("origin_request_id") != cloud_id
            or ExecutionSteps.pending(stored_step) != pending
            or scopes != ["once"]
            or any(
                stored_step.get(k) != binding.get(k)
                for k in (
                    "user_id",
                    "tenant_id",
                    "project_id",
                    "conversation_id",
                    "run_id",
                    "session_id",
                    "device_id",
                    "tool_name",
                    "input_digest",
                )
            )
        ):
            raise RuntimeV2Error("computer_use_pending_invalid", "Execution step is invalid")
        binding["execution_step"] = step
