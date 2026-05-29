"""Darwinian Evolver skill plugin.

The plugin intentionally does not import ``darwinian_evolver``. The upstream
project is AGPL-3.0, so runtime use is kept in user-invoked subprocess scripts
shipped with the SKILL.md guidance.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

_PLUGIN_DIR = Path(__file__).resolve().parent

DARWINIAN_EVOLVER_CONFIG_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "cache_dir": {
            "type": "string",
            "default": "~/.memstack/cache/darwinian-evolver",
        },
        "default_model": {"type": "string", "default": "openai/gpt-4o-mini"},
        "default_iterations": {"type": "integer", "minimum": 1, "default": 3},
        "default_parent_count": {"type": "integer", "minimum": 1, "default": 2},
        "default_concurrency": {"type": "integer", "minimum": 1, "default": 2},
    },
}

DARWINIAN_EVOLVER_UI_HINTS = {
    "cache_dir": {
        "label": "Cache Directory",
        "help": "Where the upstream darwinian_evolver checkout is kept.",
    },
    "default_model": {
        "label": "Default OpenRouter Model",
        "placeholder": "openai/gpt-4o-mini",
    },
    "default_iterations": {"label": "Default Iterations"},
    "default_parent_count": {"label": "Default Parent Count"},
    "default_concurrency": {"label": "Default Concurrency"},
}

DARWINIAN_EVOLVER_DEFAULTS = {
    "cache_dir": "~/.memstack/cache/darwinian-evolver",
    "default_model": "openai/gpt-4o-mini",
    "default_iterations": 3,
    "default_parent_count": 2,
    "default_concurrency": 2,
    "plugin_dir": str(_PLUGIN_DIR),
    "skill_dir": str(_PLUGIN_DIR / "darwinian-evolver"),
}


class DarwinianEvolverPlugin:
    name = "darwinian-evolver-plugin"

    def setup(self, api: PluginRuntimeApi) -> None:
        api.register_config_schema(
            DARWINIAN_EVOLVER_CONFIG_SCHEMA,
            config_ui_hints=DARWINIAN_EVOLVER_UI_HINTS,
            defaults=DARWINIAN_EVOLVER_DEFAULTS,
            secret_paths=[],
        )
        api.register_service("darwinian_evolver:defaults", DARWINIAN_EVOLVER_DEFAULTS)


plugin = DarwinianEvolverPlugin()
