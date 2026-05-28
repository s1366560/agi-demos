"""Unit tests for the local Drone pipeline plugin."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from src.infrastructure.agent.plugins.discovery import discover_plugins
from src.infrastructure.agent.plugins.loader import AgentPluginLoader
from src.infrastructure.agent.plugins.registry import AgentPluginRegistry, PluginToolBuildContext
from src.infrastructure.agent.plugins.state_store import PluginStateStore
from src.infrastructure.agent.workspace_plan.pipeline import DRONE_PROVIDER
from src.infrastructure.agent.workspace_plan.pipeline_provider_registry import (
    PipelineProviderUnavailableError,
)

pytestmark = pytest.mark.unit


def _tool_context() -> SimpleNamespace:
    return SimpleNamespace(
        conversation_id="conversation-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
    )


def test_discover_plugins_loads_local_drone_manifest() -> None:
    discovered, diagnostics = discover_plugins(
        state_store=PluginStateStore(),
        include_builtins=False,
        include_entrypoints=False,
    )

    by_name = {plugin.name: plugin for plugin in discovered}
    plugin = by_name["drone-pipeline-plugin"]
    assert plugin.source == "local"
    assert plugin.kind == "pipeline_provider"
    assert plugin.providers == (DRONE_PROVIDER,)
    assert all(diagnostic.plugin_name != "drone" for diagnostic in diagnostics)


async def test_drone_plugin_registers_pipeline_provider_and_tool() -> None:
    discovered, _diagnostics = discover_plugins(
        state_store=PluginStateStore(),
        include_builtins=False,
        include_entrypoints=False,
    )
    drone_discovery = next(
        plugin for plugin in discovered if plugin.name == "drone-pipeline-plugin"
    )
    drone_plugin = drone_discovery.plugin
    registry = AgentPluginRegistry()

    diagnostics = await AgentPluginLoader(registry=registry).load_plugins([drone_plugin])
    provider = registry.get_provider("pipeline:drone")
    infrastructure = registry.get_service("drone:infrastructure")
    tools, tool_diagnostics = await registry.build_tools(
        PluginToolBuildContext(
            tenant_id="tenant-1",
            project_id="project-1",
            base_tools={},
        )
    )

    assert diagnostics == []
    assert provider is not None
    assert provider.__name__ == "DronePipelineProvider"
    assert infrastructure == {
        "compose_tool": "docker_compose",
        "compose_files": ["docker-compose.yml"],
        "client_workdir": str(Path(drone_discovery.manifest_path).parent),
        "project_name": "memstack-drone",
        "profiles": ["drone"],
        "services": ["drone-server", "drone-runner-docker"],
        "check_args": ["ps", "--format", "json"],
        "start_args": ["up", "-d", "drone-server", "drone-runner-docker"],
        "stop_args": ["stop", "drone-runner-docker", "drone-server"],
        "logs_args": ["logs", "--tail", "100", "drone-server", "drone-runner-docker"],
    }
    assert "cicd_run_pipeline" in tools
    assert tools["cicd_run_pipeline"]._plugin_origin == "drone-pipeline-plugin"
    tool_schema = tools["cicd_run_pipeline"].parameters
    assert "repository" in tool_schema["properties"]
    assert "repo" in tool_schema["properties"]
    assert "workspace_id" not in tool_schema["properties"]
    assert any(diagnostic.plugin_name == "drone-pipeline-plugin" for diagnostic in tool_diagnostics)


async def test_drone_infrastructure_uses_docker_compose_plugin_contract() -> None:
    discovered, _diagnostics = discover_plugins(
        state_store=PluginStateStore(),
        include_builtins=False,
        include_entrypoints=False,
    )
    selected = [
        plugin.plugin
        for plugin in discovered
        if plugin.name in {"drone-pipeline-plugin", "docker-compose-plugin"}
    ]
    registry = AgentPluginRegistry()

    diagnostics = await AgentPluginLoader(registry=registry).load_plugins(selected)
    tools, tool_diagnostics = await registry.build_tools(
        PluginToolBuildContext(
            tenant_id="tenant-1",
            project_id="project-1",
            base_tools={},
        )
    )
    infrastructure = registry.get_service("drone:infrastructure")
    result = await tools[infrastructure["compose_tool"]].execute(
        _tool_context(),
        compose_args=infrastructure["check_args"],
        client_workdir=infrastructure["client_workdir"],
        workdir=infrastructure["client_workdir"],
        compose_files=infrastructure["compose_files"],
        project_name=infrastructure["project_name"],
        profiles=infrastructure["profiles"],
        dry_run=True,
    )
    payload = json.loads(result.output)

    assert diagnostics == []
    assert not any(item.level == "error" for item in tool_diagnostics)
    assert result.is_error is False
    assert payload["command"] == [
        "docker",
        "compose",
        "-f",
        str(Path(infrastructure["client_workdir"]) / "docker-compose.yml"),
        "-p",
        "memstack-drone",
        "--profile",
        "drone",
        "ps",
        "--format",
        "json",
    ]


async def test_drone_plugin_config_schema_matches_workspace_drone_form() -> None:
    discovered, _diagnostics = discover_plugins(
        state_store=PluginStateStore(),
        include_builtins=False,
        include_entrypoints=False,
    )
    drone_plugin = next(
        plugin.plugin for plugin in discovered if plugin.name == "drone-pipeline-plugin"
    )
    registry = AgentPluginRegistry()

    diagnostics = await AgentPluginLoader(registry=registry).load_plugins([drone_plugin])
    config_schema = registry.list_config_schemas()["drone-pipeline-plugin"]
    schema = config_schema.schema
    properties = schema["properties"]

    assert diagnostics == []
    assert schema["additionalProperties"] is False
    assert "required" not in schema
    assert "repository" not in properties
    assert "source_control" not in properties
    assert "environment" not in properties
    assert "deploy" not in properties
    assert all(field_schema.get("type") != "object" for field_schema in properties.values())
    assert list(properties) == [
        "drone_server_env",
        "drone_token_env",
        "poll_interval_seconds",
    ]
    assert config_schema.defaults == {
        "drone_server_env": "DRONE_SERVER",
        "drone_token_env": "DRONE_TOKEN",
        "poll_interval_seconds": 5,
    }
    assert config_schema.config_ui_hints["drone_server_env"] == {
        "label": "Drone Server Env",
        "placeholder": "DRONE_SERVER",
        "help": "Environment variable that stores the Drone server URL used by drone CLI.",
    }
    assert config_schema.secret_paths == []


async def test_loader_does_not_validate_schema_without_plugin_config() -> None:
    """Manifest/config schemas should not require instance config during plugin load."""

    class _Plugin:
        name = "schema-only-plugin"

        @staticmethod
        def setup(api) -> None:
            api.register_config_schema(
                {
                    "type": "object",
                    "required": ["api_key"],
                    "properties": {"api_key": {"type": "string"}},
                }
            )

    registry = AgentPluginRegistry()

    diagnostics = await AgentPluginLoader(registry=registry).load_plugins([_Plugin()])

    assert diagnostics == []


async def test_loader_validates_explicit_plugin_config() -> None:
    """Explicit plugin config should still be validated against registered schema."""

    class _Plugin:
        name = "configured-plugin"
        config: ClassVar[dict[str, object]] = {}

        @staticmethod
        def setup(api) -> None:
            api.register_config_schema(
                {
                    "type": "object",
                    "required": ["api_key"],
                    "properties": {"api_key": {"type": "string"}},
                }
            )

    registry = AgentPluginRegistry()

    diagnostics = await AgentPluginLoader(registry=registry).load_plugins([_Plugin()])

    assert [diagnostic.code for diagnostic in diagnostics] == ["config_validation_failed"]


async def test_pipeline_provider_unavailable_error_uses_stable_message() -> None:
    exc = PipelineProviderUnavailableError("drone")

    assert str(exc) == "pipeline provider plugin is not enabled: drone"
    assert exc.provider == "drone"
