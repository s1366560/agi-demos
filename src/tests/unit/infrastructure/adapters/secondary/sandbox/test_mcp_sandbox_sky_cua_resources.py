"""Project-scoped sky-cua Chromium resource contract tests."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from docker.errors import NotFound

from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxResourceError
from src.infrastructure.adapters.secondary.sandbox.chromium_seccomp import (
    chromium_seccomp_security_opt,
)
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter


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


def _settings(*, shm_size: str = "1g") -> SimpleNamespace:
    return SimpleNamespace(
        sandbox_shm_size=shm_size,
        sandbox_pip_cache_enabled=False,
        sandbox_pip_cache_path="",
        sandbox_platform_url=None,
        sandbox_service_token=None,
    )


def test_chromium_volume_identity_is_deterministic_and_tenant_scoped(
    adapter: MCPSandboxAdapter,
) -> None:
    tenant_id = "tenant-alpha"
    project_id = "project-beta"
    digest = hashlib.sha256(f"{tenant_id}\0{project_id}".encode()).hexdigest()[:32]

    name = adapter._chromium_volume_name(tenant_id, project_id)
    labels = adapter._chromium_volume_labels(tenant_id, project_id)

    assert name == f"memstack-sky-cua-chromium-{digest}"
    assert labels == {
        "memstack.managed": "true",
        "memstack.resource.type": "sky-cua-chromium-profile",
        "memstack.tenant_id": tenant_id,
        "memstack.project_id": project_id,
    }


@pytest.mark.asyncio
async def test_create_mounts_managed_chromium_volume_and_applies_shm_size(
    adapter: MCPSandboxAdapter,
    docker_client: MagicMock,
) -> None:
    captured: dict[str, object] = {}
    tenant_id = "tenant-alpha"
    project_id = "project-beta"
    volume_name = adapter._chromium_volume_name(tenant_id, project_id)
    expected_labels = adapter._chromium_volume_labels(tenant_id, project_id)

    docker_client.volumes.get = Mock(side_effect=NotFound("missing"))
    created_volume = MagicMock()
    created_volume.attrs = {"Labels": expected_labels}
    docker_client.volumes.create = Mock(return_value=created_volume)
    docker_client.networks.create = Mock(return_value=MagicMock())

    def run_container(**kwargs: object) -> MagicMock:
        captured.update(kwargs)
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
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.get_settings",
            return_value=_settings(shm_size="1g"),
        ),
        patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.asyncio.sleep",
            new=AsyncMock(),
        ),
    ):
        await adapter.create_sandbox(
            project_path="/tmp/workspace",
            tenant_id=tenant_id,
            project_id=project_id,
        )

    docker_client.volumes.create.assert_called_once_with(
        name=volume_name,
        labels=expected_labels,
    )
    assert captured["shm_size"] == "1g"
    assert captured["security_opt"] == chromium_seccomp_security_opt()
    volumes = captured["volumes"]
    assert isinstance(volumes, dict)
    assert volumes[volume_name] == {
        "bind": "/home/sandbox/.config/chromium",
        "mode": "rw",
    }


def test_rebuild_recomputes_managed_mount_and_shm_size(adapter: MCPSandboxAdapter) -> None:
    tenant_id = "tenant-alpha"
    project_id = "project-beta"
    volume_name = adapter._chromium_volume_name(tenant_id, project_id)

    with patch(
        "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.get_settings",
        return_value=_settings(shm_size="2g"),
    ):
        container_config = adapter._build_rebuild_container_config(
            sandbox_id="sandbox-1",
            config=SandboxConfig(image="sandbox-mcp-server:latest"),
            old_ports=[18765, 16080, 17681],
            project_path="/tmp/workspace",
            labels={
                "memstack.sandbox": "true",
                "memstack.tenant_id": tenant_id,
                "memstack.project_id": project_id,
            },
        )

    assert container_config["shm_size"] == "2g"
    assert container_config["security_opt"] == chromium_seccomp_security_opt()
    assert container_config["volumes"][volume_name] == {
        "bind": "/home/sandbox/.config/chromium",
        "mode": "rw",
    }


def test_recovery_ignores_adapter_owned_chromium_mount(adapter: MCPSandboxAdapter) -> None:
    container = MagicMock()
    container.attrs = {
        "Config": {"Image": "sandbox-mcp-server:latest", "Env": []},
        "Mounts": [
            {
                "Source": "/tmp/caller-state",
                "Destination": "/opt/caller-state",
                "RW": True,
            },
            {
                "Name": "memstack-sky-cua-chromium-owned",
                "Source": "/var/lib/docker/volumes/owned/_data",
                "Destination": "/home/sandbox/.config/chromium",
                "RW": True,
            },
        ],
    }

    config = adapter._extract_config_from_mounts(container)

    assert config.rw_volumes == {"/tmp/caller-state": "/opt/caller-state"}


@pytest.mark.asyncio
async def test_existing_volume_with_mismatched_labels_is_rejected(
    adapter: MCPSandboxAdapter,
    docker_client: MagicMock,
) -> None:
    volume = MagicMock()
    volume.attrs = {
        "Labels": {
            "memstack.managed": "true",
            "memstack.resource.type": "sky-cua-chromium-profile",
            "memstack.tenant_id": "attacker-tenant",
            "memstack.project_id": "project-beta",
        }
    }
    docker_client.volumes.get = Mock(return_value=volume)

    with pytest.raises(SandboxResourceError):
        await adapter._ensure_chromium_volume("tenant-alpha", "project-beta")

    docker_client.volumes.create.assert_not_called()


@pytest.mark.asyncio
async def test_project_resource_purge_stops_containers_then_removes_verified_volume(
    adapter: MCPSandboxAdapter,
    docker_client: MagicMock,
) -> None:
    tenant_id = "tenant-alpha"
    project_id = "project-beta"
    volume_name = adapter._chromium_volume_name(tenant_id, project_id)
    container = MagicMock()
    container.id = "container-1"
    container.name = "sandbox-1"
    volume = MagicMock()
    volume.attrs = {"Labels": adapter._chromium_volume_labels(tenant_id, project_id)}
    docker_client.containers.list = Mock(side_effect=[[container], []])
    docker_client.containers.get = Mock(return_value=container)
    docker_client.volumes.get = Mock(return_value=volume)

    with (
        patch.object(adapter, "_pre_destroy_hook", new=AsyncMock()),
        patch.object(adapter, "_safe_stop_and_remove_container", new=AsyncMock(return_value=True)),
        patch.object(adapter, "_cleanup_instance_tracking", new=AsyncMock()),
    ):
        await adapter.purge_project_resources(tenant_id, project_id)

    docker_client.volumes.get.assert_called_once_with(volume_name)
    volume.remove.assert_called_once_with()


@pytest.mark.asyncio
async def test_project_resource_purge_never_deletes_forged_volume(
    adapter: MCPSandboxAdapter,
    docker_client: MagicMock,
) -> None:
    docker_client.containers.list = Mock(return_value=[])
    volume = MagicMock()
    volume.attrs = {
        "Labels": {
            "memstack.managed": "true",
            "memstack.resource.type": "sky-cua-chromium-profile",
            "memstack.tenant_id": "wrong-tenant",
            "memstack.project_id": "project-beta",
        }
    }
    docker_client.volumes.get = Mock(return_value=volume)

    with pytest.raises(SandboxResourceError):
        await adapter.purge_project_resources("tenant-alpha", "project-beta")

    volume.remove.assert_not_called()
