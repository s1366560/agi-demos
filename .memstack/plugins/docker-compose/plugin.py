from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType

    from src.infrastructure.agent.plugins.registry import PluginToolBuildContext
    from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi
    from src.infrastructure.agent.tools.context import ToolContext
    from src.infrastructure.agent.tools.define import ToolInfo

_PLUGIN_DIR = Path(__file__).resolve().parent


def _load_sibling(module_file: str) -> ModuleType:
    file_path = _PLUGIN_DIR / module_file
    module_name = f"docker_compose_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load sibling module: {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DOCKER_COMPOSE_CONFIG_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "docker_bin": {"type": "string", "default": "docker"},
        "docker_host": {"type": "string"},
        "docker_context": {"type": "string"},
        "client_workdir": {"type": "string"},
        "daemon_workdir": {"type": "string"},
        "allow_host_socket_from_sandbox": {"type": "boolean", "default": False},
        "default_timeout_seconds": {"type": "integer", "minimum": 1, "default": 600},
        "output_limit_chars": {"type": "integer", "minimum": 1, "default": 40000},
        "allowed_project_roots": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
        },
        "allowed_client_roots": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
        },
        "path_mappings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "container_path": {"type": "string"},
                    "daemon_path": {"type": "string"},
                },
                "required": ["container_path", "daemon_path"],
            },
            "default": [],
        },
    },
}

DOCKER_COMPOSE_UI_HINTS = {
    "docker_bin": {"label": "Docker CLI"},
    "docker_host": {
        "label": "Docker Host",
        "placeholder": "tcp://docker:2375",
        "help": "Use tcp:// or ssh:// for a Docker daemon on another machine.",
    },
    "docker_context": {"label": "Docker Context"},
    "client_workdir": {
        "label": "Client Workdir",
        "help": "Path readable by the API/plugin process for compose files.",
    },
    "daemon_workdir": {
        "label": "Docker Daemon Workdir",
        "help": "Equivalent project path on the machine running the Docker daemon.",
    },
    "allow_host_socket_from_sandbox": {
        "label": "Allow Host Socket From Sandbox",
        "help": "Disabled by default to avoid host-daemon DNS and path mismatches.",
    },
    "default_timeout_seconds": {"label": "Default Timeout Seconds"},
    "output_limit_chars": {"label": "Output Limit Characters"},
    "allowed_project_roots": {"label": "Allowed Project Roots"},
    "allowed_client_roots": {"label": "Allowed Client Roots"},
    "path_mappings": {"label": "Path Mappings"},
}

DOCKER_COMPOSE_DEFAULTS = {
    "docker_bin": "docker",
    "allow_host_socket_from_sandbox": False,
    "default_timeout_seconds": 600,
    "output_limit_chars": 40000,
    "allowed_project_roots": [],
    "allowed_client_roots": [],
    "path_mappings": [],
}

_CONFIG_TO_TOOL_KWARGS = {
    "docker_bin": "docker_bin",
    "docker_host": "docker_host",
    "docker_context": "docker_context",
    "client_workdir": "client_workdir",
    "daemon_workdir": "daemon_workdir",
    "allow_host_socket_from_sandbox": "allow_host_socket_from_sandbox",
    "default_timeout_seconds": "timeout_seconds",
    "allowed_project_roots": "allowed_project_roots",
    "allowed_client_roots": "allowed_client_roots",
    "path_mappings": "path_mappings",
    "output_limit_chars": "output_limit_chars",
}


async def _load_tenant_config(context: PluginToolBuildContext) -> dict[str, Any]:
    session_factory = getattr(context, "session_factory", None)
    if session_factory is None:
        return {}

    from src.infrastructure.adapters.secondary.persistence.plugin_config_repository import (
        PluginConfigRepository,
    )

    async with session_factory() as session:
        config = await PluginConfigRepository(session).get_by_tenant_and_plugin(
            context.tenant_id,
            "docker-compose-plugin",
        )
        if config is None or not isinstance(config.config, dict):
            return {}
        return dict(config.config)


def _configured_tool(compose_tool: ToolInfo, config: dict[str, Any]) -> ToolInfo:
    from src.infrastructure.agent.tools.define import ToolInfo

    defaults = {
        tool_key: value
        for config_key, tool_key in _CONFIG_TO_TOOL_KWARGS.items()
        if (value := config.get(config_key)) not in (None, "", [])
    }

    async def execute(ctx: ToolContext, **kwargs: object) -> object:
        merged = dict(defaults)
        merged.update({key: value for key, value in kwargs.items() if value is not None})
        return await compose_tool.execute(ctx, **merged)

    wrapped = ToolInfo(
        name=compose_tool.name,
        description=compose_tool.description,
        parameters=compose_tool.parameters,
        execute=execute,
        permission=compose_tool.permission,
        category=compose_tool.category,
        model_filter=compose_tool.model_filter,
        tags=compose_tool.tags,
        execution_context=compose_tool.execution_context,
        dependencies=compose_tool.dependencies,
        aliases=compose_tool.aliases,
        sandbox_id=compose_tool.sandbox_id,
        _sandbox_id=compose_tool._sandbox_id,
    )
    wrapped._plugin_origin = "docker-compose-plugin"
    return wrapped


class DockerComposePlugin:
    name = "docker-compose-plugin"

    def setup(self, api: PluginRuntimeApi) -> None:
        tools_module = _load_sibling("tools.py")
        compose_tool = tools_module.docker_compose_tool
        compose_tool._plugin_origin = self.name

        async def build_tools(context: PluginToolBuildContext) -> dict[str, ToolInfo]:
            config = await _load_tenant_config(context)
            return {tools_module.DOCKER_COMPOSE_TOOL_NAME: _configured_tool(compose_tool, config)}

        api.register_tool_factory(build_tools)
        api.register_config_schema(
            DOCKER_COMPOSE_CONFIG_SCHEMA,
            config_ui_hints=DOCKER_COMPOSE_UI_HINTS,
            defaults=DOCKER_COMPOSE_DEFAULTS,
            secret_paths=[],
        )
        api.register_service("docker_compose:defaults", DOCKER_COMPOSE_DEFAULTS)


plugin = DockerComposePlugin()
