from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

_PLUGIN_DIR = Path(__file__).resolve().parent


def _load_sibling(module_file: str) -> ModuleType:
    file_path = _PLUGIN_DIR / module_file
    module_name = f"drone_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load sibling module: {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DRONE_PLUGIN_CONFIG_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "drone_server_env": {
            "type": "string",
            "title": "Drone Server Environment Variable",
            "default": "DRONE_SERVER",
        },
        "drone_token_env": {
            "type": "string",
            "title": "Drone Token Environment Variable",
            "default": "DRONE_TOKEN",
        },
        "poll_interval_seconds": {
            "type": "integer",
            "title": "Poll Interval Seconds",
            "minimum": 1,
            "default": 5,
        },
    },
    "additionalProperties": False,
}

DRONE_PLUGIN_CONFIG_UI_HINTS = {
    "drone_server_env": {
        "label": "Drone Server Env",
        "placeholder": "DRONE_SERVER",
        "help": "Environment variable that stores the Drone server URL used by drone CLI.",
    },
    "drone_token_env": {
        "label": "Drone Token Env",
        "placeholder": "DRONE_TOKEN",
        "help": "Environment variable that stores the Drone personal access token.",
    },
    "poll_interval_seconds": {"label": "Poll Interval Seconds"},
}

DRONE_PLUGIN_CONFIG_DEFAULTS = {
    "drone_server_env": "DRONE_SERVER",
    "drone_token_env": "DRONE_TOKEN",
    "poll_interval_seconds": 5,
}

DRONE_PLUGIN_CONFIG_SECRET_PATHS: list[str] = []

DRONE_PLUGIN_DEFAULTS = {
    "drone_server_env": "DRONE_SERVER",
    "drone_token_env": "DRONE_TOKEN",
    "poll_interval_seconds": 5,
}

DRONE_PLUGIN_SECRET_PATHS: list[str] = []


class DronePipelinePlugin:
    name = "drone-pipeline-plugin"

    def setup(self, api: PluginRuntimeApi) -> None:
        provider_module = _load_sibling("provider.py")
        tools_module = _load_sibling("tools.py")
        cicd_tool = tools_module.cicd_run_pipeline_tool
        cicd_tool._plugin_origin = self.name

        api.register_provider("pipeline:drone", provider_module.DronePipelineProvider)
        api.register_tool_factory(
            lambda _context: {tools_module.CICD_RUN_PIPELINE_TOOL_NAME: cicd_tool}
        )
        api.register_config_schema(
            DRONE_PLUGIN_CONFIG_SCHEMA,
            config_ui_hints=DRONE_PLUGIN_CONFIG_UI_HINTS,
            defaults=DRONE_PLUGIN_CONFIG_DEFAULTS,
            secret_paths=DRONE_PLUGIN_CONFIG_SECRET_PATHS,
        )
        api.register_service("drone:defaults", DRONE_PLUGIN_DEFAULTS)
        api.register_service("drone:secret_paths", DRONE_PLUGIN_SECRET_PATHS)


plugin = DronePipelinePlugin()
