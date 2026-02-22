"""Tool for plugin runtime install/list/enable/disable/reload operations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.infrastructure.agent.plugins.manager import get_plugin_runtime_manager
from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.agent.tools.self_modifying_lifecycle import (
    SelfModifyingLifecycleOrchestrator,
)

logger = logging.getLogger(__name__)

TOOL_NAME = "plugin_manager"


class PluginManagerTool(AgentTool):
    """Manage runtime plugins installed via Python package entry points."""

    def __init__(self, tenant_id: Optional[str], project_id: Optional[str]) -> None:
        super().__init__(name=TOOL_NAME, description=self._build_description())
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._pending_events: list[Any] = []

    @staticmethod
    def _build_description() -> str:
        return (
            "Manage runtime plugins with list/install/enable/disable/reload actions. "
            "Plugins can be discovered from local folders `.memstack/plugins/<name>/plugin.py` "
            "or Python entry points in group 'memstack.agent_plugins'. "
            "Use install to pip-install a package, then reload or enable specific plugin names."
        )

    def consume_pending_events(self) -> list[Any]:
        """Consume pending SSE events buffered during execute()."""
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get tool parameter schema for function calling."""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "install", "enable", "disable", "reload", "uninstall"],
                    "description": "Plugin management action. Default: list",
                },
                "requirement": {
                    "type": "string",
                    "description": "Package requirement for install action (e.g. my-plugin-package==1.0.0)",
                },
                "plugin_name": {
                    "type": "string",
                    "description": "Plugin name for enable/disable/uninstall actions",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """Execute plugin management operation."""
        action = str(kwargs.get("action", "list")).strip().lower() or "list"
        manager = get_plugin_runtime_manager()

        if action == "list":
            plugins, diagnostics = manager.list_plugins(tenant_id=self._tenant_id)
            return {
                "title": "Plugin runtime status",
                "output": self._format_plugin_list(plugins),
                "metadata": {
                    "action": action,
                    "plugins": plugins,
                    "diagnostics": [_serialize_diagnostic(item) for item in diagnostics],
                },
            }

        if action == "install":
            requirement = str(kwargs.get("requirement", "")).strip()
            if not requirement:
                return self._error_response("requirement is required for install action")

            result = await manager.install_plugin(requirement)
            if not result.get("success"):
                return self._error_response(
                    "plugin install failed",
                    action=action,
                    requirement=requirement,
                    details=result,
                )

            lifecycle = self._run_lifecycle(action=action, plugin_name=None)
            self._append_toolset_changed_event(
                action=action,
                plugin_name=None,
                lifecycle=lifecycle,
                details=result,
            )
            return {
                "title": "Plugin installed",
                "output": (
                    f"Installed requirement: {requirement}\n"
                    f"Discovered plugins: {', '.join(result.get('new_plugins', [])) or '(none)'}"
                ),
                "metadata": {
                    "action": action,
                    "requirement": requirement,
                    "result": result,
                    "lifecycle": lifecycle,
                },
            }

        if action in {"enable", "disable"}:
            plugin_name = str(kwargs.get("plugin_name", "")).strip()
            if not plugin_name:
                return self._error_response("plugin_name is required for enable/disable actions")

            enabled = action == "enable"
            diagnostics = await manager.set_plugin_enabled(
                plugin_name,
                enabled=enabled,
                tenant_id=self._tenant_id,
            )
            lifecycle = self._run_lifecycle(action=action, plugin_name=plugin_name)
            self._append_toolset_changed_event(
                action=action,
                plugin_name=plugin_name,
                lifecycle=lifecycle,
                details={
                    "diagnostics": [_serialize_diagnostic(item) for item in diagnostics],
                },
            )
            return {
                "title": f"Plugin {action}d",
                "output": f"Plugin '{plugin_name}' is now {'enabled' if enabled else 'disabled'}.",
                "metadata": {
                    "action": action,
                    "plugin_name": plugin_name,
                    "diagnostics": [_serialize_diagnostic(item) for item in diagnostics],
                    "lifecycle": lifecycle,
                },
            }

        if action == "uninstall":
            plugin_name = str(kwargs.get("plugin_name", "")).strip()
            if not plugin_name:
                return self._error_response("plugin_name is required for uninstall action")

            result = await manager.uninstall_plugin(plugin_name)
            if not result.get("success"):
                return self._error_response(
                    "plugin uninstall failed",
                    action=action,
                    plugin_name=plugin_name,
                    details=result,
                )

            lifecycle = self._run_lifecycle(action=action, plugin_name=plugin_name)
            self._append_toolset_changed_event(
                action=action,
                plugin_name=plugin_name,
                lifecycle=lifecycle,
                details=result,
            )
            return {
                "title": "Plugin uninstalled",
                "output": f"Uninstalled plugin '{plugin_name}'",
                "metadata": {
                    "action": action,
                    "plugin_name": plugin_name,
                    "result": result,
                    "lifecycle": lifecycle,
                },
            }

        if action == "reload":
            diagnostics = await manager.reload()
            lifecycle = self._run_lifecycle(action=action, plugin_name=None)
            self._append_toolset_changed_event(
                action=action,
                plugin_name=None,
                lifecycle=lifecycle,
                details={
                    "diagnostics": [_serialize_diagnostic(item) for item in diagnostics],
                },
            )
            return {
                "title": "Plugin runtime reloaded",
                "output": "Plugin runtime discovery and registry reload completed.",
                "metadata": {
                    "action": action,
                    "diagnostics": [_serialize_diagnostic(item) for item in diagnostics],
                    "lifecycle": lifecycle,
                },
            }

        return self._error_response(f"Unsupported action: {action}")

    def _run_lifecycle(self, *, action: str, plugin_name: Optional[str]) -> Dict[str, Any]:
        lifecycle = SelfModifyingLifecycleOrchestrator.run_post_change(
            source=TOOL_NAME,
            tenant_id=self._tenant_id,
            project_id=self._project_id,
            clear_tool_definitions=True,
            metadata={
                "action": action,
                "plugin_name": plugin_name,
            },
        )
        logger.info(
            "Plugin manager lifecycle completed for tenant=%s project=%s: %s",
            self._tenant_id,
            self._project_id,
            lifecycle.get("cache_invalidation", {}),
        )
        return lifecycle

    def _append_toolset_changed_event(
        self,
        *,
        action: str,
        plugin_name: Optional[str],
        lifecycle: Dict[str, Any],
        details: Dict[str, Any],
    ) -> None:
        self._pending_events.append(
            {
                "type": "toolset_changed",
                "data": {
                    "source": TOOL_NAME,
                    "tenant_id": self._tenant_id,
                    "project_id": self._project_id,
                    "action": action,
                    "plugin_name": plugin_name,
                    "details": details,
                    "lifecycle": lifecycle,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    @staticmethod
    def _format_plugin_list(plugins: list[Dict[str, Any]]) -> str:
        if not plugins:
            return "No plugins discovered."
        lines = []
        for item in plugins:
            source = item.get("source") or "unknown"
            package = item.get("package") or "-"
            enabled = "enabled" if item.get("enabled", True) else "disabled"
            lines.append(f"- {item['name']} [{enabled}] source={source} package={package}")
        return "\n".join(lines)

    @staticmethod
    def _error_response(message: str, **extra: Any) -> Dict[str, Any]:
        return {
            "title": "Plugin Manager Failed",
            "output": f"Error: {message}",
            "metadata": {
                "action": "error",
                "error": message,
                **extra,
            },
        }


def _serialize_diagnostic(diagnostic: Any) -> Dict[str, Any]:
    return {
        "plugin_name": diagnostic.plugin_name,
        "code": diagnostic.code,
        "message": diagnostic.message,
        "level": diagnostic.level,
    }
