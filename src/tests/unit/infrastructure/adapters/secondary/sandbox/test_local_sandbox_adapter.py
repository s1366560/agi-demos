"""Unit tests for LocalSandboxAdapter lifecycle compatibility."""

from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest

from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxStatus
from src.infrastructure.adapters.secondary.sandbox import local_sandbox_adapter as adapter_mod
from src.infrastructure.adapters.secondary.sandbox.local_sandbox_adapter import LocalSandboxAdapter


class _FakeMCPClient:
    instances: ClassVar[list["_FakeMCPClient"]] = []

    def __init__(self, url: str) -> None:
        self.url = url
        self.connected = False
        self.disconnected = False
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.__class__.instances.append(self)

    async def connect(self) -> None:
        self.connected = True

    async def initialize(self) -> None:
        return None

    async def disconnect(self) -> None:
        self.disconnected = True

    async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((tool_name, arguments))
        return {"isError": False, "content": [{"type": "text", "text": "ok"}]}


@pytest.fixture(autouse=True)
def fake_mcp_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeMCPClient.instances.clear()
    monkeypatch.setattr(adapter_mod, "WebSocketMCPClient", _FakeMCPClient)


@pytest.mark.unit
async def test_create_sandbox_connects_to_configured_local_tunnel() -> None:
    adapter = LocalSandboxAdapter(connection_timeout=1)
    config = SandboxConfig(
        image="local-sandbox",
        environment={
            "LOCAL_SANDBOX_TUNNEL_URL": "ws://local.example/mcp",
            "LOCAL_SANDBOX_AUTH_TOKEN": "sandbox-token",
            "LOCAL_SANDBOX_WORKSPACE_PATH": "/Users/me/project",
        },
    )

    instance = await adapter.create_sandbox(
        project_path="/tmp/ignored",
        config=config,
        project_id="project-1",
        tenant_id="tenant-1",
        sandbox_id="local-fixed",
    )

    assert instance.id == "local-fixed"
    assert instance.status == SandboxStatus.RUNNING
    assert instance.endpoint == "ws://local.example/mcp?token=sandbox-token"
    assert instance.project_path == "/Users/me/project"
    assert await adapter.container_exists("local-fixed") is True
    assert _FakeMCPClient.instances[0].url == "ws://local.example/mcp?token=sandbox-token"


@pytest.mark.unit
async def test_call_tool_delegates_to_local_mcp_client() -> None:
    adapter = LocalSandboxAdapter(connection_timeout=1)
    instance = await adapter.create_sandbox(
        project_path="/workspace",
        config=SandboxConfig(image="local-sandbox"),
        project_id="project-1",
        tenant_id="tenant-1",
    )

    result = await adapter.call_tool(instance.id, "read", {"file_path": "README.md"})

    assert result == {"isError": False, "content": [{"type": "text", "text": "ok"}]}
    assert _FakeMCPClient.instances[0].calls == [("read", {"file_path": "README.md"})]


@pytest.mark.unit
async def test_cleanup_expired_removes_only_non_running_connections() -> None:
    adapter = LocalSandboxAdapter(connection_timeout=1)
    running = await adapter.create_sandbox(
        project_path="/workspace",
        config=SandboxConfig(image="local-sandbox"),
        project_id="project-running",
        tenant_id="tenant-1",
    )
    stopped = await adapter.create_sandbox(
        project_path="/workspace",
        config=SandboxConfig(image="local-sandbox"),
        project_id="project-stopped",
        tenant_id="tenant-1",
    )
    stopped_conn = adapter.get_connection(stopped.id)
    assert stopped_conn is not None
    stopped_conn.status = SandboxStatus.STOPPED
    stopped_conn.created_at = datetime.now(UTC) - timedelta(hours=2)

    cleaned = await adapter.cleanup_expired(max_age_seconds=3600)

    assert cleaned == 1
    assert await adapter.container_exists(running.id) is True
    assert adapter.get_connection(stopped.id) is None


@pytest.mark.unit
async def test_cleanup_project_containers_disconnects_project_connections() -> None:
    adapter = LocalSandboxAdapter(connection_timeout=1)
    instance = await adapter.create_sandbox(
        project_path="/workspace",
        config=SandboxConfig(image="local-sandbox"),
        project_id="project-1",
        tenant_id="tenant-1",
    )

    cleaned = await adapter.cleanup_project_containers("project-1")

    assert cleaned == 1
    assert await adapter.container_exists(instance.id) is False
