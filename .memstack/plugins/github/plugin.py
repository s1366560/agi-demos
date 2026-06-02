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
    module_name = f"github_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load sibling module: {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GITHUB_PLUGIN_CONFIG_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "api_base_url": {"type": "string", "default": "https://api.github.com"},
        "token_env": {"type": "string", "default": "GITHUB_TOKEN"},
        "default_owner": {"type": "string"},
        "default_repo": {"type": "string"},
        "timeout_seconds": {"type": "integer", "minimum": 1, "default": 30},
        "output_limit_chars": {"type": "integer", "minimum": 1, "default": 40000},
    },
}

GITHUB_PLUGIN_CONFIG_UI_HINTS = {
    "api_base_url": {
        "label": "GitHub API Base URL",
        "placeholder": "https://api.github.com",
    },
    "token_env": {
        "label": "Token Env",
        "placeholder": "GITHUB_TOKEN",
        "help": "Environment variable containing a GitHub token.",
        "sensitive": True,
    },
    "default_owner": {"label": "Default Owner"},
    "default_repo": {"label": "Default Repository"},
    "timeout_seconds": {"label": "Timeout Seconds"},
    "output_limit_chars": {"label": "Output Limit Characters"},
}

GITHUB_PLUGIN_DEFAULTS = {
    "api_base_url": "https://api.github.com",
    "token_env": "GITHUB_TOKEN",
    "timeout_seconds": 30,
    "output_limit_chars": 40000,
}

GITHUB_PLUGIN_SECRET_PATHS = ["token_env"]

_CONFIG_TO_TOOL_KWARGS = {
    "api_base_url": "api_base_url",
    "token_env": "token_env",
    "default_owner": "owner",
    "default_repo": "repo",
    "timeout_seconds": "timeout_seconds",
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
            "github-plugin",
        )
        if config is None or not isinstance(config.config, dict):
            return {}
        return dict(config.config)


def _configured_tool(github_tool: ToolInfo, config: dict[str, Any]) -> ToolInfo:
    from src.infrastructure.agent.tools.define import ToolInfo

    merged_config = dict(GITHUB_PLUGIN_DEFAULTS)
    merged_config.update(config)
    defaults = {
        tool_key: value
        for config_key, tool_key in _CONFIG_TO_TOOL_KWARGS.items()
        if (value := merged_config.get(config_key)) not in (None, "", [])
    }

    async def execute(ctx: ToolContext, **kwargs: object) -> object:
        merged = dict(defaults)
        merged.update({key: value for key, value in kwargs.items() if value is not None})
        return await github_tool.execute(ctx, **merged)

    wrapped = ToolInfo(
        name=github_tool.name,
        description=github_tool.description,
        parameters=github_tool.parameters,
        execute=execute,
        permission=github_tool.permission,
        category=github_tool.category,
        model_filter=github_tool.model_filter,
        tags=github_tool.tags,
        execution_context=github_tool.execution_context,
        dependencies=github_tool.dependencies,
        aliases=github_tool.aliases,
        sandbox_id=github_tool.sandbox_id,
        _sandbox_id=github_tool._sandbox_id,
    )
    wrapped._plugin_origin = "github-plugin"
    return wrapped


class GitHubPlugin:
    name = "github-plugin"

    def setup(self, api: PluginRuntimeApi) -> None:
        tools_module = _load_sibling("tools.py")
        github_tool = tools_module.github_tool
        github_tool._plugin_origin = self.name

        async def build_tools(context: PluginToolBuildContext) -> dict[str, ToolInfo]:
            config = await _load_tenant_config(context)
            return {tools_module.GITHUB_TOOL_NAME: _configured_tool(github_tool, config)}

        api.register_tool_factory(build_tools)
        api.register_config_schema(
            GITHUB_PLUGIN_CONFIG_SCHEMA,
            config_ui_hints=GITHUB_PLUGIN_CONFIG_UI_HINTS,
            defaults=GITHUB_PLUGIN_DEFAULTS,
            secret_paths=GITHUB_PLUGIN_SECRET_PATHS,
        )
        api.register_service("github:defaults", GITHUB_PLUGIN_DEFAULTS)
        api.register_service("github:secret_paths", GITHUB_PLUGIN_SECRET_PATHS)


plugin = GitHubPlugin()
