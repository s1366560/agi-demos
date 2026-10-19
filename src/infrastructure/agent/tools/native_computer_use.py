"""Operation-scoped native tools backed by an authenticated desktop connection."""

from __future__ import annotations

import copy
import hashlib
import json
from importlib.resources import files
from typing import TYPE_CHECKING, Any, Literal, cast

from src.application.services.approved_run_tool_permission_v2 import (
    ApprovedRunToolPermissionV2,
    _identity,
    _read_run,
    current_approved_run_guard_v2,
)
from src.application.services.chat_run_tool_permission_v2 import (
    ChatRunToolPermissionV2,
    current_chat_run_guard_v2,
    current_claimed_chat_tool_invocation_v2,
)
from src.infrastructure.agent.native_computer_use.contracts import (
    READ_TOOL_NAMES,
    TOOL_NAMES,
    CallAuthorization,
    PermissionProfile,
)
from src.infrastructure.agent.native_computer_use.effects import argument_schema, selection_effect
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

if TYPE_CHECKING:
    from src.infrastructure.agent.native_computer_use.broker import NativeComputerBroker


def current_native_computer_broker() -> NativeComputerBroker | None:
    """Use only the Redis resource owned by the pinned runtime generation."""
    from redis.asyncio import Redis

    from src.infrastructure.agent.native_computer_use.broker import NativeComputerBroker
    from src.infrastructure.plugins.v2.boundary import current_operation_context_v2
    from src.infrastructure.plugins.v2.redis_runtime import (
        REDIS_RUNTIME_SERVICE_V2,
        RedisRuntimeServiceV2,
    )

    try:
        operation = current_operation_context_v2()
        resource = operation.require(REDIS_RUNTIME_SERVICE_V2)
    except RuntimeV2Error as error:
        if error.code in {"operation_context_not_pinned", "missing_service"}:
            return None
        raise
    if not isinstance(resource, RedisRuntimeServiceV2) or not isinstance(resource.client, Redis):
        return None
    return NativeComputerBroker(resource.client)


async def authorize_native_call(
    ctx: ToolContext,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    broker: NativeComputerBroker | None = None,
) -> CallAuthorization:
    """Recover canonical authority and the exact already-claimed HITL receipt."""
    guard = current_approved_run_guard_v2() or current_chat_run_guard_v2()
    if guard is None or tool_name not in TOOL_NAMES:
        raise RuntimeV2Error("computer_use_authority_missing", "Native tool requires run authority")
    identity = (ctx.tenant_id, ctx.project_id, ctx.conversation_id, ctx.user_id)
    if guard.identity != identity or _identity(guard.operation) != identity:
        raise RuntimeV2Error("computer_use_identity_mismatch", "Native tool scope changed")
    permission = await _native_permission(ctx, tool_name, arguments, broker)
    approved_tools: tuple[str, ...] = ()
    if isinstance(guard, ApprovedRunToolPermissionV2):
        await guard.require(permission)
    elif isinstance(guard, ChatRunToolPermissionV2):
        receipt = current_claimed_chat_tool_invocation_v2(tool_name, arguments)
        if receipt is guard and permission != "read":
            await guard.revalidate_current_authority(permission)
            approved_tools = (tool_name,)
        elif await guard.decision(permission, tool_name, arguments) != "allow":
            raise RuntimeV2Error(
                "computer_use_invocation_not_approved", "Native action needs approval"
            )
    row = await _read_run(guard.sessions, guard.run_id, guard.identity, guard.child_run_id)
    child_owner_digest: str | None = None
    if guard.child_run_id is not None:
        from src.infrastructure.agent.subagent.owner_lease_v2 import current_owner_v2

        owner = current_owner_v2.get()
        if (
            owner is None
            or owner.run_id != guard.child_run_id
            or owner.conversation_id != ctx.conversation_id
        ):
            raise RuntimeV2Error("computer_use_child_owner_invalid", "Native child owner changed")
        child_owner_digest = hashlib.sha256(owner.token.encode("utf-8")).hexdigest()
    profile = row.permission_profile
    round_number = ctx.runtime_context.get("round")
    if (
        profile not in {"read_only", "workspace_write", "full_access"}
        or row.run_kind not in {"chat", "plan"}
        or not isinstance(round_number, int)
        or isinstance(round_number, bool)
        or round_number < 1
        or not ctx.session_id
        or not ctx.call_id
        or ctx.runtime_context.get("run_id") != (guard.child_run_id or guard.run_id)
    ):
        raise RuntimeV2Error(
            "computer_use_context_invalid", "Native call lacks trusted run context"
        )
    device_id = arguments.get("device_id")
    if device_id is not None and (not isinstance(device_id, str) or not device_id):
        raise RuntimeV2Error("computer_use_device_invalid", "Device identifier must be nonempty")
    return CallAuthorization(
        user_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        conversation_id=ctx.conversation_id,
        run_id=guard.run_id,
        session_id=native_session_id(ctx.session_id, guard.child_run_id or guard.run_id),
        round=round_number,
        permission_profile=cast(PermissionProfile, profile),
        authorization_revision=row.revision,
        plan_version_id=row.plan_version_id,
        approved_tools=approved_tools,
        call_id=ctx.call_id,
        device_id=device_id,
        child_run_id=guard.child_run_id,
        child_owner_digest=child_owner_digest,
        run_kind=cast(Literal["chat", "plan"], row.run_kind),
        allowed_mcp_servers=_allowed_mcp_servers(ctx),
    )


