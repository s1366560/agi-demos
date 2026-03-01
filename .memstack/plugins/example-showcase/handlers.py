"""Example handlers for hooks, HTTP routes, CLI commands, and lifecycle events.

This module demonstrates all handler types supported by the plugin system.
Each handler follows a simple pattern: accept context/args, return a result or None.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hook handlers
# ---------------------------------------------------------------------------


async def on_before_tool_execution(context: Any) -> Any:
    """Hook handler invoked before a tool executes.

    Demonstrates a high-priority hook that logs tool invocations.
    In production, this could add audit trails, modify arguments, or
    enforce policies.
    """
    tool_name = getattr(context, "tool_name", "unknown")
    logger.info("[showcase] before_tool_execution: tool=%s", tool_name)
    return None


async def on_after_tool_execution(context: Any) -> Any:
    """Hook handler invoked after a tool executes.

    Demonstrates a normal-priority hook that records tool execution results.
    """
    tool_name = getattr(context, "tool_name", "unknown")
    logger.info("[showcase] after_tool_execution: tool=%s", tool_name)
    return None


async def on_agent_session_start(context: Any) -> Any:
    """Hook handler invoked when an agent session starts.

    Demonstrates session initialization logic.
    """
    logger.info("[showcase] agent_session_start")
    return None


# ---------------------------------------------------------------------------
# HTTP route handlers
# ---------------------------------------------------------------------------


async def health_check_handler(request: Any) -> dict[str, Any]:
    """GET /plugins/showcase/health -- plugin health check endpoint.

    Returns the plugin's health status and uptime info.
    """
    return {
        "plugin": "example-showcase",
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
    }


async def echo_api_handler(request: Any) -> dict[str, Any]:
    """POST /plugins/showcase/echo -- echo JSON body back.

    Demonstrates a POST handler that processes request body.
    """
    body = getattr(request, "body", None)
    if body is None:
        body = {"message": "no body provided"}
    return {
        "plugin": "example-showcase",
        "echo": body,
    }


async def stats_handler(request: Any) -> dict[str, Any]:
    """GET /plugins/showcase/stats -- return plugin statistics.

    Returns mock statistics for demonstration purposes.
    """
    return {
        "plugin": "example-showcase",
        "stats": {
            "tools_registered": 3,
            "skills_registered": 2,
            "hooks_registered": 3,
            "uptime_seconds": 0,
        },
    }


# ---------------------------------------------------------------------------
# CLI command handlers
# ---------------------------------------------------------------------------


async def cli_info_handler(args: dict[str, Any]) -> str:
    """CLI command: showcase info -- print plugin information.

    Demonstrates a CLI command that returns structured text.
    """
    info = {
        "name": "example-showcase",
        "version": "1.0.0",
        "description": "Comprehensive example plugin for MemStack",
        "capabilities": [
            "tools (3)",
            "skills (2)",
            "hooks (3)",
            "http_routes (3)",
            "cli_commands (2)",
            "lifecycle_hooks (4)",
            "config_schema",
            "commands (1)",
            "services (1)",
            "providers (1)",
        ],
    }
    return json.dumps(info, indent=2)


async def cli_greet_handler(args: dict[str, Any]) -> str:
    """CLI command: showcase greet -- greet a user by name.

    Demonstrates a CLI command with arguments.
    """
    name = args.get("name", "World")
    language = args.get("language", "en")

    greetings = {
        "en": f"Hello, {name}!",
        "zh": f"你好, {name}!",
        "ja": f"こんにちは, {name}!",
        "es": f"Hola, {name}!",
        "fr": f"Bonjour, {name}!",
    }

    return greetings.get(language, greetings["en"])


# ---------------------------------------------------------------------------
# Lifecycle handlers
# ---------------------------------------------------------------------------


async def on_load_handler() -> None:
    """Called after plugin setup() completes and registrations are wired."""
    logger.info("[showcase] lifecycle: on_load -- plugin loaded successfully")


async def on_enable_handler() -> None:
    """Called when the plugin is enabled at runtime."""
    logger.info("[showcase] lifecycle: on_enable -- plugin enabled")


async def on_disable_handler() -> None:
    """Called when the plugin is disabled at runtime."""
    logger.info("[showcase] lifecycle: on_disable -- plugin disabled")


async def on_unload_handler() -> None:
    """Called when the plugin is unloaded from the runtime."""
    logger.info("[showcase] lifecycle: on_unload -- plugin unloaded, cleaning up")


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------


async def showcase_command_handler(**kwargs: Any) -> str:
    """Runtime command handler for 'showcase.hello'.

    Commands differ from CLI commands: they are invoked programmatically
    by the agent runtime rather than from a terminal.
    """
    name = kwargs.get("name", "World")
    return f"Showcase plugin says hello to {name}!"


# ---------------------------------------------------------------------------
# Service & Provider
# ---------------------------------------------------------------------------


class ShowcaseGreetingService:
    """Example service exposed by the plugin.

    Services are singleton objects registered in the plugin registry that
    other plugins or the runtime can look up by name.
    """

    def greet(self, name: str, language: str = "en") -> str:
        greetings = {
            "en": f"Hello, {name}!",
            "zh": f"你好, {name}!",
            "ja": f"こんにちは, {name}!",
        }
        return greetings.get(language, greetings["en"])


class ShowcaseGreetingProvider:
    """Example provider exposed by the plugin.

    Providers are factory-like objects registered in the plugin registry.
    They follow a similar pattern to services but are intended for
    creating instances rather than acting as singletons.
    """

    def __init__(self, default_language: str = "en") -> None:
        self._default_language = default_language

    def create_greeting(self, name: str, language: str | None = None) -> str:
        lang = language or self._default_language
        return ShowcaseGreetingService().greet(name, lang)
