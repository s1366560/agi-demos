"""Unit tests for tool_converter module."""

from unittest.mock import MagicMock

import pytest

from src.infrastructure.agent.core.tool_converter import convert_tools


class MockTool:
    """Mock tool for testing."""

    def __init__(
        self,
        name: str = "test_tool",
        description: str = "A test tool",
        is_model_visible: bool = True,
        permission: str | None = None,
    ) -> None:
        self._name = name
        self.description = description
        self.permission = permission
        self._is_model_visible = is_model_visible
        self._tool_schema = MagicMock()
        self._tool_schema.is_model_visible = is_model_visible

    def execute(self, **kwargs):
        """Execute the tool."""
        return f"Executed with {kwargs}"

    def get_parameters_schema(self):
        """Get parameters schema."""
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Input value"},
            },
            "required": ["input"],
        }


class AsyncMockTool:
    """Mock async tool for testing."""

    def __init__(self, name: str = "async_tool") -> None:
        self._name = name
        self.description = "An async tool"
        self._tool_schema = MagicMock()
        self._tool_schema.is_model_visible = True

    async def execute(self, **kwargs):
        """Async execute the tool."""
        return f"Async executed with {kwargs}"


class AppOnlyTool:
    """Mock app-only tool (not visible to model)."""

    def __init__(self) -> None:
        self.description = "App only tool"
        self._tool_schema = MagicMock()
        self._tool_schema.is_model_visible = False

    def execute(self, **kwargs):
        return "Should not be called"


class ToolWithSchemaDict:
    """Tool with raw schema dict."""

    def __init__(self, visibility: list) -> None:
        self.description = "Tool with schema dict"
        self._schema = {"_meta": {"ui": {"visibility": visibility}}}

    def execute(self, **kwargs):
        return "Executed"


@pytest.fixture
def basic_tools():
    """Create basic tools dict for testing."""
    return {
        "test_tool": MockTool(),
    }


@pytest.fixture
def mixed_tools():
    """Create tools with mixed visibility."""
    return {
        "model_tool": MockTool(name="model_tool", is_model_visible=True),
        "app_only_tool": AppOnlyTool(),
    }


