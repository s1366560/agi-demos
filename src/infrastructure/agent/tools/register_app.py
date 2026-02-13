"""RegisterAppTool - Agent tool for registering interactive HTML apps.

When the agent creates an interactive HTML UI (dashboard, chart, form, etc.),
it calls this tool to register the app with the platform. The app is then
rendered in the Canvas panel as a sandboxed iframe.

Two modes of operation:
1. Inline HTML: pass html_content directly
2. Sandbox file: pass file_path and the tool reads HTML from the sandbox
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.domain.events.agent_events import AgentMCPAppRegisteredEvent
from src.domain.model.mcp.app import (
    MCPApp,
    MCPAppResource,
    MCPAppSource,
    MCPAppStatus,
    MCPAppUIMetadata,
)
from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)

TOOL_NAME = "register_app"
TOOL_DESCRIPTION = (
    "Register a standalone interactive HTML application to display in the Canvas panel. "
    "Use this ONLY for simple one-off UIs (dashboard, chart, form) that do NOT have "
    "a running MCP server behind them.\n\n"
    "Do NOT use this tool if the UI is backed by an MCP server with _meta.ui - "
    "those tools auto-render in Canvas when called.\n\n"
    "The HTML will be rendered in a sandboxed iframe with postMessage communication:\n"
    "- Receive data: window.addEventListener('message', handler)\n"
    "- Message format: {type: 'ui/toolResult', toolResult: {...}}\n\n"
    "Provide EITHER html_content (inline HTML string) OR file_path (path in sandbox).\n\n"
    "If linking to an existing MCP server tool, pass mcp_server_name and mcp_tool_name "
    "to store metadata only (HTML is served live by the MCP server, not from database)."
)

# Maximum HTML size: 5MB
MAX_HTML_SIZE = 5 * 1024 * 1024


class RegisterAppTool(AgentTool):
    """Agent tool for registering interactive HTML apps in the Canvas."""

    def __init__(
        self,
        tenant_id: str,
        project_id: str,
        session_factory: Optional[Any] = None,
        sandbox_adapter: Optional[Any] = None,
        sandbox_id: Optional[str] = None,
    ) -> None:
        super().__init__(name=TOOL_NAME, description=TOOL_DESCRIPTION)
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._session_factory = session_factory
        self._sandbox_adapter = sandbox_adapter
        self._sandbox_id = sandbox_id
        self._pending_events: List[Any] = []

    def set_sandbox_id(self, sandbox_id: str) -> None:
        """Set sandbox ID (called when sandbox becomes available)."""
        self._sandbox_id = sandbox_id

    def consume_pending_events(self) -> List[Any]:
        """Consume pending SSE events (called by processor after execute)."""
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Display title for the app (e.g., 'Sales Dashboard')",
                },
                "html_content": {
                    "type": "string",
                    "description": (
                        "Complete HTML document string. Use this for inline HTML. "
                        "Must be a valid HTML document with <html> tags."
                    ),
                },
                "file_path": {
                    "type": "string",
                    "description": (
                        "Path to an HTML file in the sandbox (e.g., '/workspace/dashboard.html'). "
                        "Use this instead of html_content for large files."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "Brief description of what the app does",
                },
                "mcp_server_name": {
                    "type": "string",
                    "description": (
                        "If this app is backed by an MCP server tool, the server name "
                        "(e.g., 'mcp-hello-app'). Used to link the app to the MCP tool."
                    ),
                },
                "mcp_tool_name": {
                    "type": "string",
                    "description": (
                        "If this app is backed by an MCP server tool, the tool name "
                        "(e.g., 'hello'). Used to link the app to the MCP tool."
                    ),
                },
            },
            "required": ["title"],
        }

    def validate_args(self, **kwargs: Any) -> bool:
        if "title" not in kwargs or not kwargs.get("title"):
            return False
        if not kwargs.get("html_content") and not kwargs.get("file_path"):
            return False
        return True

    async def execute(
        self,
        title: str,
        html_content: Optional[str] = None,
        file_path: Optional[str] = None,
        description: Optional[str] = None,
        mcp_server_name: Optional[str] = None,
        mcp_tool_name: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Register an interactive HTML app."""
        self._pending_events.clear()
        self._last_app_id = None
        self._last_html = None
        self._last_title = None

        if not html_content and not file_path:
            return "Error: Provide either html_content or file_path"

        # Read HTML from sandbox file if file_path provided
        if file_path and not html_content:
            html_content = await self._read_sandbox_file(file_path)
            if html_content is None:
                return f"Error: Could not read file '{file_path}' from sandbox"

        if len(html_content) > MAX_HTML_SIZE:
            return f"Error: HTML content exceeds {MAX_HTML_SIZE // 1024 // 1024}MB limit"

        # Create MCPApp record
        # Use actual MCP server/tool names if provided, otherwise generate synthetic names
        app_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        server_name = mcp_server_name or f"agent-{title.lower().replace(' ', '-')[:30]}"
        tool_name = mcp_tool_name or f"app_{title.lower().replace(' ', '_')[:30]}"
        resource_uri = f"ui://agent-app/{app_id}/index.html"

        # Always store HTML as a DB cache. For MCP server-backed tools, the
        # processor fetches fresh HTML from the MCP server on each tool call,
        # but DB serves as fallback for Open App / page refresh scenarios.
        app = MCPApp(
            id=app_id,
            project_id=self._project_id,
            tenant_id=self._tenant_id,
            server_id=None,
            server_name=server_name,
            tool_name=tool_name,
            ui_metadata=MCPAppUIMetadata(
                resource_uri=resource_uri,
                title=title,
            ),
            resource=MCPAppResource(
                uri=resource_uri,
                html_content=html_content,
                resolved_at=now,
                size_bytes=len(html_content.encode("utf-8")),
            ),
            source=MCPAppSource.AGENT_DEVELOPED,
            status=MCPAppStatus.READY,
            created_at=now,
        )

        # Persist to database
        try:
            await self._save_app(app)
        except Exception as e:
            logger.error("Failed to save MCP App: %s", e)
            return f"Error: Failed to save app - {e!s}"

        # Queue SSE event for processor to emit
        self._pending_events.append(
            AgentMCPAppRegisteredEvent(
                app_id=app_id,
                server_name=app.server_name,
                tool_name=app.tool_name,
                source=MCPAppSource.AGENT_DEVELOPED.value,
                resource_uri=app.ui_metadata.resource_uri,
                title=title,
            )
        )

        # Set has_ui so processor emits AgentMCPAppResultEvent
        self._last_app_id = app_id
        self._last_html = html_content
        self._last_title = title

        size_kb = len(html_content.encode("utf-8")) / 1024
        logger.info("Registered MCP App: id=%s, title=%s, size=%.1fKB", app_id, title, size_kb)

        return (
            f"App '{title}' registered successfully (id: {app_id}, "
            f"size: {size_kb:.1f}KB). The app is now visible in the Canvas panel."
        )

    # -- has_ui / ui_metadata for processor integration --

    @property
    def has_ui(self) -> bool:
        """Return True after successful execute() so processor emits app event."""
        return hasattr(self, "_last_app_id") and self._last_app_id is not None

    @property
    def ui_metadata(self) -> Optional[Dict[str, Any]]:
        """Return UI metadata for the last registered app."""
        if not self.has_ui:
            return None
        return {
            "resourceUri": f"ui://agent-app/{self._last_app_id}/index.html",
            "title": getattr(self, "_last_title", "App"),
        }

    async def _save_app(self, app: MCPApp) -> None:
        """Save app to database via session factory."""
        if not self._session_factory:
            logger.warning("No session_factory - app will not persist to database")
            return

        from src.infrastructure.adapters.secondary.persistence.sql_mcp_app_repository import (
            SqlMCPAppRepository,
        )

        async with self._session_factory() as session:
            repo = SqlMCPAppRepository(session)
            await repo.save(app)
            await session.commit()

    async def _read_sandbox_file(self, file_path: str) -> Optional[str]:
        """Read a file from the sandbox."""
        if not self._sandbox_adapter or not self._sandbox_id:
            logger.error("No sandbox adapter/id - cannot read file")
            return None

        try:
            result = await self._sandbox_adapter.execute_tool(
                sandbox_id=self._sandbox_id,
                tool_name="read",
                arguments={"path": file_path},
                timeout=30.0,
            )
            # Extract text content from MCP result
            content = result.get("content", [])
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        return item.get("text", "")
            if isinstance(content, str):
                return content
            return str(result) if result else None
        except Exception as e:
            logger.error("Failed to read sandbox file '%s': %s", file_path, e)
            return None
