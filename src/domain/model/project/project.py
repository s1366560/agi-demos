from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.domain.shared_kernel import Entity


class SandboxType(Enum):
    """Type of sandbox for project operations."""

    CLOUD = "cloud"  # Server-managed Docker container (default)
    LOCAL = "local"  # User's local machine via WebSocket tunnel


@dataclass(frozen=True, kw_only=True)
class LocalSandboxConfig:
    """Configuration for local sandbox connection.

    Attributes:
        workspace_path: Path to workspace on user's machine
        tunnel_url: WebSocket tunnel URL (e.g., wss://xxx.ngrok.io)
        host: Local host address (default: localhost)
        port: Local port number (default: 8765)
    """

    workspace_path: str = "/workspace"
    tunnel_url: str | None = None
    host: str = "localhost"
    port: int = 8765

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_path": self.workspace_path,
            "tunnel_url": self.tunnel_url,
            "host": self.host,
            "port": self.port,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LocalSandboxConfig":
        return cls(
            workspace_path=data.get("workspace_path", "/workspace"),
            tunnel_url=data.get("tunnel_url"),
            host=data.get("host", "localhost"),
            port=data.get("port", 8765),
        )


@dataclass(frozen=True, kw_only=True)
class SandboxConfig:
    """Sandbox configuration for a project.

    Attributes:
        sandbox_type: Type of sandbox (cloud or local)
        local_config: Configuration for local sandbox (if type is local)
    """

    sandbox_type: SandboxType = SandboxType.CLOUD
    local_config: LocalSandboxConfig | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sandbox_type": self.sandbox_type.value,
            "local_config": self.local_config.to_dict() if self.local_config else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SandboxConfig":
        sandbox_type = data.get("sandbox_type", "cloud")
        if isinstance(sandbox_type, str):
            sandbox_type = SandboxType(sandbox_type)

        local_config = None
        if data.get("local_config"):
            local_config = LocalSandboxConfig.from_dict(data["local_config"])

        return cls(sandbox_type=sandbox_type, local_config=local_config)


@dataclass(kw_only=True)
class Project(Entity):
    """Project domain entity for organizing memories"""

    tenant_id: str
    name: str
    owner_id: str
    description: str | None = None
    member_ids: list[str] = field(default_factory=list)
    memory_rules: dict[str, Any] = field(default_factory=dict)
    graph_config: dict[str, Any] = field(default_factory=dict)
    sandbox_config: SandboxConfig = field(default_factory=SandboxConfig)
    is_public: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    def is_local_sandbox(self) -> bool:
        """Check if project uses local sandbox."""
        return self.sandbox_config.sandbox_type == SandboxType.LOCAL

    def get_sandbox_tunnel_url(self) -> str | None:
        """Get tunnel URL for local sandbox."""
        if self.sandbox_config.local_config:
            return self.sandbox_config.local_config.tunnel_url
        return None
