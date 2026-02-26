"""MCP Server Templates - Standardized starting points for MCP server development.

This module provides templates for common MCP server patterns,
enabling agents to quickly scaffold new servers with best practices.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, cast, override

if TYPE_CHECKING:
    from src.domain.ports.services.sandbox_port import SandboxPort


from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)


# =============================================================================
# Template Definitions
# =============================================================================

TEMPLATES = {
    "web-dashboard": {
        "name": "web-dashboard",
        "description": "Interactive web dashboard with real-time updates",
        "dependencies": ["mcp", "jinja2"],
        "files": [
            {
                "path": "{{server_name}}/server.py",
                "content": '''"""MCP Server: {{server_name}} - Web Dashboard."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
import asyncio

# Create server instance
server = Server("{{server_name}}")


@server.list_tools()
async def list_tools():
    """List available tools."""
    return [
        {
            "name": "render_dashboard",
            "description": "Render the dashboard UI",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "data": {"type": "object", "description": "Dashboard data"}
                }
            },
            "_meta": {
                "ui": {
                    "resourceUri": "ui://{{server_name}}/dashboard",
                    "title": "{{server_name}} Dashboard"
                }
            }
        },
        {
            "name": "update_metrics",
            "description": "Update dashboard metrics",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "metrics": {"type": "object"}
                }
            }
        }
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""
    if name == "render_dashboard":
        return {"content": [{"type": "text", "text": "Dashboard rendered"}]}
    elif name == "update_metrics":
        return {"content": [{"type": "text", "text": "Metrics updated"}]}
    raise ValueError(f"Unknown tool: {name}")


@server.list_resources()
async def list_resources():
    """List available resources."""
    return [
        {
            "uri": "ui://{{server_name}}/dashboard",
            "name": "Dashboard UI",
            "mimeType": "text/html"
        }
    ]


@server.read_resource()
async def read_resource(uri):
    """Read resource content."""
    uri = str(uri)
    if uri == "ui://{{server_name}}/dashboard":
        html = """
        <!DOCTYPE html>
        <html>
        <head><title>{{server_name}} Dashboard</title></head>
        <body>
            <h1>{{server_name}} Dashboard</h1>
            <div id="metrics">Loading...</div>
        </body>
        </html>
        """
        return {"contents": [{"uri": uri, "mimeType": "text/html", "text": html}]}
    raise ValueError(f"Unknown resource: {uri}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream)


if __name__ == "__main__":
    asyncio.run(main())
''',
            },
            {
                "path": "{{server_name}}/pyproject.toml",
                "content": """[project]
name = "{{server_name}}"
version = "0.1.0"
dependencies = ["mcp", "jinja2"]

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
""",
            },
        ],
    },
    "api-wrapper": {
        "name": "api-wrapper",
        "description": "Wrapper for external REST APIs",
        "dependencies": ["mcp", "httpx"],
        "files": [
            {
                "path": "{{server_name}}/server.py",
                "content": '''"""MCP Server: {{server_name}} - API Wrapper."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
import asyncio
import httpx

# Create server instance
server = Server("{{server_name}}")

# API base URL (configure as needed)
API_BASE_URL = "https://api.example.com"


@server.list_tools()
async def list_tools():
    """List available tools."""
    return [
        {
            "name": "api_get",
            "description": "Make GET request to API",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "endpoint": {"type": "string", "description": "API endpoint path"},
                    "params": {"type": "object", "description": "Query parameters"}
                },
                "required": ["endpoint"]
            }
        },
        {
            "name": "api_post",
            "description": "Make POST request to API",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "endpoint": {"type": "string"},
                    "data": {"type": "object"}
                },
                "required": ["endpoint"]
            }
        }
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""
    async with httpx.AsyncClient() as client:
        if name == "api_get":
            endpoint = arguments.get("endpoint", "")
            params = arguments.get("params", {})
            response = await client.get(f"{API_BASE_URL}{endpoint}", params=params)
            return {"content": [{"type": "text", "text": response.text}]}
        elif name == "api_post":
            endpoint = arguments.get("endpoint", "")
            data = arguments.get("data", {})
            response = await client.post(f"{API_BASE_URL}{endpoint}", json=data)
            return {"content": [{"type": "text", "text": response.text}]}
    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream)


if __name__ == "__main__":
    asyncio.run(main())
''',
            },
            {
                "path": "{{server_name}}/pyproject.toml",
                "content": """[project]
name = "{{server_name}}"
version = "0.1.0"
dependencies = ["mcp", "httpx"]

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
""",
            },
        ],
    },
    "data-processor": {
        "name": "data-processor",
        "description": "Data processing and transformation server",
        "dependencies": ["mcp", "pandas"],
        "files": [
            {
                "path": "{{server_name}}/server.py",
                "content": '''"""MCP Server: {{server_name}} - Data Processor."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
import asyncio
import pandas as pd

# Create server instance
server = Server("{{server_name}}")


@server.list_tools()
async def list_tools():
    """List available tools."""
    return [
        {
            "name": "process_csv",
            "description": "Process CSV data",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "csv_data": {"type": "string", "description": "CSV data as string"},
                    "operations": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["csv_data"]
            }
        },
        {
            "name": "transform_data",
            "description": "Transform data with specified operations",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "data": {"type": "array"},
                    "transform_type": {"type": "string", "enum": ["filter", "sort", "aggregate"]}
                }
            }
        },
        {
            "name": "export_result",
            "description": "Export processed data",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "format": {"type": "string", "enum": ["csv", "json"]}
                }
            }
        }
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""
    if name == "process_csv":
        csv_data = arguments.get("csv_data", "")
        df = pd.read_csv(pd.io.common.StringIO(csv_data))
        return {"content": [{"type": "text", "text": df.to_json()}]}
    elif name == "transform_data":
        return {"content": [{"type": "text", "text": "Transformed"}]}
    elif name == "export_result":
        return {"content": [{"type": "text", "text": "Exported"}]}
    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream)


