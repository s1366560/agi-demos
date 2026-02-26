"""Tests for plugin_tool_to_info and build_plugin_tool_infos."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.plugin_tools import (
    build_plugin_tool_infos,
    plugin_tool_to_info,
)


@pytest.mark.unit
class TestPluginToolToInfo:
    """Tests for plugin_tool_to_info conversion function."""

    def test_form1_legacy_agent_tool(self) -> None:
        # Form 1: object with .execute and .name
        legacy = MagicMock()
        legacy.name = "legacy_tool"
        legacy.description = "A legacy tool"
        legacy.get_parameters = MagicMock(
            return_value={"type": "object", "properties": {"x": {"type": "string"}}}
        )
        legacy.permission = "read"

        info = plugin_tool_to_info("my_legacy", legacy, plugin_name="test-plugin")

        assert info is not None
        assert isinstance(info, ToolInfo)
        assert info.name == "my_legacy"
        assert info.category == "plugin"
        assert "plugin" in info.tags
        assert "test-plugin" in info.tags

    def test_form2_dict_definition(self) -> None:
        # Form 2: dict with name/description/parameters/execute
        execute_fn = AsyncMock()
        tool_dict = {
            "description": "Dict tool",
            "parameters": {"type": "object", "properties": {"y": {"type": "integer"}}},
            "execute": execute_fn,
            "permission": "write",
        }

        info = plugin_tool_to_info("dict_tool", tool_dict, plugin_name="my-plugin")

        assert info is not None
        assert info.name == "dict_tool"
        assert info.description == "Dict tool"
        assert info.permission == "write"
        assert info.execute is execute_fn

    def test_form2_dict_no_execute_returns_none(self) -> None:
        tool_dict = {
            "description": "Broken tool",
            "parameters": {"type": "object"},
        }

        info = plugin_tool_to_info("broken", tool_dict)
        assert info is None

    def test_form2_dict_non_callable_execute_returns_none(self) -> None:
        tool_dict = {
            "execute": "not_a_function",
        }

        info = plugin_tool_to_info("bad", tool_dict)
        assert info is None

    def test_form2_dict_defaults(self) -> None:
        execute_fn = AsyncMock()
        tool_dict = {"execute": execute_fn}

        info = plugin_tool_to_info("minimal_dict", tool_dict)

        assert info is not None
        assert info.description == ""
        assert info.permission is None
        assert info.parameters == {"type": "object", "properties": {}}

    def test_form3_bare_callable(self) -> None:
        # Form 3: just an async callable
        async def my_func(**kwargs: object) -> str:
            return "result"

        info = plugin_tool_to_info("callable_tool", my_func)

        assert info is not None
        assert info.name == "callable_tool"
        assert info.description == "Plugin tool: callable_tool"
        assert info.permission is None

    def test_unsupported_type_returns_none(self) -> None:
        info = plugin_tool_to_info("bad_tool", 42)
        assert info is None

    def test_exception_during_conversion_returns_none(self) -> None:
        # Object that raises on attribute access
        class Explosive:
            @property
            def execute(self) -> None:
                raise RuntimeError("boom")

            @property
            def name(self) -> str:
                raise RuntimeError("boom")

        info = plugin_tool_to_info("explosive", Explosive())
        assert info is None

    def test_empty_plugin_name_tags(self) -> None:
        async def fn(**kwargs: object) -> str:
            return ""

        info = plugin_tool_to_info("t", fn, plugin_name="")
        assert info is not None
        assert "plugin" in info.tags


@pytest.mark.unit
class TestBuildPluginToolInfos:
    """Tests for build_plugin_tool_infos."""

    async def test_builds_from_registry(self) -> None:
        # Arrange
        execute_fn = AsyncMock()
        registry = MagicMock()
        registry.build_tools = AsyncMock(
            return_value=(
                {"tool_a": execute_fn},
                [],  # no diagnostics
            )
        )
        context = MagicMock()

        # Act
        infos = await build_plugin_tool_infos(registry, context)

        # Assert
        assert len(infos) == 1
        assert infos[0].name == "tool_a"

    async def test_skips_unconvertible_tools(self) -> None:
        registry = MagicMock()
        registry.build_tools = AsyncMock(
            return_value=(
                {"good": AsyncMock(), "bad": 42},
                [],
            )
        )
        context = MagicMock()

        infos = await build_plugin_tool_infos(registry, context)
        assert len(infos) == 1
        assert infos[0].name == "good"

    async def test_handles_diagnostics(self) -> None:
        registry = MagicMock()
        diag = MagicMock()
        diag.level = "error"
        diag.plugin_name = "bad-plugin"
        diag.code = "load_failed"
        diag.message = "Could not load"

        registry.build_tools = AsyncMock(return_value=({}, [diag]))
        context = MagicMock()

        infos = await build_plugin_tool_infos(registry, context)
        assert len(infos) == 0
