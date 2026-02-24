"""
MCP App Domain Model.

Defines the MCPApp entity and related value objects for MCP Apps,
which are interactive HTML interfaces returned by MCP tools via
the _meta.ui.resourceUri extension.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class MCPAppSource(str, Enum):
    """Source of an MCP App."""

    USER_ADDED = "user_added"
    AGENT_DEVELOPED = "agent_developed"


class MCPAppStatus(str, Enum):
    """Lifecycle status of an MCP App."""

    DISCOVERED = "discovered"
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass(frozen=True)
class MCPAppUIMetadata:
    """UI metadata from _meta.ui in MCP tool description.

    Attributes:
        resource_uri: The ui:// URI pointing to the app's HTML resource.
        permissions: Requested iframe permissions per SEP-1865 spec format
            ({camera: {}, microphone: {}, geolocation: {}, clipboardWrite: {}}).
        csp: Content Security Policy directives for the app.
        title: Display title for the app.
        visibility: Who can access this tool - ["model", "app"] (default both).
        prefers_border: Whether a visible border is preferred by the app.
        domain: Dedicated sandbox origin for OAuth/CORS.
    """

    resource_uri: str
    permissions: Any = field(default_factory=dict)
    csp: Dict[str, List[str]] = field(default_factory=dict)
    title: Optional[str] = None
    visibility: List[str] = field(default_factory=lambda: ["model", "app"])
    prefers_border: Optional[bool] = None
    domain: Optional[str] = None
    display_mode: Optional[str] = None  # "inline" | "fullscreen" | "pip"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: Dict[str, Any] = {"resourceUri": self.resource_uri}
        if self.permissions:
            result["permissions"] = self.permissions
        if self.csp:
            result["csp"] = self.csp
        if self.title:
            result["title"] = self.title
        if self.visibility != ["model", "app"]:
            result["visibility"] = self.visibility
        if self.prefers_border is not None:
            result["prefersBorder"] = self.prefers_border
        if self.domain:
            result["domain"] = self.domain
        if self.display_mode:
            result["displayMode"] = self.display_mode
        return result

    @classmethod
    def _normalize_permissions(cls, raw: Any) -> Dict[str, Any]:  # noqa: ANN401
        """Normalize permissions to spec format {camera: {}, microphone: {}, ...}.

        Accepts both legacy array format ["camera", "microphone"] and
        spec object format {camera: {}, microphone: {}}.
        """
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, list):
            mapping = {
                "camera": "camera",
                "microphone": "microphone",
                "geolocation": "geolocation",
                "clipboard-write": "clipboardWrite",
                "clipboardWrite": "clipboardWrite",
            }
            return {mapping.get(p, p): {} for p in raw if p}
        return {}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPAppUIMetadata":
        """Create from dictionary (MCP protocol format)."""
        return cls(
            resource_uri=data.get("resourceUri", ""),
            permissions=cls._normalize_permissions(data.get("permissions", {})),
            csp=data.get("csp", {}),
            title=data.get("title"),
            visibility=data.get("visibility", ["model", "app"]),
            prefers_border=data.get("prefersBorder"),
            domain=data.get("domain"),
            display_mode=data.get("displayMode"),
        )


@dataclass(frozen=True)
class MCPAppResource:
    """Resolved HTML content for an MCP App.

    Attributes:
        uri: The ui:// URI that was resolved.
        html_content: The bundled HTML content.
        mime_type: MIME type of the resource.
        resolved_at: When the resource was last fetched.
        size_bytes: Size of the HTML content in bytes.
    """

    uri: str
    html_content: str
    mime_type: str = "text/html;profile=mcp-app"
    resolved_at: datetime = field(default_factory=datetime.utcnow)
    size_bytes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "uri": self.uri,
            "html_content": self.html_content,
            "mime_type": self.mime_type,
            "resolved_at": self.resolved_at.isoformat(),
            "size_bytes": self.size_bytes,
        }


@dataclass(kw_only=True)
class MCPApp:
    """MCP App entity.

    Represents an interactive HTML interface declared by an MCP tool
    via the _meta.ui.resourceUri extension. Apps are rendered in
    sandboxed iframes within the Canvas panel.

    Attributes:
        id: Unique identifier.
        project_id: Project this app belongs to.
        tenant_id: Tenant for multi-tenancy scoping.
        server_id: The MCPServer that provides this app.
        server_name: Human-readable server name.
        tool_name: The MCP tool that declares this app.
        ui_metadata: UI configuration from _meta.ui.
        resource: Cached HTML resource (None until resolved).
        source: How this app was created (user-added or agent-developed).
        status: Current lifecycle status.
        error_message: Error details if status is ERROR.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    tenant_id: str
    server_id: Optional[str] = None
    server_name: str
    tool_name: str
    ui_metadata: MCPAppUIMetadata
    resource: Optional[MCPAppResource] = None
    source: MCPAppSource = MCPAppSource.USER_ADDED
    status: MCPAppStatus = MCPAppStatus.DISCOVERED
    error_message: Optional[str] = None
    lifecycle_metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    def _record_lifecycle(self, status: MCPAppStatus, **metadata: Any) -> None:  # noqa: ANN401
        """Record lifecycle transition metadata for persistence/audit."""
        now = datetime.utcnow()
        self.lifecycle_metadata["last_status"] = status.value
        self.lifecycle_metadata["last_transition_at"] = now.isoformat()
        self.lifecycle_metadata.update(metadata)
        self.updated_at = now

    def mark_loading(self) -> None:
        """Transition to loading state."""
        self.status = MCPAppStatus.LOADING
        self._record_lifecycle(MCPAppStatus.LOADING)

    def mark_ready(self, resource: MCPAppResource) -> None:
        """Transition to ready state with resolved resource."""
        self.resource = resource
        self.status = MCPAppStatus.READY
        self.error_message = None
        self._record_lifecycle(
            MCPAppStatus.READY,
            resource_uri=resource.uri,
            resource_size_bytes=resource.size_bytes,
        )

    def mark_error(self, error: str) -> None:
        """Transition to error state."""
        self.status = MCPAppStatus.ERROR
        self.error_message = error
        self._record_lifecycle(MCPAppStatus.ERROR, last_error=error)

    def mark_disabled(self) -> None:
        """Disable the app."""
        self.status = MCPAppStatus.DISABLED
        self._record_lifecycle(MCPAppStatus.DISABLED)

    def mark_discovered(self) -> None:
        """Reset to discovered state, clearing any cached resource.

        Called when the sandbox is recreated and the resource is no longer
        accessible. The app can be re-resolved once the sandbox is ready.
        """
        self.resource = None
        self.status = MCPAppStatus.DISCOVERED
        self.error_message = None
        self._record_lifecycle(MCPAppStatus.DISCOVERED, resource_uri=self.ui_metadata.resource_uri)

    @property
    def is_ready(self) -> bool:
        """Check if the app is ready to render."""
        return self.status == MCPAppStatus.READY and self.resource is not None

    @property
    def resource_uri(self) -> str:
        """Get the ui:// resource URI."""
        return self.ui_metadata.resource_uri

    @property
    def display_title(self) -> str:
        """Get display title (from metadata or tool name)."""
        return self.ui_metadata.title or self.tool_name

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "server_id": self.server_id,
            "server_name": self.server_name,
            "tool_name": self.tool_name,
            "ui_metadata": self.ui_metadata.to_dict(),
            "resource": self.resource.to_dict() if self.resource else None,
            "source": self.source.value,
            "status": self.status.value,
            "error_message": self.error_message,
            "lifecycle_metadata": self.lifecycle_metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
