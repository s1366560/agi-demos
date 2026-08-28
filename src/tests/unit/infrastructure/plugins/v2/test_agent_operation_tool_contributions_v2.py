"""Operation-scoped ToolSet contributions for one pinned Agent turn."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pytest

from src.domain.model.mcp.tool import MCPTool, MCPToolSchema
from src.infrastructure.agent.processor import ToolDefinition
from src.infrastructure.plugins.v2.agent_operation_tool_contributions import (
    activate_skill_mcp_operation_tools_v2,
    contribute_operation_tool_definitions_v2,
    parse_skill_mcp_configs_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.tool_set import (
    PreparedToolProviderV2,
    ToolSetCatalogV2,
    ToolSetResolverV2,
    ToolSetV2,
    bind_operation_tool_set_catalog_v2,
)

pytestmark = pytest.mark.unit

_EMPTY_PREPARED_TOOL_PROVIDER = PreparedToolProviderV2(tools={})


class _Operation:
    def __init__(self, operation_id: str) -> None:
        self.operation_id = operation_id
        self._services: dict[str, object] = {}
        self._effects: list[Callable[[], object]] = []

    def require(self, service: str) -> object:
        try:
            return self._services[service]
        except KeyError as exc:
            raise RuntimeV2Error("missing_service", f"missing {service}") from exc

    def provide(
        self,
        service: str,
        value: object,
        *,
        label: str | None = None,
    ) -> Callable[[], None]:
        _ = label
        if service in self._services:
            raise RuntimeV2Error("service_conflict", f"duplicate {service}")
        self._services[service] = value

        def dispose() -> None:
            if self._services.get(service) is value:
                del self._services[service]

        self._effects.append(dispose)
        return dispose

    async def effect(
        self,
        setup: Callable[[], object | Awaitable[object]],
        *,
        label: str,
    ) -> None:
        _ = label
        result = setup()
        if inspect.isawaitable(result):
            result = await result
        if callable(result):
            self._effects.append(result)

    async def dispose(self) -> None:
        for disposer in reversed(self._effects):
            result = disposer()
            if inspect.isawaitable(result):
                await result
        self._effects.clear()


class _SelectionPipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def select_with_trace(self, tools: dict[str, Any], _context: object) -> object:
        self.calls.append(tuple(tools))
        return SimpleNamespace(tools=tools, trace=())


class _MCPClient:
    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, object]:
        return {"content": {"tool": tool_name, "arguments": arguments}}


class _SkillMCPManager:
    def __init__(self, *, activation_error: BaseException | None = None) -> None:
        self.activation_error = activation_error
        self.events: list[str] = []
        self.catalog: ToolSetCatalogV2 | None = None
        self._client = _MCPClient()

    def register_skill_mcps(self, skill_id: str, configs: list[object]) -> None:
        self.events.append(f"register:{skill_id}:{len(configs)}")

    async def activate_skill(self, skill_id: str) -> list[MCPTool]:
        self.events.append(f"activate:{skill_id}")
        if self.activation_error is not None:
            raise self.activation_error
        return [
            MCPTool(
                server_id="echo-server",
                server_name="echo-server",
                schema=MCPToolSchema(
                    name="mcp_echo",
                    description="Echo through the operation MCP server",
                    input_schema={
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                ),
            )
        ]

    def get_active_client(self, server_name: str) -> _MCPClient | None:
        return self._client if server_name == "echo-server" else None

    async def deactivate_skill(self, skill_id: str) -> None:
        contribution_count = 0 if self.catalog is None else len(self.catalog.contributions())
        self.events.append(f"deactivate:{skill_id}:contributions={contribution_count}")

    def unregister_skill_mcps(self, skill_id: str) -> None:
        self.events.append(f"unregister:{skill_id}")


async def _execute_base() -> str:
    return "base"


async def _execute_dynamic(value: str) -> str:
    return value


def _base_tool_set(**_kwargs: object) -> ToolSetV2:
    definition = ToolDefinition(
        name="base_tool",
        description="Generation tool",
        parameters={"type": "object", "properties": {}},
        execute=_execute_base,
    )
    return ToolSetV2(
        tools=MappingProxyType({"base_tool": SimpleNamespace(description="Generation tool")}),
        definitions=(definition,),
    )


async def test_operation_contributions_merge_before_one_selection_and_preserve_schema() -> None:
    base_catalog = ToolSetCatalogV2()
    _ = base_catalog.register_tools("generation-tools", _base_tool_set)
    resolver = ToolSetResolverV2(strategy="ordered-contributions", catalog=base_catalog)
    operation = _Operation("turn-a")
    operation_catalog = bind_operation_tool_set_catalog_v2(operation)
    dynamic = ToolDefinition(
        name="dynamic_tool",
        description="Operation tool",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        execute=_execute_dynamic,
    )
    await contribute_operation_tool_definitions_v2(
        operation=operation,
        catalog=operation_catalog,
        source_id="operation-dynamic-tools",
        definitions=(dynamic,),
    )
    pipeline = _SelectionPipeline()

    tool_set = resolver.resolve(
        agent=SimpleNamespace(_tool_selection_pipeline=pipeline),
        selection_context=object(),
        prepared_tool_provider=_EMPTY_PREPARED_TOOL_PROVIDER,
        operation_catalog=operation_catalog,
    )

    assert pipeline.calls == [("base_tool", "dynamic_tool")]
    assert tuple(tool_set.tools) == ("base_tool", "dynamic_tool")
    dynamic_resolved = next(item for item in tool_set.definitions if item.name == "dynamic_tool")
    assert dynamic_resolved.parameters == dynamic.parameters
    assert await dynamic_resolved.execute(value="kept") == "kept"

    await operation.dispose()
    after_dispose = resolver.resolve(
        agent=object(),
        selection_context=None,
        prepared_tool_provider=_EMPTY_PREPARED_TOOL_PROVIDER,
        operation_catalog=operation_catalog,
    )
    assert tuple(after_dispose.tools) == ("base_tool",)
    assert await dynamic_resolved.execute(value="revoked") == {
        "error": "tool_execution_failed",
        "tool": "dynamic_tool",
        "message": "Tool raised an exception. See server logs for details.",
    }


async def test_two_operation_catalogs_never_mix_contributions() -> None:
    base_catalog = ToolSetCatalogV2()
    resolver = ToolSetResolverV2(strategy="ordered-contributions", catalog=base_catalog)
    first_operation = _Operation("turn-a")
    second_operation = _Operation("turn-b")
    first_catalog = bind_operation_tool_set_catalog_v2(first_operation)
    second_catalog = bind_operation_tool_set_catalog_v2(second_operation)
    await contribute_operation_tool_definitions_v2(
        operation=first_operation,
        catalog=first_catalog,
        source_id="turn-tools",
        definitions=(ToolDefinition("tool_a", "A", {}, _execute_base),),
    )
    await contribute_operation_tool_definitions_v2(
        operation=second_operation,
        catalog=second_catalog,
        source_id="turn-tools",
        definitions=(ToolDefinition("tool_b", "B", {}, _execute_base),),
    )

    first = resolver.resolve(
        agent=object(),
        selection_context=None,
        prepared_tool_provider=_EMPTY_PREPARED_TOOL_PROVIDER,
        operation_catalog=first_catalog,
    )
    second = resolver.resolve(
        agent=object(),
        selection_context=None,
        prepared_tool_provider=_EMPTY_PREPARED_TOOL_PROVIDER,
        operation_catalog=second_catalog,
    )

    assert tuple(first.tools) == ("tool_a",)
    assert tuple(second.tools) == ("tool_b",)


async def test_skill_mcp_and_subagent_share_one_preselection_tool_set() -> None:
    base_catalog = ToolSetCatalogV2()
    _ = base_catalog.register_tools("generation-tools", _base_tool_set)
    resolver = ToolSetResolverV2(strategy="ordered-contributions", catalog=base_catalog)
    operation = _Operation("turn-combined")
    operation_catalog = bind_operation_tool_set_catalog_v2(operation)
    manager = _SkillMCPManager()
    await activate_skill_mcp_operation_tools_v2(
        operation=operation,
        catalog=operation_catalog,
        manager=manager,
        skill_id="skill-echo",
        configs=parse_skill_mcp_configs_v2(
            [{"server_name": "echo-server", "command": "echo-server"}]
        ),
    )
    await contribute_operation_tool_definitions_v2(
        operation=operation,
        catalog=operation_catalog,
        source_id="operation-subagent-tools",
        definitions=(
            ToolDefinition(
                name="delegate_to_subagent",
                description="Delegate within this turn",
                parameters={"type": "object", "properties": {}},
                execute=_execute_dynamic,
            ),
        ),
    )
    pipeline = _SelectionPipeline()

    resolved = resolver.resolve(
        agent=SimpleNamespace(_tool_selection_pipeline=pipeline),
        selection_context=object(),
        prepared_tool_provider=_EMPTY_PREPARED_TOOL_PROVIDER,
        operation_catalog=operation_catalog,
    )

    expected = ("base_tool", "mcp_echo", "delegate_to_subagent")
    assert pipeline.calls == [expected]
    assert tuple(resolved.tools) == expected
    assert {definition.name for definition in resolved.definitions} == set(expected)


async def test_skill_mcp_activation_is_owned_and_released_by_operation_effect() -> None:
    operation = _Operation("turn-mcp")
    catalog = bind_operation_tool_set_catalog_v2(operation)
    manager = _SkillMCPManager()
    manager.catalog = catalog
    configs = parse_skill_mcp_configs_v2(
        [
            {
                "server_name": "echo-server",
                "command": "echo-server",
                "args": ["--stdio"],
                "env": {"SAFE_TEST_VALUE": "redacted"},
            }
        ]
    )

    await activate_skill_mcp_operation_tools_v2(
        operation=operation,
        catalog=catalog,
        manager=manager,
        skill_id="skill-echo",
        configs=configs,
    )

    resolved = ToolSetCatalogV2().resolve(
        agent=object(),
        selection_context=None,
        prepared_tool_provider=_EMPTY_PREPARED_TOOL_PROVIDER,
        operation_catalog=catalog,
    )
    assert [definition.name for definition in resolved.definitions] == ["mcp_echo"]
    assert await resolved.definitions[0].execute(value="hello") == {
        "tool": "mcp_echo",
        "arguments": {"value": "hello"},
    }

    await operation.dispose()

    with pytest.raises(RuntimeV2Error) as error:
        await resolved.definitions[0].execute(value="after-dispose")
    assert error.value.code == "operation_tool_revoked"

    assert manager.events == [
        "register:skill-echo@turn-mcp:1",
        "activate:skill-echo@turn-mcp",
        "deactivate:skill-echo@turn-mcp:contributions=0",
        "unregister:skill-echo@turn-mcp",
    ]


async def test_skill_mcp_activation_failure_cleans_registration_without_contribution() -> None:
    operation = _Operation("turn-failed")
    catalog = bind_operation_tool_set_catalog_v2(operation)
    manager = _SkillMCPManager(activation_error=RuntimeError("secret-bearing failure"))

    with pytest.raises(RuntimeV2Error) as error:
        await activate_skill_mcp_operation_tools_v2(
            operation=operation,
            catalog=catalog,
            manager=manager,
            skill_id="skill-failed",
            configs=parse_skill_mcp_configs_v2(
                [{"server_name": "failed", "command": "failed-command"}]
            ),
        )

    assert error.value.code == "skill_mcp_activation_failed"
    assert "secret-bearing" not in str(error.value)
    assert catalog.contributions() == ()
    assert manager.events == [
        "register:skill-failed@turn-failed:1",
        "activate:skill-failed@turn-failed",
        "deactivate:skill-failed@turn-failed:contributions=0",
        "unregister:skill-failed@turn-failed",
    ]


def test_skill_mcp_config_parser_rejects_untyped_env_before_activation() -> None:
    with pytest.raises(RuntimeV2Error) as error:
        parse_skill_mcp_configs_v2(
            [
                {
                    "server_name": "unsafe",
                    "command": "unsafe",
                    "env": {"TOKEN": object()},
                }
            ]
        )

    assert error.value.code == "invalid_skill_mcp_config"


def test_skill_mcp_config_parser_requires_canonical_fields_only() -> None:
    parsed = parse_skill_mcp_configs_v2([{"server_name": "canonical", "command": "mcp-server"}])
    assert parsed[0].server_name == "canonical"

    with pytest.raises(RuntimeV2Error) as error:
        parse_skill_mcp_configs_v2(
            [
                {
                    "name": "legacy-name",
                    "command": "mcp-server",
                }
            ]
        )

    assert error.value.code == "invalid_skill_mcp_config"

    with pytest.raises(RuntimeV2Error) as error:
        parse_skill_mcp_configs_v2(
            [
                {
                    "server_name": "canonical",
                    "command": "mcp-server",
                    "unexpected": True,
                }
            ]
        )

    assert error.value.code == "invalid_skill_mcp_config"


async def test_cancelled_skill_activation_cleans_registration_and_preserves_cancellation() -> None:
    operation = _Operation("turn-cancelled")
    catalog = bind_operation_tool_set_catalog_v2(operation)
    manager = _SkillMCPManager(activation_error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await activate_skill_mcp_operation_tools_v2(
            operation=operation,
            catalog=catalog,
            manager=manager,
            skill_id="skill-cancelled",
            configs=parse_skill_mcp_configs_v2(
                [{"server_name": "cancelled", "command": "cancelled-command"}]
            ),
        )

    assert catalog.contributions() == ()
    assert manager.events == [
        "register:skill-cancelled@turn-cancelled:1",
        "activate:skill-cancelled@turn-cancelled",
        "deactivate:skill-cancelled@turn-cancelled:contributions=0",
        "unregister:skill-cancelled@turn-cancelled",
    ]


async def test_concurrent_skill_operations_keep_activation_and_catalogs_isolated() -> None:
    first_operation = _Operation("turn-first")
    second_operation = _Operation("turn-second")
    first_catalog = bind_operation_tool_set_catalog_v2(first_operation)
    second_catalog = bind_operation_tool_set_catalog_v2(second_operation)
    manager = _SkillMCPManager()
    configs = parse_skill_mcp_configs_v2([{"server_name": "echo-server", "command": "echo-server"}])

    await asyncio.gather(
        activate_skill_mcp_operation_tools_v2(
            operation=first_operation,
            catalog=first_catalog,
            manager=manager,
            skill_id="shared-skill",
            configs=configs,
        ),
        activate_skill_mcp_operation_tools_v2(
            operation=second_operation,
            catalog=second_catalog,
            manager=manager,
            skill_id="shared-skill",
            configs=configs,
        ),
    )

    first = ToolSetCatalogV2().resolve(
        agent=object(),
        selection_context=None,
        prepared_tool_provider=_EMPTY_PREPARED_TOOL_PROVIDER,
        operation_catalog=first_catalog,
    )
    second = ToolSetCatalogV2().resolve(
        agent=object(),
        selection_context=None,
        prepared_tool_provider=_EMPTY_PREPARED_TOOL_PROVIDER,
        operation_catalog=second_catalog,
    )
    assert [definition.name for definition in first.definitions] == ["mcp_echo"]
    assert [definition.name for definition in second.definitions] == ["mcp_echo"]

    await first_operation.dispose()
    assert first_catalog.contributions() == ()
    assert [definition.name for definition in second.definitions] == ["mcp_echo"]

    await second_operation.dispose()
    assert second_catalog.contributions() == ()
    assert {event.split(":")[1].split("@")[1] for event in manager.events if "@" in event} == {
        "turn-first",
        "turn-second",
    }
