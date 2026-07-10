"""Security regression tests for MCP sandbox capability authentication."""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxStatus
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
    MCPSandboxAdapter,
    MCPSandboxInstance,
)


@pytest.fixture
def docker_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def adapter(docker_client: MagicMock) -> MCPSandboxAdapter:
    with patch(
        "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env",
        return_value=docker_client,
    ):
        return MCPSandboxAdapter()


async def test_create_sandbox_generates_private_capability_and_loopback_ports(
    adapter: MCPSandboxAdapter,
    docker_client: MagicMock,
) -> None:
    captured_config: dict[str, object] = {}

    def run_container(**kwargs: object) -> MagicMock:
        captured_config.update(kwargs)
        container = MagicMock()
        container.name = kwargs["name"]
        container.status = "running"
        container.labels = kwargs["labels"]
        container.ports = {}
        return container

    docker_client.containers.run = Mock(side_effect=run_container)

    with (
        patch.object(adapter, "_is_port_available", return_value=True),
        patch.object(adapter, "_persist_sandbox_state", new=AsyncMock()),
        patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.asyncio.sleep",
            new=AsyncMock(),
        ),
    ):
        instance = await adapter.create_sandbox(project_path="/tmp/project")

    environment = captured_config["environment"]
    assert isinstance(environment, dict)
    token = environment["MCP_STATIC_TOKEN"]
    assert isinstance(token, str)
    assert len(token) >= 32
    assert environment["MCP_AUTH_ENABLED"] == "true"
    assert environment["MCP_ALLOW_LOCALHOST"] == "false"
    assert instance.mcp_auth_token == token
    assert token not in repr(instance)
    assert token not in str(captured_config["labels"])

    ports = captured_config["ports"]
    assert isinstance(ports, dict)
    assert all(binding[0] == "127.0.0.1" for binding in ports.values())


def test_rebuild_config_preserves_capability_and_loopback_ports(
    adapter: MCPSandboxAdapter,
) -> None:
    token = "rebuild-capability"

    container_config = adapter._build_rebuild_container_config(
        sandbox_id="sandbox-1",
        config=SandboxConfig(image="sandbox-mcp-server:latest"),
        old_ports=[18765, 16080, 17681],
        project_path="/tmp/project",
        labels={"memstack.sandbox": "true"},
        auth_token=token,
    )

    environment = container_config["environment"]
    assert environment["MCP_AUTH_ENABLED"] == "true"
    assert environment["MCP_ALLOW_LOCALHOST"] == "false"
    assert environment["MCP_STATIC_TOKEN"] == token
    assert container_config["ports"] == {
        "8765/tcp": ("127.0.0.1", 18765),
        "6080/tcp": ("127.0.0.1", 16080),
        "7681/tcp": ("127.0.0.1", 17681),
    }


async def test_connect_mcp_sends_capability_in_authorization_header(
    adapter: MCPSandboxAdapter,
) -> None:
    instance = MCPSandboxInstance(
        id="sandbox-1",
        status=SandboxStatus.RUNNING,
        config=SandboxConfig(image="sandbox-mcp-server:latest"),
        project_path="/tmp/project",
        endpoint="ws://localhost:18765",
        websocket_url="ws://localhost:18765",
        mcp_port=18765,
        mcp_auth_token="sandbox-capability",
    )
    adapter._active_sandboxes[instance.id] = instance
    client = MagicMock()
    client.is_connected = False
    client.connect = AsyncMock(return_value=True)

    with (
        patch.object(adapter, "_verify_container_running", new=AsyncMock(return_value=True)),
        patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.MCPWebSocketClient",
            return_value=client,
        ) as client_type,
    ):
        connected = await adapter.connect_mcp(instance.id)

    assert connected is True
    client_type.assert_called_once_with(
        url="ws://localhost:18765",
        headers={"Authorization": "Bearer sandbox-capability"},
        timeout=30.0,
        heartbeat_interval=None,
    )


async def test_connect_mcp_rejects_recovered_container_without_capability(
    adapter: MCPSandboxAdapter,
) -> None:
    instance = MCPSandboxInstance(
        id="legacy-sandbox",
        status=SandboxStatus.RUNNING,
        config=SandboxConfig(image="sandbox-mcp-server:latest"),
        project_path="/tmp/project",
        endpoint="ws://localhost:18765",
        websocket_url="ws://localhost:18765",
        mcp_port=18765,
    )
    adapter._active_sandboxes[instance.id] = instance

    with (
        patch.object(adapter, "_verify_container_running", new=AsyncMock()) as verify,
        patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.MCPWebSocketClient"
        ) as client_type,
    ):
        connected = await adapter.connect_mcp(instance.id)

    assert connected is False
    verify.assert_not_awaited()
    client_type.assert_not_called()


async def test_recovery_reads_capability_from_container_environment(
    adapter: MCPSandboxAdapter,
    docker_client: MagicMock,
) -> None:
    container = MagicMock()
    container.status = "running"
    container.labels = {
        "memstack.sandbox": "true",
        "memstack.sandbox.id": "sandbox-1",
        "memstack.sandbox.mcp_port": "18765",
    }
    container.attrs = {
        "Config": {"Env": ["MCP_STATIC_TOKEN=recovered-capability"]},
        "Mounts": [
            {
                "Destination": "/workspace",
                "Source": "/tmp/project",
                "RW": True,
            }
        ],
    }
    docker_client.containers.get = Mock(return_value=container)

    instance = await adapter._recover_sandbox_from_docker("sandbox-1")

    assert instance is not None
    assert instance.mcp_auth_token == "recovered-capability"