class TestToolConverter:
    """Tests for tool_converter module."""

    @pytest.mark.unit
    def test_convert_tools_basic(self, basic_tools):
        """Test basic tool conversion."""
        definitions = convert_tools(basic_tools)

        assert len(definitions) == 1
        assert definitions[0].name == "test_tool"
        assert definitions[0].description == "A test tool"

    @pytest.mark.unit
    def test_convert_tools_filters_app_only(self, mixed_tools):
        """Test app-only tools are filtered out."""
        definitions = convert_tools(mixed_tools)

        assert len(definitions) == 1
        assert definitions[0].name == "model_tool"

    @pytest.mark.unit
    def test_convert_tools_empty_dict(self):
        """Test empty tools dict returns empty list."""
        definitions = convert_tools({})

        assert definitions == []

    @pytest.mark.unit
    def test_convert_tools_extracts_parameters_schema(self, basic_tools):
        """Test parameters schema is extracted."""
        definitions = convert_tools(basic_tools)

        assert definitions[0].parameters is not None
        assert "properties" in definitions[0].parameters
        assert "input" in definitions[0].parameters["properties"]

    @pytest.mark.unit
    def test_convert_tools_extracts_permission(self):
        """Test permission is extracted."""
        tools = {
            "restricted_tool": MockTool(permission="user:write"),
        }

        definitions = convert_tools(tools)

        assert definitions[0].permission == "user:write"

    @pytest.mark.unit
    def test_convert_tools_stores_original_instance(self, basic_tools):
        """Test original tool instance is stored."""
        definitions = convert_tools(basic_tools)

        assert hasattr(definitions[0], "_tool_instance")
        assert definitions[0]._tool_instance is basic_tools["test_tool"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_wrapper_handles_sync(self, basic_tools):
        """Test execute wrapper handles sync tools."""
        definitions = convert_tools(basic_tools)

        result = await definitions[0].execute(input="test")

        assert result == "Executed with {'input': 'test'}"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_wrapper_handles_async(self):
        """Test execute wrapper handles async tools."""
        tools = {
            "async_tool": AsyncMockTool(),
        }

        definitions = convert_tools(tools)

        result = await definitions[0].execute(input="test")

        assert result == "Async executed with {'input': 'test'}"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_wrapper_handles_error(self):
        """Tool exceptions return a structured, redacted error (no raw message leak)."""

        class ErrorTool:
            description = "Error tool"
            _tool_schema = MagicMock()
            _tool_schema.is_model_visible = True

            def execute(self, **kwargs):
                raise ValueError("Tool error")

        tools = {"error_tool": ErrorTool()}
        definitions = convert_tools(tools)

        result = await definitions[0].execute(input="test")

        # New contract: structured dict, no raw exception text leaked to LLM.
        assert isinstance(result, dict)
        assert result["error"] == "tool_execution_failed"
        assert result["tool"] == "error_tool"
        # Raw exception message must NOT appear in the LLM-facing payload.
        assert "Tool error" not in str(result)

    @pytest.mark.unit
    def test_convert_tools_schema_dict_visibility_model(self):
        """Test schema dict with model visibility is included."""
        tools = {
            "visible_tool": ToolWithSchemaDict(visibility=["model", "app"]),
        }

        definitions = convert_tools(tools)

        assert len(definitions) == 1

    @pytest.mark.unit
    def test_convert_tools_schema_dict_visibility_app_only(self):
        """Test schema dict with app-only visibility is excluded."""
        tools = {
            "hidden_tool": ToolWithSchemaDict(visibility=["app"]),
        }

        definitions = convert_tools(tools)

        assert len(definitions) == 0

    @pytest.mark.unit
    def test_convert_tools_default_description(self):
        """Test default description when tool has none."""

        class NoDescTool:
            _tool_schema = MagicMock()
            _tool_schema.is_model_visible = True

        tools = {"nodesc_tool": NoDescTool()}
        definitions = convert_tools(tools)

        assert definitions[0].description == "Tool: nodesc_tool"

    @pytest.mark.unit
    def test_convert_tools_args_schema_fallback(self):
        """Test fallback to args_schema for parameters."""

        class ArgsSchemaTool:
            description = "Args schema tool"
            _tool_schema = MagicMock()
            _tool_schema.is_model_visible = True

            class ArgsSchema:
                @staticmethod
                def model_json_schema():
                    return {
                        "type": "object",
                        "properties": {"arg1": {"type": "string"}},
                    }

            args_schema = ArgsSchema

        tools = {"args_tool": ArgsSchemaTool()}
        definitions = convert_tools(tools)

        assert definitions[0].parameters["properties"]["arg1"]["type"] == "string"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_wrapper_ainvoke_fallback(self):
        """Test fallback to ainvoke method."""

        class AinvokeTool:
            description = "Ainvoke tool"
            _tool_schema = MagicMock()
            _tool_schema.is_model_visible = True

            async def ainvoke(self, **kwargs):
                return f"ainvoke: {kwargs}"

        tools = {"ainvoke_tool": AinvokeTool()}
        definitions = convert_tools(tools)

        result = await definitions[0].execute(input="test")

        assert result == "ainvoke: {'input': 'test'}"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_wrapper_run_fallback(self):
        """Test fallback to run method."""

        class RunTool:
            description = "Run tool"
            _tool_schema = MagicMock()
            _tool_schema.is_model_visible = True

            def run(self, **kwargs):
                return f"run: {kwargs}"

        tools = {"run_tool": RunTool()}
        definitions = convert_tools(tools)

        result = await definitions[0].execute(input="test")

        assert "run:" in result

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_wrapper_no_execute_method_error(self):
        """Tool with no execute method returns the structured, redacted error."""

        class NoMethodTool:
            description = "No method tool"
            _tool_schema = MagicMock()
            _tool_schema.is_model_visible = True
            # No execute, ainvoke, _run, run methods

        tools = {"nomethod_tool": NoMethodTool()}
        definitions = convert_tools(tools)

        result = await definitions[0].execute(input="test")

        assert isinstance(result, dict)
        assert result["error"] == "tool_execution_failed"
        assert result["tool"] == "nomethod_tool"
        # Internal exception text must NOT be exposed.
        assert "has no execute method" not in str(result)


class TestToolInfoWrapperRunContext:
    """ToolInfo-wrapped tools must observe the active RunContext (P1-13)."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_toolinfo_wrapper_inherits_active_abort_signal(self):
        """The stub ToolContext must reuse the per-run abort_signal, not a fresh Event."""
        import asyncio

        from src.infrastructure.agent.processor.run_context import (
            RunContext,
            set_current_run_context,
        )
        from src.infrastructure.agent.tools.context import ToolContext
        from src.infrastructure.agent.tools.define import ToolInfo

        captured: dict[str, ToolContext] = {}

        async def _execute(ctx: ToolContext, **_: object) -> str:
            captured["ctx"] = ctx
            return "ok"

        info = ToolInfo(
            name="signal_probe",
            description="probe",
            parameters={"type": "object", "properties": {}, "required": []},
            execute=_execute,
        )

        external_signal = asyncio.Event()
        set_current_run_context(RunContext(abort_signal=external_signal, conversation_id="conv-42"))

        definitions = convert_tools({"signal_probe": info})
        await definitions[0].execute()

        ctx = captured["ctx"]
        assert ctx.abort_signal is external_signal
        assert ctx.conversation_id == "conv-42"
        assert ctx.call_id  # non-empty

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_toolinfo_wrapper_falls_back_when_no_run_active(self):
        """Without an active RunContext (e.g. ad-hoc call) a fresh signal is used."""
        import asyncio

        from src.infrastructure.agent.processor.run_context import (
            RunContext,
            set_current_run_context,
        )
        from src.infrastructure.agent.tools.context import ToolContext
        from src.infrastructure.agent.tools.define import ToolInfo

        captured: dict[str, ToolContext] = {}

        async def _execute(ctx: ToolContext, **_: object) -> str:
            captured["ctx"] = ctx
            return "ok"

        info = ToolInfo(
            name="probe2",
            description="probe",
            parameters={"type": "object", "properties": {}, "required": []},
            execute=_execute,
        )

        # Explicitly clear any binding leaked from sibling tests.
        set_current_run_context(RunContext(abort_signal=None))

        definitions = convert_tools({"probe2": info})
        await definitions[0].execute()

        assert isinstance(captured["ctx"].abort_signal, asyncio.Event)
        assert not captured["ctx"].abort_signal.is_set()
        assert captured["ctx"].conversation_id == ""