def _allowed_mcp_servers(ctx: ToolContext) -> tuple[str, ...]:
    servers = ctx.runtime_context.get("allowed_mcp_servers", [])
    if not isinstance(servers, (list, tuple)) or any(
        not isinstance(server, str) or not server for server in servers
    ):
        raise RuntimeV2Error("computer_use_mcp_profile_invalid", "Agent MCP scope is invalid")
    return tuple(servers)


async def _native_permission(
    ctx: ToolContext, tool_name: str, arguments: dict[str, Any], broker: NativeComputerBroker | None
) -> str:
    if tool_name != "computer_connector_call":
        return "read" if tool_name in READ_TOOL_NAMES else "mcp"
    broker = broker or current_native_computer_broker()
    if broker is None:
        raise RuntimeV2Error("computer_use_device_disconnected", "Native device is unavailable")
    devices = await broker.devices.list(
        user_id=ctx.user_id, tenant_id=ctx.tenant_id, project_id=ctx.project_id
    )
    return "read" if selection_effect(devices, tool_name, arguments) == "read" else "mcp"


async def create_native_computer_tools(
    *,
    tenant_id: str,
    project_id: str,
    user_id: str | None,
    broker: NativeComputerBroker | None = None,
) -> dict[str, ToolInfo]:
    """Discover schemas for one authenticated user; never cache them by project."""
    if not user_id or not tenant_id or not project_id:
        return {}
    broker = broker or current_native_computer_broker()
    if broker is None:
        return {}
    definitions = await broker.describe_tools(
        user_id=user_id, tenant_id=tenant_id, project_id=project_id
    )
    tools: dict[str, ToolInfo] = {}
    device_catalog = (
        await broker.devices.list(user_id=user_id, tenant_id=tenant_id, project_id=project_id)
        if any(item.get("name") == "computer_connector_call" for item in definitions)
        else []
    )
    for definition in definitions:
        name = definition.get("name")
        schema = definition.get("inputSchema")
        if name not in TOOL_NAMES or not isinstance(schema, dict):
            continue
        parameters = copy.deepcopy(argument_schema(schema))
        properties = parameters.setdefault("properties", {})
        if not isinstance(properties, dict):
            continue
        properties["device_id"] = {
            "type": "string",
            "minLength": 1,
            "description": "Exact connected device ID when device selection is required.",
        }

        def bind_execute(tool_name: str) -> Any:
            async def execute(ctx: ToolContext, **arguments: Any) -> ToolResult:
                if (ctx.user_id, ctx.tenant_id, ctx.project_id) != (user_id, tenant_id, project_id):
                    return ToolResult(
                        output='{"error":"computer_use_identity_mismatch"}', is_error=True
                    )
                try:
                    authority = await authorize_native_call(
                        ctx, tool_name, arguments, broker=broker
                    )
                    native_arguments = {k: v for k, v in arguments.items() if k != "device_id"}
                    return cast(
                        ToolResult,
                        await ctx.race(broker.request(authority, tool_name, native_arguments)),
                    )
                except RuntimeV2Error as error:
                    return ToolResult(output=json.dumps({"error": error.code}), is_error=True)
                except Exception as error:
                    from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError

                    if isinstance(error, DeviceBridgeError):
                        return ToolResult(output=json.dumps({"error": str(error)}), is_error=True)
                    raise

            return execute

        tools[name] = ToolInfo(
            name=name,
            description=str(definition.get("description", name)),
            parameters=parameters,
            execute=bind_execute(name),
            permission="read" if name in READ_TOOL_NAMES else "mcp",
            repeatable_observation=name in READ_TOOL_NAMES,
            permission_resolver=(
                lambda arguments: "read"
                if selection_effect(device_catalog, "computer_connector_call", arguments) == "read"
                else "mcp"
            )
            if name == "computer_connector_call"
            else None,
            category="computer_use",
            tags=frozenset({"native", "computer_use"}),
        )
    return _with_native_permission_tool(tools)


def _with_native_permission_tool(tools: dict[str, ToolInfo]) -> dict[str, ToolInfo]:
    if not tools:
        return tools
    from src.infrastructure.agent.native_computer_use.permission import native_permission_tool

    return {**tools, "request_permission": native_permission_tool()}


def native_session_id(session_id: str, execution_run_id: str) -> str:
    return hashlib.sha256(json.dumps([session_id, execution_run_id]).encode("utf-8")).hexdigest()


def native_computer_guidance(tool_names: set[str]) -> str:
    """Expose packaged first-party guidance only for an actually selected native observation tool."""
    if "computer_get_app_state" not in tool_names:
        return ""
    return (
        files("src.infrastructure.agent.native_computer_use")
        .joinpath("guidance.md")
        .read_text(encoding="utf-8")
    )


async def cancel_native_computer_run(session_id: str) -> None:
    """Release all device resources when the authoritative operation finishes."""
    guard = current_approved_run_guard_v2() or current_chat_run_guard_v2()
    if guard is None:
        return
    broker = current_native_computer_broker()
    if broker is not None:
        tenant, project, _, user = guard.identity
        await broker.cancel_session(
            guard.run_id,
            session_id=native_session_id(session_id, guard.child_run_id or guard.run_id),
            user_id=user,
            tenant_id=tenant,
            project_id=project,
        )
