"""Tests for @tool_define, ToolInfo, wrap_legacy_tool, and registry functions."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.tools.define import (
    ToolInfo,
    clear_registry,
    get_registered_tools,
    tool_define,
    tool_info_to_openai_format,
    wrap_legacy_tool,
)


@pytest.mark.unit
class TestToolInfo:
    """Tests for ToolInfo dataclass."""

    def test_create_minimal(self) -> None:
        # Arrange & Act
        info = ToolInfo(
            name="test",
            description="A test tool",
            parameters={"type": "object"},
            execute=AsyncMock(),
        )

        # Assert
        assert info.name == "test"
        assert info.description == "A test tool"
        assert info.permission is None
        assert info.category == "general"
        assert info.model_filter is None
        assert info.tags == frozenset()

    def test_create_full(self) -> None:
        fn = AsyncMock()

        def model_filter(m: str) -> bool:
            return m.startswith("gpt")

        info = ToolInfo(
            name="write_file",
            description="Write a file",
            parameters={"type": "object", "properties": {}},
            execute=fn,
            permission="write",
            category="filesystem",
            model_filter=model_filter,
            tags=frozenset({"fs", "write"}),
        )

        assert info.permission == "write"
        assert info.category == "filesystem"
        assert info.model_filter is model_filter
        assert "fs" in info.tags


@pytest.mark.unit
class TestToolDefineDecorator:
    """Tests for @tool_define decorator."""

    def setup_method(self) -> None:
        clear_registry()

    def teardown_method(self) -> None:
        clear_registry()

    def test_decorator_returns_tool_info(self) -> None:
        @tool_define(
            name="my_tool",
            description="Does things",
            parameters={"type": "object", "properties": {}},
        )
        async def my_tool(ctx: object) -> str:
            return "hello"

        assert isinstance(my_tool, ToolInfo)
        assert my_tool.name == "my_tool"
        assert my_tool.description == "Does things"

    def test_decorator_registers_in_registry(self) -> None:
        @tool_define(
            name="registered_tool",
            description="test",
            parameters={"type": "object"},
        )
        async def registered_tool(ctx: object) -> str:
            return "hi"

        registry = get_registered_tools()
        assert "registered_tool" in registry
        assert registry["registered_tool"] is registered_tool

    def test_decorator_preserves_execute(self) -> None:
        original_fn = AsyncMock(return_value="result")

        @tool_define(
            name="exec_test",
            description="test",
            parameters={"type": "object"},
        )
        async def exec_test(ctx: object) -> str:
            return await original_fn(ctx)

        assert callable(exec_test.execute)

    def test_decorator_with_all_options(self) -> None:
        def model_filter(m: str) -> bool:
            return True

        @tool_define(
            name="full_tool",
            description="full",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}},
            permission="bash",
            category="terminal",
            model_filter=model_filter,
            tags=frozenset({"dangerous"}),
        )
        async def full_tool(ctx: object, x: str = "") -> str:
            return x

        assert full_tool.permission == "bash"
        assert full_tool.category == "terminal"
        assert full_tool.model_filter is model_filter
        assert "dangerous" in full_tool.tags

    def test_decorator_attaches_tool_info_to_fn(self) -> None:
        @tool_define(
            name="introspect",
            description="test",
            parameters={"type": "object"},
        )
        async def introspect(ctx: object) -> str:
            return ""

        # The original function should have _tool_info
        assert introspect.execute._tool_info is introspect  # type: ignore[attr-defined]


@pytest.mark.unit
class TestRegistryFunctions:
    """Tests for get_registered_tools and clear_registry."""

    def setup_method(self) -> None:
        clear_registry()

    def teardown_method(self) -> None:
        clear_registry()

    def test_get_registered_tools_returns_copy(self) -> None:
        @tool_define(name="t1", description="t", parameters={"type": "object"})
        async def t1(ctx: object) -> str:
            return ""

        registry = get_registered_tools()
        registry["fake"] = MagicMock()

        # Original should not be modified
        assert "fake" not in get_registered_tools()

    def test_clear_registry(self) -> None:
        @tool_define(name="to_clear", description="t", parameters={"type": "object"})
        async def to_clear(ctx: object) -> str:
            return ""

        assert len(get_registered_tools()) > 0
        clear_registry()
        assert len(get_registered_tools()) == 0


@pytest.mark.unit
class TestToolInfoToOpenaiFormat:
    """Tests for tool_info_to_openai_format."""

    def test_basic_conversion(self) -> None:
        info = ToolInfo(
            name="read_file",
            description="Read a file",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            execute=AsyncMock(),
        )

        result = tool_info_to_openai_format(info)

        assert result["type"] == "function"
        assert result["function"]["name"] == "read_file"
        assert result["function"]["description"] == "Read a file"
        assert result["function"]["parameters"]["required"] == ["path"]


@pytest.mark.unit
class TestWrapLegacyTool:
    """Tests for wrap_legacy_tool."""

    def test_wrap_with_get_parameters(self) -> None:
        legacy = MagicMock()
        legacy.name = "old_tool"
        legacy.description = "Legacy tool"
        legacy.get_parameters = MagicMock(
            return_value={"type": "object", "properties": {"x": {"type": "string"}}}
        )
        legacy.permission = "read"

        info = wrap_legacy_tool(legacy)

        assert isinstance(info, ToolInfo)
        assert info.name == "old_tool"
        assert info.description == "Legacy tool"
        assert info.parameters["properties"]["x"]["type"] == "string"
        assert info.permission == "read"
        assert info.execute is legacy.execute

    def test_wrap_with_get_parameters_schema(self) -> None:
        legacy = MagicMock(spec=["name", "get_parameters_schema", "execute"])
        legacy.name = "schema_tool"
        legacy.get_parameters_schema = MagicMock(return_value={"type": "object"})

        info = wrap_legacy_tool(legacy)
        assert info.parameters == {"type": "object"}

    def test_wrap_with_parameters_attribute(self) -> None:
        legacy = MagicMock(spec=["name", "parameters", "execute"])
        legacy.name = "attr_tool"
        legacy.parameters = {"type": "object", "properties": {}}

        info = wrap_legacy_tool(legacy)
        assert info.parameters == {"type": "object", "properties": {}}

    def test_wrap_no_description_uses_empty(self) -> None:
        legacy = MagicMock(spec=["name", "execute"])
        legacy.name = "no_desc"

        info = wrap_legacy_tool(legacy)
        assert info.description == ""

    def test_wrap_no_permission(self) -> None:
        legacy = MagicMock(spec=["name", "execute"])
        legacy.name = "no_perm"

        info = wrap_legacy_tool(legacy)
        assert info.permission is None