if __name__ == "__main__":
    asyncio.run(main())
''',
            },
            {
                "path": "{{server_name}}/pyproject.toml",
                "content": """[project]
name = "{{server_name}}"
version = "0.1.0"
dependencies = ["mcp", "pandas"]

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
""",
            },
        ],
    },
}


# =============================================================================
# Helper Functions
# =============================================================================


def list_available_templates() -> list[dict[str, str]]:
    """List all available templates.

    Returns:
        List of template info dicts with name and description
    """
    return [{"name": t["name"], "description": t["description"]} for t in TEMPLATES.values()]  # type: ignore[dict-item]


def get_template_by_name(name: str) -> dict[str, Any] | None:
    """Get template by name.

    Args:
        name: Template name

    Returns:
        Template dict or None if not found
    """
    return TEMPLATES.get(name)


def render_template_content(content: str, variables: dict[str, str]) -> str:
    """Render template content with variable substitution.

    Uses simple {{variable}} syntax for substitution.

    Args:
        content: Template content with {{variable}} placeholders
        variables: Dict of variable names to values

    Returns:
        Rendered content with variables substituted
    """
    result = content

    for key, value in variables.items():
        placeholder = "{{" + key + "}}"
        result = result.replace(placeholder, str(value))

    # Remove any unrendered placeholders (optional, based on preference)
    # result = re.sub(r'\{\{[^}]+\}\}', '', result)

    return result


# =============================================================================
# Tool Implementation
# =============================================================================


class CreateMCPServerFromTemplateTool(AgentTool):
    """Tool for creating MCP servers from templates.

    Creates a new MCP server based on a predefined template,
    writing files to the sandbox and optionally installing dependencies.
    """

    def __init__(
        self,
        sandbox_adapter: SandboxPort,
        sandbox_id: str,
        workspace_path: str = "/workspace",
    ) -> None:
        """Initialize the template tool.

        Args:
            sandbox_adapter: MCPSandboxAdapter instance
            sandbox_id: Sandbox container ID
            workspace_path: Path to workspace in sandbox
        """
        super().__init__(
            name="create_mcp_server_from_template",
            description=(
                "Create a new MCP server from a predefined template. "
                "Available templates: web-dashboard, api-wrapper, data-processor. "
                "Creates server files and optionally installs dependencies."
            ),
        )
        self._sandbox_adapter = sandbox_adapter
        self._sandbox_id = sandbox_id
        self._workspace_path = workspace_path

    @property
    @override
    def name(self) -> str:
        return "create_mcp_server_from_template"

    @property
    @override
    def description(self) -> str:
        return (
            "Create a new MCP server from a predefined template. "
            "Available templates: web-dashboard, api-wrapper, data-processor. "
            "Creates server files and optionally installs dependencies."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "template": {
                    "type": "string",
                    "description": "Template name (web-dashboard, api-wrapper, data-processor)",
                    "enum": ["web-dashboard", "api-wrapper", "data-processor"],
                },
                "server_name": {
                    "type": "string",
                    "description": "Name for the new server (alphanumeric and dashes)",
                },
                "install_deps": {
                    "type": "boolean",
                    "description": "Whether to install dependencies (default: true)",
                    "default": True,
                },
            },
            "required": ["template", "server_name"],
        }

    @override
    def get_parameters_schema(self) -> dict[str, Any]:
        return self.parameters

    async def execute(  # type: ignore[override]
        self,
        template: str,
        server_name: str,
        install_deps: bool = True,
    ) -> str:
        """Execute the template creation tool.

        Args:
            template: Template name
            server_name: Name for the new server
            install_deps: Whether to install dependencies

        Returns:
            Result message
        """
        # Validate template
        template_data = get_template_by_name(template)
        if not template_data:
            available = ", ".join(t["name"] for t in list_available_templates())
            return f"Error: Template '{template}' not found. Available: {available}"

        # Validate server name
        if not re.match(r"^[a-z][a-z0-9-]*$", server_name):
            return (
                f"Error: Invalid server name '{server_name}'. "
                "Use lowercase letters, numbers, and dashes only."
            )

        logger.info("Creating MCP server '%s' from template '%s'", server_name, template)

        # Render and write files
        server_path = f"{self._workspace_path}/{server_name}"
        files_created = []

        for file_info in template_data["files"]:
            # Render content
            rendered_content = render_template_content(
                file_info["content"],
                {"server_name": server_name, "description": f"{server_name} MCP server"},
            )

            # Render path
            rendered_path = render_template_content(file_info["path"], {"server_name": server_name})

            full_path = f"{self._workspace_path}/{rendered_path}"

            # Write file
            try:
                await self._sandbox_adapter.call_tool(
                    sandbox_id=self._sandbox_id,
                    tool_name="write",
                    arguments={
                        "path": full_path,
                        "content": rendered_content,
                    },
                )
                files_created.append(rendered_path)
                logger.debug("Created file: %s", rendered_path)
            except Exception as e:
                logger.error("Failed to write file %s: %s", rendered_path, e)
                return f"Error: Failed to create file {rendered_path}: {e}"

        # Install dependencies
        if install_deps and template_data.get("dependencies"):
            deps = " ".join(template_data["dependencies"])
            try:
                await self._sandbox_adapter.call_tool(
                    sandbox_id=self._sandbox_id,
                    tool_name="bash",
                    arguments={
                        "command": f"cd {server_path} && pip install {deps}",
                    },
                )
                logger.info("Installed dependencies: %s", deps)
            except Exception as e:
                logger.warning("Failed to install dependencies: %s", e)
                # Continue anyway - deps can be installed manually

        return (
            f"Successfully created MCP server '{server_name}' from template '{template}'.\n"
            f"Files created: {', '.join(files_created)}\n"
            f"Dependencies: {', '.join(template_data.get('dependencies', []))}"
        )


# =============================================================================
# Functional tool: @tool_define version
# =============================================================================

# ---------------------------------------------------------------------------
# Module-level DI references
# ---------------------------------------------------------------------------

_template_sandbox_adapter: SandboxPort | None = None
_template_sandbox_id: str | None = None
_template_workspace_path: str = "/workspace"


def configure_create_mcp_server_from_template_tool(
    sandbox_adapter: SandboxPort,
    sandbox_id: str,
    workspace_path: str = "/workspace",
) -> None:
    """Inject runtime dependencies for create_mcp_server_from_template_tool."""
    global _template_sandbox_adapter, _template_sandbox_id, _template_workspace_path
    _template_sandbox_adapter = sandbox_adapter
    _template_sandbox_id = sandbox_id
    _template_workspace_path = workspace_path


# ---------------------------------------------------------------------------
# Helper: validate inputs
# ---------------------------------------------------------------------------


def _template_validate_inputs(
    template: str,
    server_name: str,
) -> str | None:
    """Validate template name and server name. Returns error string or None."""
    template_data = get_template_by_name(template)
    if not template_data:
        available = ", ".join(t["name"] for t in list_available_templates())
        return f"Error: Template '{template}' not found. Available: {available}"
    if not re.match(r"^[a-z][a-z0-9-]*$", server_name):
        return (
            f"Error: Invalid server name '{server_name}'. "
            "Use lowercase letters, numbers, and dashes only."
        )
    if not _template_sandbox_adapter or not _template_sandbox_id:
        return (
            "Error: Sandbox not available. "
            "This tool requires a running sandbox with MCP support."
        )
    return None


# ---------------------------------------------------------------------------
# Helper: render and write files
# ---------------------------------------------------------------------------


async def _template_write_files(
    template_data: dict[str, Any],
    server_name: str,
) -> tuple[list[str], str | None]:
    """Render template files and write to sandbox. Returns (files_created, error)."""
    adapter = cast("SandboxPort", _template_sandbox_adapter)
    sid = cast(str, _template_sandbox_id)
    files_created: list[str] = []

    for file_info in template_data["files"]:
        rendered_content = render_template_content(
            file_info["content"],
            {"server_name": server_name, "description": f"{server_name} MCP server"},
        )
        rendered_path = render_template_content(
            file_info["path"], {"server_name": server_name}
        )
        full_path = f"{_template_workspace_path}/{rendered_path}"

        try:
            await adapter.call_tool(
                sandbox_id=sid,
                tool_name="write",
                arguments={"path": full_path, "content": rendered_content},
            )
            files_created.append(rendered_path)
            logger.debug("Created file: %s", rendered_path)
        except Exception as e:
            logger.error("Failed to write file %s: %s", rendered_path, e)
            return files_created, f"Error: Failed to create file {rendered_path}: {e}"

    return files_created, None


# ---------------------------------------------------------------------------
# Helper: install dependencies
# ---------------------------------------------------------------------------


async def _template_install_deps(
    template_data: dict[str, Any],
    server_name: str,
) -> None:
    """Install template dependencies in sandbox."""
    adapter = cast("SandboxPort", _template_sandbox_adapter)
    sid = cast(str, _template_sandbox_id)
    deps = " ".join(template_data["dependencies"])
    server_path = f"{_template_workspace_path}/{server_name}"

    try:
        await adapter.call_tool(
            sandbox_id=sid,
            tool_name="bash",
            arguments={"command": f"cd {server_path} && pip install {deps}"},
        )
        logger.info("Installed dependencies: %s", deps)
    except Exception as e:
        logger.warning("Failed to install dependencies: %s", e)


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool_define(
    name="create_mcp_server_from_template",
    description=(
        "Create a new MCP server from a predefined template. "
        "Available templates: web-dashboard, api-wrapper, data-processor. "
        "Creates server files and optionally installs dependencies."
    ),
    parameters={
        "type": "object",
        "properties": {
            "template": {
                "type": "string",
                "description": (
                    "Template name (web-dashboard, api-wrapper, data-processor)"
                ),
                "enum": ["web-dashboard", "api-wrapper", "data-processor"],
            },
            "server_name": {
                "type": "string",
                "description": "Name for the new server (lowercase, numbers, dashes)",
            },
            "install_deps": {
                "type": "boolean",
                "description": "Whether to install dependencies (default: true)",
                "default": True,
            },
        },
        "required": ["template", "server_name"],
    },
    permission="sandbox",
    category="mcp",
    tags=frozenset({"mcp", "template", "scaffold"}),
)
async def create_mcp_server_from_template_tool(
    ctx: ToolContext,
    *,
    template: str,
    server_name: str,
    install_deps: bool = True,
) -> ToolResult:
    """Create a new MCP server from a predefined template."""
    _ = ctx  # available for future use (permissions, emit, etc.)

    # Validate inputs
    validation_error = _template_validate_inputs(template, server_name)
    if validation_error:
        return ToolResult(output=validation_error, is_error=True)

    template_data = get_template_by_name(template)
    if not template_data:
        return ToolResult(output=f"Template '{template}' not found.", is_error=True)

    logger.info(
        "Creating MCP server '%s' from template '%s'", server_name, template
    )

    # Render and write files
    files_created, write_error = await _template_write_files(template_data, server_name)
    if write_error:
        return ToolResult(output=write_error, is_error=True)

    # Install dependencies
    if install_deps and template_data.get("dependencies"):
        await _template_install_deps(template_data, server_name)

    deps_list = template_data.get("dependencies", [])
    output = (
        f"Successfully created MCP server '{server_name}' "
        f"from template '{template}'.\n"
        f"Files created: {', '.join(files_created)}\n"
        f"Dependencies: {', '.join(deps_list)}"
    )

    return ToolResult(
        output=output,
        title=f"MCP Template: {server_name}",
        metadata={
            "template": template,
            "server_name": server_name,
            "files_created": files_created,
            "dependencies": deps_list,
        },
    )
