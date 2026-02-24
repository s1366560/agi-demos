"""MCP App Resource Resolver.

Resolves ui:// resource URIs by fetching HTML content from MCP servers.
Supports both sandbox-hosted and external MCP servers.
"""

import asyncio
import enum
import logging
from collections.abc import Callable
from typing import Any

from src.domain.model.mcp.app import MCPAppResource

logger = logging.getLogger(__name__)

MAX_RESOURCE_SIZE = 5 * 1024 * 1024  # 5MB max HTML resource size
RESOLVE_TIMEOUT_SECONDS = 30  # Timeout for resource resolution calls


class ResourceErrorKind(enum.Enum):
    """Classification of resource resolution errors."""

    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
    TOO_LARGE = "too_large"
    SERVER_ERROR = "server_error"
    NETWORK = "network"
    NO_MANAGER = "no_manager"


class ResourceResolutionError(Exception):
    """Structured error for MCP App resource resolution failures."""

    def __init__(self, message: str, kind: ResourceErrorKind) -> None:
        super().__init__(message)
        self.kind = kind


class MCPAppResourceResolver:
    """Resolves ui:// URIs to HTML content by calling MCP resources/read."""

    def __init__(
        self,
        sandbox_mcp_server_manager: Any = None,
        manager_factory: Callable | None = None,
    ) -> None:
        """Initialize resource resolver.

        Accepts either a direct manager instance or a factory callable
        to avoid circular dependency when constructed from DI container.
        The factory is called lazily on first resolve() invocation.

        Args:
            sandbox_mcp_server_manager: Direct manager instance (preferred).
            manager_factory: Callable that returns a manager instance (lazy init).
        """
        self._mcp_manager = sandbox_mcp_server_manager
        self._manager_factory = manager_factory

    def _get_manager(self) -> Any:
        """Get the MCP manager, creating it lazily from factory if needed."""
        if self._mcp_manager is None and self._manager_factory is not None:
            self._mcp_manager = self._manager_factory()
        if self._mcp_manager is None:
            raise ResourceResolutionError(
                "MCPAppResourceResolver: No sandbox_mcp_server_manager available. "
                "Provide either a direct instance or a manager_factory.",
                kind=ResourceErrorKind.NO_MANAGER,
            )
        return self._mcp_manager

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
            resource_uri,
            server_name,
        )

        if not resource_uri:
            raise ResourceResolutionError("Empty resource URI", kind=ResourceErrorKind.NOT_FOUND)

        try:
            manager = self._get_manager()
            result = await asyncio.wait_for(
                manager.call_tool(
                    project_id=project_id,
                    server_name=server_name,
                    tool_name="__resources_read__",
                    arguments={"uri": resource_uri},
                ),
                timeout=RESOLVE_TIMEOUT_SECONDS,
            )

            if result.is_error:
                error_text = self._extract_text(result.content)
                raise ResourceResolutionError(
                    f"Failed to resolve resource: {error_text}",
                    kind=ResourceErrorKind.SERVER_ERROR,
                )

            html_content = self._extract_resource_content(result.content, resource_uri)

            if len(html_content.encode("utf-8")) > MAX_RESOURCE_SIZE:
                raise ResourceResolutionError(
                    f"Resource too large: {len(html_content)} bytes (max {MAX_RESOURCE_SIZE})",
                    kind=ResourceErrorKind.TOO_LARGE,
                )

            return MCPAppResource(
                uri=resource_uri,
                html_content=html_content,
                size_bytes=len(html_content.encode("utf-8")),
            )

        except (ValueError, ResourceResolutionError):
            raise
        except TimeoutError:
            logger.error(
                "Timeout resolving resource %s (server=%s, %ds)",
                resource_uri,
                server_name,
                RESOLVE_TIMEOUT_SECONDS,
            )
            raise ResourceResolutionError(
                f"Resource resolution timed out after {RESOLVE_TIMEOUT_SECONDS}s "
                f"for {resource_uri}",
                kind=ResourceErrorKind.TIMEOUT,
            )
        except (OSError, ConnectionError) as e:
            logger.error("Network error resolving resource %s: %s", resource_uri, e)
            raise ResourceResolutionError(
                f"Network error resolving resource: {e}",
                kind=ResourceErrorKind.NETWORK,
            ) from e
        except Exception as e:
            logger.error("Error resolving resource %s: %s", resource_uri, e)
            raise ResourceResolutionError(
                f"Resource resolution failed: {e}",
                kind=ResourceErrorKind.SERVER_ERROR,
            ) from e

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

        raise ResourceResolutionError(
            f"No HTML content found for resource {resource_uri}",
            kind=ResourceErrorKind.NOT_FOUND,
        )

    @staticmethod
    def _extract_text(content: list) -> str:
        """Extract text from MCP content items."""
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)
