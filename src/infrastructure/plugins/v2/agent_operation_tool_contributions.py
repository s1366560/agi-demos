"""Disposable model-visible tool contributions owned by one Agent operation."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, cast, runtime_checkable

from src.domain.model.mcp.tool import MCPTool
from src.infrastructure.agent.mcp.skill_mcp_manager import SkillMCPConfig
from src.infrastructure.agent.processor import ToolDefinition

from .runtime import OperationContextV2, RuntimeV2Error
from .tool_set import ToolSetContributionCatalogProtocolV2, ToolSetV2

OPERATION_SKILL_MCP_TOOL_SOURCE_V2 = "operation-skill-mcp-tools"
OPERATION_SUBAGENT_TOOL_SOURCE_V2 = "operation-subagent-tools"

logger = logging.getLogger(__name__)

_SKILL_MCP_CONFIG_FIELDS_V2 = frozenset(
    {
        "server_name",
        "command",
        "args",
        "env",
        "auto_start",
    }
)


@dataclass
class _OperationToolLeaseV2:
    """Synchronous revocation token shared by all definitions in one contribution."""

    source_id: str
    active: bool = True

    def ensure_active(self) -> None:
        if not self.active:
            raise RuntimeV2Error(
                "operation_tool_revoked",
                f"operation tool contribution {self.source_id} is no longer active",
            )

    def revoke(self) -> None:
        self.active = False


@runtime_checkable
class SkillMCPManagerProtocolV2(Protocol):
    """Lifecycle surface required by one operation-scoped MCP contribution."""

    def register_skill_mcps(self, skill_id: str, configs: list[SkillMCPConfig]) -> None: ...

    async def activate_skill(self, skill_id: str) -> list[MCPTool]: ...

    def get_active_client(self, server_name: str) -> object | None: ...

    async def deactivate_skill(self, skill_id: str) -> None: ...

    def unregister_skill_mcps(self, skill_id: str) -> None: ...


@dataclass(frozen=True, kw_only=True)
class _OperationToolAdapterV2:
    """Preserve a prepared ToolDefinition while selection handles raw tools."""

    definition: ToolDefinition
    lease: _OperationToolLeaseV2

    @property
    def description(self) -> str:
        return self.definition.description

    @property
    def permission(self) -> str | None:
        return self.definition.permission

    @property
    def permission_resolver(self) -> Callable[[dict[str, Any]], str | None] | None:
        return self.definition.permission_resolver

    @property
    def aliases(self) -> tuple[str, ...]:
        return self.definition.aliases

    @property
    def tags(self) -> object:
        return getattr(self.definition._tool_instance, "tags", frozenset())

    def get_parameters_schema(self) -> dict[str, Any]:
        return dict(self.definition.parameters)

    async def execute(self, **kwargs: object) -> object:
        self.lease.ensure_active()
        result = self.definition.execute(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def consume_pending_events(self) -> list[Any]:
        if not self.lease.active:
            return []
        instance = self.definition._tool_instance
        consume = getattr(instance, "consume_pending_events", None)
        if not callable(consume):
            return []
        result = consume()
        if isinstance(result, Sequence) and not isinstance(result, (str, bytes)):
            return list(result)
        return []


def parse_skill_mcp_configs_v2(raw_configs: object) -> tuple[SkillMCPConfig, ...]:
    """Validate untrusted skill metadata without exposing environment values."""
    if raw_configs is None:
        return ()
    if not isinstance(raw_configs, Sequence) or isinstance(raw_configs, (str, bytes)):
        raise RuntimeV2Error(
            "invalid_skill_mcp_config",
            "skill mcp_servers must be an array",
        )
    configs: list[SkillMCPConfig] = []
    server_names: set[str] = set()
    for index, raw_config in enumerate(raw_configs):
        if not isinstance(raw_config, Mapping):
            raise RuntimeV2Error(
                "invalid_skill_mcp_config",
                f"skill mcp_servers[{index}] must be an object",
            )
        config = _parse_skill_mcp_config_v2(raw_config, index=index)
        if config.server_name in server_names:
            raise RuntimeV2Error(
                "invalid_skill_mcp_config",
                f"skill mcp_servers[{index}].server_name is duplicated",
            )
        server_names.add(config.server_name)
        configs.append(config)
    return tuple(configs)


def _parse_skill_mcp_config_v2(
    raw_config: Mapping[object, object],
    *,
    index: int,
) -> SkillMCPConfig:
    if not all(isinstance(key, str) for key in raw_config) or not set(raw_config).issubset(
        _SKILL_MCP_CONFIG_FIELDS_V2
    ):
        raise RuntimeV2Error(
            "invalid_skill_mcp_config",
            f"skill mcp_servers[{index}] contains unsupported fields",
        )
    server_name = raw_config.get("server_name")
    command = raw_config.get("command")
    if not isinstance(server_name, str) or not server_name.strip():
        raise RuntimeV2Error(
            "invalid_skill_mcp_config",
            f"skill mcp_servers[{index}].server_name must be a non-empty string",
        )
    if not isinstance(command, str) or not command.strip():
        raise RuntimeV2Error(
            "invalid_skill_mcp_config",
            f"skill mcp_servers[{index}].command must be a non-empty string",
        )
    raw_args = raw_config.get("args", ())
    if not isinstance(raw_args, Sequence) or isinstance(raw_args, (str, bytes)):
        raise RuntimeV2Error(
            "invalid_skill_mcp_config",
            f"skill mcp_servers[{index}].args must be an array of strings",
        )
    if not all(isinstance(value, str) for value in raw_args):
        raise RuntimeV2Error(
            "invalid_skill_mcp_config",
            f"skill mcp_servers[{index}].args must contain only strings",
        )
    raw_env = raw_config.get("env", {})
    if not isinstance(raw_env, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in raw_env.items()
    ):
        raise RuntimeV2Error(
            "invalid_skill_mcp_config",
            f"skill mcp_servers[{index}].env must contain only string pairs",
        )
    auto_start = raw_config.get("auto_start", True)
    if not isinstance(auto_start, bool):
        raise RuntimeV2Error(
            "invalid_skill_mcp_config",
            f"skill mcp_servers[{index}].auto_start must be boolean",
        )
    return SkillMCPConfig(
        server_name=server_name.strip(),
        command=command.strip(),
        args=list(cast("Sequence[str]", raw_args)),
        env=dict(cast("Mapping[str, str]", raw_env)),
        auto_start=auto_start,
    )


async def contribute_operation_tool_definitions_v2(
    *,
    operation: OperationContextV2,
    catalog: ToolSetContributionCatalogProtocolV2,
    source_id: str,
    definitions: Sequence[ToolDefinition],
) -> None:
    """Register prepared definitions as one reversible operation effect."""

    def setup() -> Callable[[], None | Awaitable[None]]:
        return _register_operation_tool_definitions_v2(
            catalog=catalog,
            source_id=source_id,
            definitions=definitions,
        )

    await operation.effect(setup, label=f"operation-tools:{source_id}")


async def lease_operation_tool_definitions_v2(
    *,
    operation: OperationContextV2,
    source_id: str,
    definitions: Sequence[ToolDefinition],
) -> ToolSetV2:
    """Bind prepared definitions to an operation without publishing a catalog source."""
    normalized_source_id = source_id.strip()
    if not normalized_source_id:
        raise RuntimeV2Error(
            "invalid_tool_contribution",
            "leased operation tools require a non-empty source ID",
        )
    lease = _OperationToolLeaseV2(source_id=normalized_source_id)
    tool_set = _operation_tool_set_v2(definitions, lease=lease)

    def setup() -> Callable[[], None]:
        return lease.revoke

    try:
        await operation.effect(setup, label=f"leased-operation-tools:{normalized_source_id}")
    except BaseException:
        lease.revoke()
        raise
    return tool_set


async def _cleanup_failed_skill_mcp_activation_v2(
    *,
    manager: SkillMCPManagerProtocolV2,
    activation_id: str,
    skill_id: str,
) -> None:
    try:
        await manager.deactivate_skill(activation_id)
    except BaseException as cleanup_error:
        logger.error(
            "Skill MCP failure cleanup could not deactivate: skill_id=%s error_type=%s",
            skill_id,
            type(cleanup_error).__name__,
        )
    try:
        manager.unregister_skill_mcps(activation_id)
    except Exception as cleanup_error:
        logger.error(
            "Skill MCP failure cleanup could not unregister: skill_id=%s error_type=%s",
            skill_id,
            type(cleanup_error).__name__,
        )


async def activate_skill_mcp_operation_tools_v2(
    *,
    operation: OperationContextV2,
    catalog: ToolSetContributionCatalogProtocolV2,
    manager: SkillMCPManagerProtocolV2,
    skill_id: str,
    configs: Sequence[SkillMCPConfig],
) -> tuple[str, ...]:
    """Activate MCP servers and expose their tools for exactly one operation."""
    if not configs:
        return ()
    normalized_skill_id = skill_id.strip()
    if not normalized_skill_id:
        raise RuntimeV2Error("invalid_skill_mcp_config", "skill id must be non-empty")
    activation_id = f"{normalized_skill_id}@{operation.operation_id}"
    activated_tool_names: tuple[str, ...] = ()

    async def setup() -> Callable[[], Awaitable[None]]:
        nonlocal activated_tool_names
        registered = False
        contribution_disposer: Callable[[], None | Awaitable[None]] | None = None

        async def cleanup_failed_activation() -> None:
            if not registered:
                return
            await _cleanup_failed_skill_mcp_activation_v2(
                manager=manager,
                activation_id=activation_id,
                skill_id=normalized_skill_id,
            )

        try:
            manager.register_skill_mcps(activation_id, list(configs))
            registered = True
            mcp_tools = await manager.activate_skill(activation_id)
            definitions = _mcp_tool_definitions_v2(manager, mcp_tools)
            contribution_disposer = _register_operation_tool_definitions_v2(
                catalog=catalog,
                source_id=OPERATION_SKILL_MCP_TOOL_SOURCE_V2,
                definitions=definitions,
            )
            activated_tool_names = tuple(definition.name for definition in definitions)
        except asyncio.CancelledError:
            await cleanup_failed_activation()
            logger.info(
                "Skill MCP operation activation cancelled: skill_id=%s",
                normalized_skill_id,
            )
            raise
        except Exception as exc:
            await cleanup_failed_activation()
            logger.error(
                "Skill MCP operation activation failed: skill_id=%s error_type=%s",
                normalized_skill_id,
                type(exc).__name__,
            )
            raise RuntimeV2Error(
                "skill_mcp_activation_failed",
                f"skill MCP activation failed for {normalized_skill_id}",
            ) from exc

        async def dispose() -> None:
            assert contribution_disposer is not None
            try:
                result = contribution_disposer()
                if inspect.isawaitable(result):
                    await result
            finally:
                try:
                    await manager.deactivate_skill(activation_id)
                finally:
                    manager.unregister_skill_mcps(activation_id)

        return dispose

    await operation.effect(setup, label=f"skill-mcp-tools:{normalized_skill_id}")
    return activated_tool_names


def _operation_tool_set_v2(
    definitions: Sequence[ToolDefinition],
    *,
    lease: _OperationToolLeaseV2,
) -> ToolSetV2:
    normalized_definitions = tuple(definitions)
    tools: dict[str, _OperationToolAdapterV2] = {}
    leased_definitions: list[ToolDefinition] = []
    for definition in normalized_definitions:
        normalized_name = definition.name.strip()
        if not normalized_name:
            raise RuntimeV2Error(
                "invalid_tool_definition",
                "operation tool definition name must be non-empty",
            )
        if normalized_name in tools:
            raise RuntimeV2Error(
                "tool_contribution_conflict",
                f"operation tool definition {normalized_name} is duplicated",
            )
        adapter = _OperationToolAdapterV2(definition=definition, lease=lease)
        tools[normalized_name] = adapter
        leased_definitions.append(
            ToolDefinition(
                name=normalized_name,
                description=definition.description,
                parameters=dict(definition.parameters),
                execute=adapter.execute,
                permission=definition.permission,
                permission_resolver=definition.permission_resolver,
                aliases=definition.aliases,
                _tool_instance=adapter,
            )
        )
    return ToolSetV2(
        tools=MappingProxyType(tools),
        definitions=tuple(leased_definitions),
    )


def _register_operation_tool_definitions_v2(
    *,
    catalog: ToolSetContributionCatalogProtocolV2,
    source_id: str,
    definitions: Sequence[ToolDefinition],
) -> Callable[[], Awaitable[None]]:
    lease = _OperationToolLeaseV2(source_id=source_id)
    tool_set = _operation_tool_set_v2(definitions, lease=lease)
    try:
        contribution_disposer = catalog.register_tools(
            source_id,
            lambda **_kwargs: tool_set,
        )
    except BaseException:
        lease.revoke()
        raise

    async def dispose() -> None:
        lease.revoke()
        result = contribution_disposer()
        if inspect.isawaitable(result):
            await result

    return dispose


def _mcp_tool_definitions_v2(
    manager: SkillMCPManagerProtocolV2,
    mcp_tools: Sequence[MCPTool],
) -> tuple[ToolDefinition, ...]:
    definitions: list[ToolDefinition] = []
    names: set[str] = set()
    for mcp_tool in mcp_tools:
        if not mcp_tool.schema.is_model_visible:
            continue
        tool_name = mcp_tool.schema.name.strip()
        if not tool_name or tool_name in names:
            raise RuntimeV2Error(
                "tool_contribution_conflict",
                "skill MCP contribution contains an empty or duplicate tool name",
            )
        client = manager.get_active_client(mcp_tool.server_name)
        if client is None:
            raise RuntimeV2Error(
                "skill_mcp_client_unavailable",
                f"skill MCP client is unavailable for server {mcp_tool.server_name}",
            )
        call_tool = getattr(client, "call_tool", None)
        if not callable(call_tool):
            raise RuntimeV2Error(
                "invalid_skill_mcp_client",
                f"skill MCP client is invalid for server {mcp_tool.server_name}",
            )
        call_tool_fn: Callable[..., object] = call_tool

        async def execute(
            _call_tool: Callable[..., object] = call_tool_fn,
            _tool_name: str = tool_name,
            **kwargs: object,
        ) -> object:
            result = _call_tool(_tool_name, kwargs)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, Mapping):
                return result.get("content", str(result))
            return result

        definitions.append(
            ToolDefinition(
                name=tool_name,
                description=(mcp_tool.schema.description or f"MCP tool: {mcp_tool.schema.name}"),
                parameters=(
                    mcp_tool.schema.input_schema
                    or {
                        "type": "object",
                        "properties": {},
                    }
                ),
                execute=execute,
                _tool_instance=mcp_tool,
            )
        )
        names.add(tool_name)
    return tuple(definitions)


__all__ = [
    "OPERATION_SKILL_MCP_TOOL_SOURCE_V2",
    "OPERATION_SUBAGENT_TOOL_SOURCE_V2",
    "SkillMCPManagerProtocolV2",
    "activate_skill_mcp_operation_tools_v2",
    "contribute_operation_tool_definitions_v2",
    "lease_operation_tool_definitions_v2",
    "parse_skill_mcp_configs_v2",
]
