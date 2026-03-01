"""Example Showcase Plugin -- comprehensive demo of ALL MemStack plugin capabilities.

This plugin demonstrates every registration API available to plugin authors:

  1. Tool registration       -- register_tool_factory()
  2. Skill registration      -- SKILL.md files in skills/ directory (preferred)
                                 or register_skill_factory() (backward compat)
  3. Hook registration       -- register_hook() with priorities
  4. HTTP route registration -- register_http_route()
  5. CLI command registration-- register_cli_command()
  6. Lifecycle hooks          -- register_lifecycle_hook()
  7. Config schema validation -- register_config_schema()
  8. Command registration    -- register_command()
  9. Service registration    -- register_service()
  10. Provider registration  -- register_provider()

Discovery: The plugin runtime discovers this module via:
  .memstack/plugins/example-showcase/plugin.py

The runtime resolves the ``plugin`` module-level variable (or a class with
``setup(api)``), then calls ``setup(api)`` where ``api`` is a
``PluginRuntimeApi`` instance scoped to this plugin's name.

IMPORTANT: Local plugins are loaded via importlib.util.spec_from_file_location
WITHOUT a package context, so relative imports (from .foo import bar) will NOT
work. Instead we use a _load_sibling() helper to import co-located modules.

Usage:
  plugin_manager(action="enable", plugin_name="example-showcase")
  plugin_manager(action="reload")
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

# ---------------------------------------------------------------------------
# Sibling module loader
# ---------------------------------------------------------------------------

_PLUGIN_DIR = Path(__file__).resolve().parent


def _load_sibling(module_file: str) -> ModuleType:
    """Load a Python module from the same directory as this plugin file.

    This avoids relative imports which fail when the plugin is loaded
    via importlib.util.spec_from_file_location (no package context).
    """
    file_path = _PLUGIN_DIR / module_file
    module_name = f"example_showcase_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load sibling module: {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# Load co-located modules
_tools_mod = _load_sibling("tools.py")
_handlers_mod = _load_sibling("handlers.py")


# ---------------------------------------------------------------------------
# Plugin config schema (JSON Schema)
# ---------------------------------------------------------------------------

PLUGIN_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "default_language": {
            "type": "string",
            "description": "Default language for greetings",
            "enum": ["en", "zh", "ja", "es", "fr"],
            "default": "en",
        },
        "max_echo_length": {
            "type": "integer",
            "description": "Maximum character length for echo tool input",
            "minimum": 1,
            "maximum": 100000,
            "default": 10000,
        },
        "enable_audit_logging": {
            "type": "boolean",
            "description": "Enable audit logging for tool executions",
            "default": False,
        },
    },
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------


class ExampleShowcasePlugin:
    """Comprehensive example plugin demonstrating all MemStack plugin capabilities."""

    name = "example-showcase"

    # Optional: config dict that gets validated against the schema above.
    config: dict[str, Any] = {
        "default_language": "en",
        "max_echo_length": 10000,
        "enable_audit_logging": False,
    }

    def setup(self, api: Any) -> None:
        """Register all plugin contributions into the runtime API.

        This is the single entry point called by the plugin loader.
        The ``api`` parameter is a ``PluginRuntimeApi`` instance scoped
        to this plugin's name ("example-showcase").

        Registration order does not matter -- the registry stores
        registrations and the runtime resolves them when needed.
        """

        # -- 1. Tools ----------------------------------------------------------
        EchoTool = _tools_mod.EchoTool
        RandomNumberTool = _tools_mod.RandomNumberTool
        TimestampTool = _tools_mod.TimestampTool

        def _tool_factory(_context: Any) -> dict[str, Any]:
            return {
                "showcase_echo": EchoTool(),
                "showcase_random": RandomNumberTool(),
                "showcase_timestamp": TimestampTool(),
            }

        api.register_tool_factory(_tool_factory)

        # -- 2. Skills ---------------------------------------------------------
        # Skills are loaded automatically from ./skills/ directory via SKILL.md
        # files declared in memstack.plugin.json: "skills": ["./skills"].
        # No manual registration needed -- the plugin runtime scans for SKILL.md
        # files and creates Skill domain entities automatically.
        #
        # For backward compatibility, you can still use:
        #   api.register_skill_factory(my_skill_factory)
        # But SKILL.md files are the preferred approach.
        # -- 3. Hooks (with priority) -----------------------------------------
        api.register_hook(
            "before_tool_execution",
            _handlers_mod.on_before_tool_execution,
            priority=10,  # High priority -- runs early
        )
        api.register_hook(
            "after_tool_execution",
            _handlers_mod.on_after_tool_execution,
            priority=100,  # Normal priority
        )
        api.register_hook(
            "agent_session_start",
            _handlers_mod.on_agent_session_start,
            priority=50,
        )

        # -- 4. HTTP Routes ----------------------------------------------------
        api.register_http_route(
            "GET",
            "/plugins/showcase/health",
            _handlers_mod.health_check_handler,
            summary="Showcase plugin health check",
            tags=["showcase"],
        )
        api.register_http_route(
            "POST",
            "/plugins/showcase/echo",
            _handlers_mod.echo_api_handler,
            summary="Echo JSON body",
            tags=["showcase"],
        )
        api.register_http_route(
            "GET",
            "/plugins/showcase/stats",
            _handlers_mod.stats_handler,
            summary="Plugin statistics",
            tags=["showcase"],
        )

        # -- 5. CLI Commands ---------------------------------------------------
        api.register_cli_command(
            "showcase-info",
            _handlers_mod.cli_info_handler,
            description="Display showcase plugin information",
        )
        api.register_cli_command(
            "showcase-greet",
            _handlers_mod.cli_greet_handler,
            description="Greet a user by name",
            args_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name to greet",
                        "default": "World",
                    },
                    "language": {
                        "type": "string",
                        "description": "Language code (en, zh, ja, es, fr)",
                        "enum": ["en", "zh", "ja", "es", "fr"],
                        "default": "en",
                    },
                },
            },
        )

        # -- 6. Lifecycle Hooks ------------------------------------------------
        api.register_lifecycle_hook("on_load", _handlers_mod.on_load_handler)
        api.register_lifecycle_hook("on_enable", _handlers_mod.on_enable_handler)
        api.register_lifecycle_hook("on_disable", _handlers_mod.on_disable_handler)
        api.register_lifecycle_hook("on_unload", _handlers_mod.on_unload_handler)

        # -- 7. Config Schema --------------------------------------------------
        api.register_config_schema(PLUGIN_CONFIG_SCHEMA)

        # -- 8. Commands -------------------------------------------------------
        api.register_command("showcase.hello", _handlers_mod.showcase_command_handler)

        # -- 9. Services -------------------------------------------------------
        api.register_service("showcase-greeting", _handlers_mod.ShowcaseGreetingService())

        # -- 10. Providers -----------------------------------------------------
        default_lang = self.config.get("default_language", "en")
        api.register_provider(
            "example-greeting",
            _handlers_mod.ShowcaseGreetingProvider(default_language=default_lang),
        )


# Module-level export -- the plugin discovery system resolves this first.
plugin = ExampleShowcasePlugin()
