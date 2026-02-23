"""Reload planner primitives for plugin runtime lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence


@dataclass(frozen=True)
class PluginReloadPlan:
    """Structured reload plan for plugin runtime mutations."""

    action: str
    dry_run: bool
    trigger_scope: str
    plugin_name: Optional[str]
    reason: Optional[str]
    steps: tuple[str, ...]
    inventory: Dict[str, int]
    diagnostics_count: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert plan to a JSON-friendly dictionary."""
        return {
            "action": self.action,
            "dry_run": self.dry_run,
            "trigger_scope": self.trigger_scope,
            "plugin_name": self.plugin_name,
            "reason": self.reason,
            "steps": list(self.steps),
            "inventory": dict(self.inventory),
            "diagnostics_count": self.diagnostics_count,
        }


def build_plugin_reload_plan(
    *,
    action: str,
    dry_run: bool,
    plugin_name: Optional[str],
    tenant_id: Optional[str],
    plugins: Sequence[Dict[str, Any]],
    diagnostics: Sequence[Any],
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a lightweight reload plan summary for plugin operations."""
    trigger_scope = "tenant" if tenant_id else "global"
    inventory = {
        "total_plugins": len(plugins),
        "enabled_plugins": sum(1 for item in plugins if bool(item.get("enabled", True))),
        "discovered_plugins": sum(1 for item in plugins if bool(item.get("discovered", False))),
    }
    plan = PluginReloadPlan(
        action=action,
        dry_run=dry_run,
        trigger_scope=trigger_scope,
        plugin_name=plugin_name,
        reason=reason,
        steps=_default_steps(action, plugin_name=plugin_name, dry_run=dry_run),
        inventory=inventory,
        diagnostics_count=len(diagnostics),
    )
    return plan.to_dict()


def _default_steps(action: str, *, plugin_name: Optional[str], dry_run: bool) -> tuple[str, ...]:
    scope = plugin_name or "*"
    steps: list[str] = [f"validate-action:{action}"]
    if dry_run:
        steps.append("skip-runtime-mutation")
    else:
        steps.extend(
            [
                f"discover-plugins:{scope}",
                "rebuild-runtime-registry",
                "invalidate-tool-caches",
            ]
        )
    return tuple(steps)
