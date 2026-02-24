"""RegisterMCPServerTool - Agent tool for registering MCP servers built in sandbox.

When the agent builds a full MCP server in the sandbox (with bidirectional tool
support), it calls this tool to register, start, and discover tools from it.
Auto-detection of MCP Apps (tools with _meta.ui) happens through the existing
pipeline.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from src.domain.ports.services.sandbox_port import SandboxPort


from src.domain.events.agent_events import AgentMCPAppRegisteredEvent
from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)

TOOL_NAME = "register_mcp_server"
TOOL_DESCRIPTION = (
    "Register and start an MCP server that you built in the sandbox. "
    "Use this when you have created a full MCP server (not just HTML) that "
    "provides tools for bidirectional interaction.\n\n"
    "After registration, the server's tools are discovered automatically. "
    "Any tool that declares _meta.ui.resourceUri will auto-render its UI in "
    "the Canvas panel when called.\n\n"
    "The MCP server MUST implement resources/read to serve HTML for _meta.ui tools. "
    "HTML is fetched live from the server each time, never cached in the database.\n\n"
    "Example for stdio server:\n"
    "  server_type='stdio', command='node', args=['server.js']\n\n"
    "Example for SSE server:\n"
    "  server_type='sse', url='http://localhost:3001/sse'\n\n"
    "Example for HTTP server:\n"
    "  server_type='http', url='http://localhost:3001/mcp'\n\n"
    "Example for WebSocket server:\n"
    "  server_type='websocket', url='ws://localhost:3001/ws'"
)


class RegisterMCPServerTool(AgentTool):
    """Agent tool for registering MCP servers built in the sandbox."""

    def __init__(
        self,
        tenant_id: str,
        project_id: str,
        sandbox_adapter: SandboxPort | None = None,
        sandbox_id: str | None = None,
        session_factory: Any | None = None,
    ) -> None:
        super().__init__(name=TOOL_NAME, description=TOOL_DESCRIPTION)
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._sandbox_adapter = sandbox_adapter
        self._sandbox_id = sandbox_id
        self._session_factory = session_factory
        self._pending_events: list[Any] = []

    def set_sandbox_id(self, sandbox_id: str) -> None:
        """Set sandbox ID (called when sandbox becomes available)."""
        self._sandbox_id = sandbox_id

    def consume_pending_events(self) -> list[Any]:
        """Consume pending SSE events (called by processor after execute)."""
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server_name": {
                    "type": "string",
                    "description": (
                        "Unique name for the MCP server (e.g., 'sales-dashboard-server'). "
                        "Use lowercase with hyphens."
                    ),
                },
                "server_type": {
                    "type": "string",
                    "enum": ["stdio", "sse", "http", "websocket"],
                    "description": (
                        "Transport type: 'stdio' for command-line servers, "
                        "'sse' for SSE servers, 'http' for HTTP servers, "
                        "'websocket' for WebSocket servers."
                    ),
                },
                "command": {
                    "type": "string",
                    "description": (
                        "Command to start the server (e.g., 'node', 'python', 'npx'). "
                        "Required for stdio servers."
                    ),
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Arguments for the command (e.g., ['server.js', '--port', '3001'])."
                    ),
                },
                "url": {
                    "type": "string",
                    "description": (
                        "URL for network servers (e.g., 'http://localhost:3001/mcp'). "
                        "Required for sse, http, and websocket servers."
                    ),
                },
            },
            "required": ["server_name", "server_type"],
        }

    def validate_args(self, **kwargs: Any) -> bool:
        server_name = kwargs.get("server_name", "")
        server_type = kwargs.get("server_type", "")
        if not server_name or not server_type:
            return False
        if server_type == "stdio" and not kwargs.get("command"):
            return False
        return not (server_type in ("sse", "http", "websocket") and not kwargs.get("url"))

    async def execute(self, **kwargs: Any) -> str:
        """Register, start, and discover tools from an MCP server."""
        server_name = kwargs.get("server_name", "")
        server_type = kwargs.get("server_type", "stdio")
        command = kwargs.get("command", "")
        args = kwargs.get("args", [])
        url = kwargs.get("url", "")

        validation_error = self._validate_execute_params(server_name, server_type, command, url)
        if validation_error:
            return validation_error

        transport_config = (
            {"command": command, "args": args} if server_type == "stdio" else {"url": url}
        )
        config_json = json.dumps(transport_config)

        try:
            install_error = await self._install_and_start_server(
                server_name, server_type, config_json
            )
            if install_error:
                return install_error

            tools, discover_error = await self._discover_tools(server_name)
            if discover_error:
                return discover_error

            tool_names = [t.get("name", "unknown") for t in tools]
            app_tools = await self._detect_and_persist_apps(server_name, tools)
            namespaced_tool_names = [f"mcp__{server_name}__{name}" for name in tool_names]

            self._emit_tools_updated_event(server_name, namespaced_tool_names)
            lifecycle_result = self._run_lifecycle_and_emit(server_name, namespaced_tool_names)

            if lifecycle_result["probe"].get("status") == "missing_tools":
                logger.warning(
                    "register_mcp_server probe detected missing tools for %s: %s",
                    server_name,
                    lifecycle_result["probe"].get("missing_tools"),
                )

            result = (
                f"MCP server '{server_name}' registered and started successfully.\n"
                f"Discovered {len(tool_names)} tool(s): {', '.join(tool_names)}"
            )
            if app_tools:
                result += (
                    f"\n\nDetected {len(app_tools)} MCP App(s) with UI: {', '.join(app_tools)}"
                )
            return result

        except Exception as e:
            logger.error("Failed to register MCP server '%s': %s", server_name, e)
            return f"Error: Failed to register MCP server '{server_name}':\n{e}"

    def _validate_execute_params(
        self,
        server_name: str,
        server_type: str,
        command: str,
        url: str,
    ) -> str | None:
        """Validate execute parameters. Returns error string or None."""
        if not server_name:
            return "Error: server_name is required."
        if server_type not in ("stdio", "sse", "http", "websocket"):
            return (
                f"Error: Invalid server_type '{server_type}'. "
                "Must be 'stdio', 'sse', 'http', or 'websocket'."
            )
        if server_type == "stdio" and not command:
            return "Error: 'command' is required for stdio servers."
        if server_type in ("sse", "http", "websocket") and not url:
            return f"Error: 'url' is required for {server_type} servers."
        if not self._sandbox_adapter or not self._sandbox_id:
            return (
                "Error: Sandbox not available. "
                "This tool requires a running sandbox with MCP support."
            )
        return None

    async def _install_and_start_server(
        self,
        server_name: str,
        server_type: str,
        config_json: str,
    ) -> str | None:
        """Install and start the MCP server. Returns error string or None."""
        install_result = await self._sandbox_adapter.call_tool(  # type: ignore[union-attr]
            sandbox_id=self._sandbox_id,  # type: ignore[arg-type]
            tool_name="mcp_server_install",
            arguments={
                "name": server_name,
                "server_type": server_type,
                "transport_config": config_json,
            },
            timeout=120.0,
        )
        install_data = self._parse_result(install_result)
        if not install_data.get("success", False):
            error = install_data.get("error", "Installation failed")
            return f"Error: Failed to install MCP server '{server_name}':\n{error}"

        start_result = await self._sandbox_adapter.call_tool(  # type: ignore[union-attr]
            sandbox_id=self._sandbox_id,  # type: ignore[arg-type]
            tool_name="mcp_server_start",
            arguments={
                "name": server_name,
                "server_type": server_type,
                "transport_config": config_json,
            },
            timeout=60.0,
        )
        start_data = self._parse_result(start_result)
        if not start_data.get("success", False):
            error = start_data.get("error", "Start failed")
            return f"Error: Failed to start MCP server '{server_name}':\n{error}"

        return None

    async def _discover_tools(self, server_name: str) -> tuple[list[dict[str, Any]], str | None]:
        """Discover tools from the server. Returns (tools, error_string_or_None)."""
        discover_result = await self._sandbox_adapter.call_tool(  # type: ignore[union-attr]
            sandbox_id=self._sandbox_id,  # type: ignore[arg-type]
            tool_name="mcp_server_discover_tools",
            arguments={"name": server_name},
            timeout=20.0,
        )
        if discover_result.get("is_error") or discover_result.get("isError"):
            error_text = self._extract_error_text(discover_result)
            return [], (
                f"Error: MCP server '{server_name}' was installed and started, "
                f"but tool discovery failed: {error_text}"
            )
        tools = self._parse_result(discover_result)
        if not isinstance(tools, list):
            tools = []
        return tools, None

    def _emit_tools_updated_event(self, server_name: str, namespaced_tool_names: list[str]) -> None:
        """Emit AgentToolsUpdatedEvent for real-time frontend update."""
        from src.domain.events.agent_events import AgentToolsUpdatedEvent

        self._pending_events.append(
            AgentToolsUpdatedEvent(
                project_id=self._project_id,
                tool_names=namespaced_tool_names,
                server_name=server_name,
                requires_refresh=True,
            )
        )
        logger.info(
            "Queued AgentToolsUpdatedEvent for server %s with %d tools",
            server_name,
            len(namespaced_tool_names),
        )

    def _run_lifecycle_and_emit(
        self, server_name: str, namespaced_tool_names: list[str]
    ) -> dict[str, Any]:
        """Run lifecycle orchestrator and emit toolset_changed event."""
        from src.infrastructure.agent.tools.self_modifying_lifecycle import (
            SelfModifyingLifecycleOrchestrator,
        )

        lifecycle_result = SelfModifyingLifecycleOrchestrator.run_post_change(
            source=TOOL_NAME,
            tenant_id=self._tenant_id,
            project_id=self._project_id,
            clear_tool_definitions=True,
            expected_tool_names=namespaced_tool_names,
            metadata={"server_name": server_name},
        )
        logger.info(
            "register_mcp_server lifecycle completed for project %s: %s",
            self._project_id,
            lifecycle_result["cache_invalidation"],
        )
        self._pending_events.append(
            {
                "type": "toolset_changed",
                "data": {
                    "source": TOOL_NAME,
                    "project_id": self._project_id,
                    "tenant_id": self._tenant_id,
                    "server_name": server_name,
                    "tool_names": namespaced_tool_names,
                    "lifecycle": lifecycle_result,
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        return lifecycle_result

    async def _detect_and_persist_apps(self, server_name: str, tools: list[dict[str, Any]]) -> list[str]:
        """Detect tools with UI metadata and persist as MCP Apps."""
        app_tools = []
        for t in tools:
            meta = t.get("_meta", {}) or {}
            ui = meta.get("ui", {}) or {}
            resource_uri = ui.get("resourceUri", "")
            if resource_uri:
                tool_name = t.get("name", "unknown")
                app_tools.append(tool_name)

                # Persist to DB via MCPAppService
                app_id = ""
                if self._session_factory:
                    try:
                        app_id = await self._persist_app(
                            server_name=server_name,
                            tool_name=tool_name,
                            resource_uri=resource_uri,
                            ui_metadata=ui,
                        )
                    except Exception as e:
                        logger.warning("Failed to persist MCP App %s: %s", tool_name, e)

                self._pending_events.append(
                    AgentMCPAppRegisteredEvent(
                        app_id=app_id,
                        server_name=server_name,
                        tool_name=tool_name,
                        source="agent_developed",
                        resource_uri=resource_uri,
                        title=ui.get("title"),
                    )
                )

        return app_tools

    async def _persist_app(
        self,
        server_name: str,
        tool_name: str,
        resource_uri: str,
        ui_metadata: dict[str, Any],
    ) -> str:
        """Persist an auto-detected MCP App to the database. Returns app ID."""
        from src.domain.model.mcp.app import (
            MCPApp,
            MCPAppSource,
            MCPAppStatus,
            MCPAppUIMetadata,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_mcp_app_repository import (
            SqlMCPAppRepository,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
            SqlMCPServerRepository,
        )

        # Try to get the MCPServer entity to get its ID
        server_id = None
        if self._session_factory:
            try:
                async with self._session_factory() as session:
                    server_repo = SqlMCPServerRepository(session)
                    # Look up server by name and project
                    server_entity = await server_repo.get_by_name(
                        project_id=self._project_id,
                        name=server_name,
                    )
                    if server_entity:
                        server_id = server_entity.id
                        logger.debug(f"Found MCPServer entity for {server_name}: id={server_id}")
            except Exception as e:
                logger.warning(f"Failed to look up MCPServer entity: {e}")

        # If no server_id found, keep it as None (nullable in DB)
        # server_name will be used for matching instead
        if not server_id:
            logger.debug(
                f"No MCPServer entity found for {server_name}, "
                f"persisting MCPApp with server_id=None"
            )

        app = MCPApp(
            project_id=self._project_id,
            tenant_id=self._tenant_id,
            server_id=server_id,
            server_name=server_name,
            tool_name=tool_name,
            ui_metadata=MCPAppUIMetadata(
                resource_uri=resource_uri,
                permissions=ui_metadata.get("permissions", []),
                csp=ui_metadata.get("csp", {}),
                title=ui_metadata.get("title"),
            ),
            source=MCPAppSource.AGENT_DEVELOPED,
            status=MCPAppStatus.DISCOVERED,
        )

        if self._session_factory is None:
            raise RuntimeError("session_factory is required to persist MCP apps")
        async with self._session_factory() as session:
            repo = SqlMCPAppRepository(session)
            await repo.save(app)
            await session.commit()

        return app.id

    @staticmethod
    def _extract_error_text(result: dict[str, Any]) -> str:
        """Extract human-readable error text from an MCP result."""
        content = result.get("content", [])
        for item in content:
            if item.get("type") == "text":
                text = item.get("text", "")
                if text.startswith("Error: "):
                    text = text[7:]
                return cast(str, text)
        return cast(str, result.get("error_message", "Unknown error"))

    @staticmethod
    def _parse_result(result: dict[str, Any]) -> Any:
        """Parse MCP tool call result, extracting text content."""
        if not result:
            return {}
        content = result.get("content", [])
        if not content:
            return {}
        for item in content:
            if item.get("type") == "text":
                text = item.get("text", "")
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return {"text": text}
        return {}
