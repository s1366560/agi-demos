"""MCP App Resource Resolver.

Resolves ui:// resource URIs by fetching HTML content from MCP servers.
Supports both sandbox-hosted and external MCP servers.
"""

import logging
from typing import Any

from src.domain.model.mcp.app import MCPAppResource

logger = logging.getLogger(__name__)

MAX_RESOURCE_SIZE = 5 * 1024 * 1024  # 5MB max HTML resource size


class MCPAppResourceResolver:
    """Resolves ui:// URIs to HTML content by calling MCP resources/read."""

    def __init__(
        self,
        sandbox_mcp_server_manager: Any,
    ) -> None:
        self._mcp_manager = sandbox_mcp_server_manager

    async def resolve(
        self,
        project_id: str,
        server_name: str,
        resource_uri: str,
    ) -> MCPAppResource:
        """Resolve a ui:// resource URI to HTML content.

        Calls the MCP server's resources/read endpoint through the sandbox
        to fetch the HTML bundle for the app.

        Args:
            project_id: Project ID for sandbox routing.
            server_name: Name of the MCP server providing the resource.
            resource_uri: The ui:// URI to resolve.

        Returns:
            MCPAppResource with the resolved HTML content.

        Raises:
            ValueError: If the resource cannot be resolved or is too large.
        """
        logger.info(
            "Resolving MCP App resource: uri=%s, server=%s",
            resource_uri, server_name,
        )

        if not resource_uri:
            raise ValueError("Empty resource URI")

        try:
            result = await self._mcp_manager.call_tool(
                project_id=project_id,
                server_name=server_name,
                tool_name="__resources_read__",
                arguments={"uri": resource_uri},
            )

            if result.is_error:
                error_text = self._extract_text(result.content)
                raise ValueError(f"Failed to resolve resource: {error_text}")

            html_content = self._extract_resource_content(result.content, resource_uri)

            if len(html_content.encode("utf-8")) > MAX_RESOURCE_SIZE:
                raise ValueError(
                    f"Resource too large: {len(html_content)} bytes "
                    f"(max {MAX_RESOURCE_SIZE})"
                )

            return MCPAppResource(
                uri=resource_uri,
                html_content=html_content,
                size_bytes=len(html_content.encode("utf-8")),
            )

        except ValueError:
            raise
        except Exception as e:
            logger.error("Error resolving resource %s: %s", resource_uri, e)
            raise ValueError(f"Resource resolution failed: {e}") from e

    def _extract_resource_content(
        self,
        content: list,
        resource_uri: str,
    ) -> str:
        """Extract HTML content from MCP resources/read response."""
        for item in content:
            if not isinstance(item, dict):
                continue
            # Look for resource content matching our URI
            if item.get("uri") == resource_uri:
                text = item.get("text", "")
                if text:
                    return text
            # Fall back to text content
            if item.get("type") == "text":
                text = item.get("text", "")
                if text and ("<html" in text.lower() or "<!doctype" in text.lower()):
                    return text

        # Last resort: concatenate all text
        text = self._extract_text(content)
        if text:
            return text

        raise ValueError(f"No HTML content found for resource {resource_uri}")

    @staticmethod
    def _extract_text(content: list) -> str:
        """Extract text from MCP content items."""
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)
