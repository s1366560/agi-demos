"""Unit tests for MCP App event hydration in SessionProcessor."""

from unittest.mock import AsyncMock

import pytest

from src.domain.events.agent_events import AgentMCPAppResultEvent, AgentObserveEvent
from src.infrastructure.agent.core.message import ToolPart, ToolState
from src.infrastructure.agent.processor import ProcessorConfig, SessionProcessor, ToolDefinition


class MockMCPTool:
    """Minimal MCP tool instance for processor event tests."""

    def __init__(
        self,
        *,
        has_ui: bool = False,
        app_id: str = "app-demo-1",
        server_name: str = "demo-server",
        ui_metadata: dict | None = None,
    ) -> None:
        self.has_ui = has_ui
        self._app_id = app_id
        self._last_app_id = ""
        self._server_name = server_name
        self._last_html = ""
        self._ui_metadata = ui_metadata or {}

    @property
    def ui_metadata(self) -> dict:
        return self._ui_metadata

    async def fetch_resource_html(self) -> str:
        return ""


def create_mcp_tool_def(mock_tool: MockMCPTool) -> ToolDefinition:
    """Create tool definition with attached runtime instance."""

    async def execute(**kwargs):
        return {"ok": True, "output": "done"}

    tool_def = ToolDefinition(
        name="mcp__demo__tool",
        description="MCP demo tool",
        parameters={"type": "object", "properties": {}, "required": []},
        execute=execute,
    )
    tool_def._tool_instance = mock_tool  # type: ignore[attr-defined]
    return tool_def


@pytest.mark.unit
class TestProcessorMCPAppResultHydration:
    """MCP UI payload hydration and event emission behavior."""

    @pytest.mark.asyncio
    async def test_emits_mcp_app_result_with_db_hydrated_resource_uri(self):
        tool_instance = MockMCPTool(has_ui=False, ui_metadata={})
        tool_def = create_mcp_tool_def(tool_instance)
        processor = SessionProcessor(
            config=ProcessorConfig(model="test-model"),
            tools=[tool_def],
        )
        processor._langfuse_context = {"project_id": "project-123"}
        processor._load_mcp_app_ui_metadata = AsyncMock(  # type: ignore[method-assign]
            return_value={"resourceUri": "ui://demo/app.html", "title": "Demo App"}
        )

        processor._pending_tool_calls["call-1"] = ToolPart(
            call_id="call-1",
            tool="mcp__demo__tool",
            input={"foo": "bar"},
            status=ToolState.RUNNING,
        )

        events = []
        async for event in processor._execute_tool(
            session_id="session-1",
            call_id="call-1",
            tool_name="mcp__demo__tool",
            arguments={"foo": "bar"},
        ):
            events.append(event)

        observe_event = next(e for e in events if isinstance(e, AgentObserveEvent))
        mcp_event = next(e for e in events if isinstance(e, AgentMCPAppResultEvent))

        assert observe_event.ui_metadata["resource_uri"] == "ui://demo/app.html"
        assert mcp_event.resource_uri == "ui://demo/app.html"
        assert mcp_event.ui_metadata["resourceUri"] == "ui://demo/app.html"
        assert mcp_event.app_id == "app-demo-1"
        assert mcp_event.project_id == "project-123"

    @pytest.mark.asyncio
    async def test_uses_snake_case_resource_uri_without_db_hydration(self):
        tool_instance = MockMCPTool(
            has_ui=True,
            ui_metadata={"resource_uri": "ui://demo/snake.html", "title": "Snake App"},
        )
        tool_def = create_mcp_tool_def(tool_instance)
        processor = SessionProcessor(
            config=ProcessorConfig(model="test-model"),
            tools=[tool_def],
        )
        processor._load_mcp_app_ui_metadata = AsyncMock(  # type: ignore[method-assign]
            return_value={"resourceUri": "ui://should-not-be-used.html"}
        )

        processor._pending_tool_calls["call-2"] = ToolPart(
            call_id="call-2",
            tool="mcp__demo__tool",
            input={},
            status=ToolState.RUNNING,
        )

        events = []
        async for event in processor._execute_tool(
            session_id="session-2",
            call_id="call-2",
            tool_name="mcp__demo__tool",
            arguments={},
        ):
            events.append(event)

        mcp_event = next(e for e in events if isinstance(e, AgentMCPAppResultEvent))
        assert mcp_event.resource_uri == "ui://demo/snake.html"
        assert mcp_event.ui_metadata["resource_uri"] == "ui://demo/snake.html"
        processor._load_mcp_app_ui_metadata.assert_not_called()  # type: ignore[attr-defined]
