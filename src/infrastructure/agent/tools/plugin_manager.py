"""Tool for plugin runtime install/list/enable/disable/reload operations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from src.infrastructure.agent.plugins.manager import get_plugin_runtime_manager
from src.infrastructure.agent.plugins.reload_planner import build_plugin_reload_plan
from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.agent.tools.mutation_ledger import MutationLedger, get_mutation_ledger
from src.infrastructure.agent.tools.mutation_transaction import (
    MutationTransaction,
    MutationTransactionStatus,
)
from src.infrastructure.agent.tools.self_modifying_lifecycle import (
    SelfModifyingLifecycleOrchestrator,
)
from src.infrastructure.agent.tools.tool_mutation_guard import build_mutation_fingerprint

logger = logging.getLogger(__name__)

TOOL_NAME = "plugin_manager"


class PluginManagerTool(AgentTool):
    """Manage runtime plugins installed via Python package entry points."""

    def __init__(
        self,
        tenant_id: Optional[str],
        project_id: Optional[str],
        *,
        mutation_ledger: Optional[MutationLedger] = None,
        mutation_loop_threshold: int = 10,
        mutation_loop_window_seconds: int = 120,
    ) -> None:
        super().__init__(name=TOOL_NAME, description=self._build_description())
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._pending_events: list[Any] = []
        self._mutation_ledger = mutation_ledger or get_mutation_ledger()
        self._mutation_loop_threshold = max(1, int(mutation_loop_threshold))
        self._mutation_loop_window_seconds = max(1, int(mutation_loop_window_seconds))

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
                "dry_run": {
                    "type": "boolean",
                    "description": "When true, return mutation/reload plan without applying changes.",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:  # noqa: ANN401
        """Execute plugin management operation."""
        action = str(kwargs.get("action", "list")).strip().lower() or "list"
        dry_run = self._as_bool(kwargs.get("dry_run", False))
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
            before_snapshot = self._snapshot_plugin_inventory(manager)

            trace_id = self._build_trace_id()
            transaction = self._start_mutation_transaction(
                trace_id=trace_id,
                action=action,
                plugin_name=None,
                requirement=requirement,
            )
            mutation_fingerprint = self._build_mutation_fingerprint(
                action=action,
                plugin_name=None,
                requirement=requirement,
            )
            mutation_guard = self._evaluate_mutation_guard(mutation_fingerprint)
            rollback = self._build_rollback_metadata(
                action=action,
                plugin_name=None,
                requirement=requirement,
                before_snapshot=before_snapshot,
            )
            if mutation_guard["blocked"] and not dry_run:
                transaction.add_phase(
                    MutationTransactionStatus.BLOCKED,
                    details={"mutation_guard": mutation_guard},
                )
                mutation_audit = self._record_mutation_audit(
                    trace_id=trace_id,
                    action=action,
                    plugin_name=None,
                    requirement=requirement,
                    mutation_fingerprint=mutation_fingerprint,
                    status="blocked",
                    dry_run=False,
                    rollback=rollback,
                    message="mutation blocked by loop guard",
                    details={
                        "mutation_guard": mutation_guard,
                        "mutation_transaction": transaction.to_dict(),
                    },
                )
                return self._error_response(
                    "mutation blocked by loop guard",
                    action=action,
                    requirement=requirement,
                    trace_id=trace_id,
                    mutation_fingerprint=mutation_fingerprint,
                    mutation_guard=mutation_guard,
                    mutation_audit=mutation_audit,
                    rollback=rollback,
                    mutation_transaction=transaction.to_dict(),
                )
            reload_plan = self._build_reload_plan(
                manager=manager,
                action=action,
                plugin_name=None,
                dry_run=dry_run,
                reason=f"install requirement {requirement}",
            )
            if dry_run:
                transaction.add_phase(
                    MutationTransactionStatus.DRY_RUN,
                    details={"reload_plan": reload_plan, "rollback": rollback},
                )
                mutation_audit = self._record_mutation_audit(
                    trace_id=trace_id,
                    action=action,
                    plugin_name=None,
                    requirement=requirement,
                    mutation_fingerprint=mutation_fingerprint,
                    status="dry_run",
                    dry_run=True,
                    rollback=rollback,
                    message="dry_run",
                    details={
                        "reload_plan": reload_plan,
                        "mutation_transaction": transaction.to_dict(),
                    },
                )
                return {
                    "title": "Plugin install plan",
                    "output": f"[dry-run] Would install requirement: {requirement}",
                    "metadata": {
                        "action": action,
                        "dry_run": True,
                        "requirement": requirement,
                        "trace_id": trace_id,
                        "mutation_fingerprint": mutation_fingerprint,
                        "mutation_guard": mutation_guard,
                        "mutation_audit": mutation_audit,
                        "reload_plan": reload_plan,
                        "rollback": rollback,
                        "mutation_transaction": transaction.to_dict(),
                        "provenance_preview": {
                            "before_count": len(before_snapshot),
                        },
                    },
                }

            result = await manager.install_plugin(requirement)
            if not result.get("success"):
                transaction.add_phase(
                    MutationTransactionStatus.FAILED,
                    details={"result": result},
                )
                mutation_audit = self._record_mutation_audit(
                    trace_id=trace_id,
                    action=action,
                    plugin_name=None,
                    requirement=requirement,
                    mutation_fingerprint=mutation_fingerprint,
                    status="failed",
                    dry_run=False,
                    rollback=rollback,
                    message="plugin install failed",
                    details={
                        "result": result,
                        "mutation_transaction": transaction.to_dict(),
                    },
                )
                return self._error_response(
                    "plugin install failed",
                    action=action,
                    requirement=requirement,
                    details=result,
                    trace_id=trace_id,
                    mutation_fingerprint=mutation_fingerprint,
                    mutation_guard=mutation_guard,
                    mutation_audit=mutation_audit,
                    rollback=rollback,
                    mutation_transaction=transaction.to_dict(),
                )
            after_snapshot = self._snapshot_plugin_inventory(manager)
            provenance = self._build_provenance_summary(
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
            )
            rollback = self._build_rollback_metadata(
                action=action,
                plugin_name=None,
                requirement=requirement,
                before_snapshot=before_snapshot,
                provenance=provenance,
            )
            mutation_audit = self._record_mutation_audit(
                trace_id=trace_id,
                action=action,
                plugin_name=None,
                requirement=requirement,
                mutation_fingerprint=mutation_fingerprint,
                status="applied",
                dry_run=False,
                rollback=rollback,
                message="plugin installed",
                details={
                    "provenance": provenance,
                    "mutation_transaction": transaction.to_dict(),
                },
            )
            details = dict(result)
            details["provenance"] = provenance
            details["mutation_guard"] = mutation_guard
            details["mutation_audit"] = mutation_audit
            details["rollback"] = rollback

            lifecycle = self._run_lifecycle(
                action=action,
                plugin_name=None,
                trace_id=trace_id,
                mutation_fingerprint=mutation_fingerprint,
                reload_plan=reload_plan,
                rollback=rollback,
            )
            transaction.add_phase(
                MutationTransactionStatus.APPLIED,
                details={"provenance": provenance},
            )
            transaction.add_phase(
                MutationTransactionStatus.VERIFIED,
                details={"probe": lifecycle.get("probe", {})},
            )
            details["mutation_transaction"] = transaction.to_dict()
            self._append_toolset_changed_event(
                action=action,
                plugin_name=None,
                lifecycle=lifecycle,
                trace_id=trace_id,
                mutation_fingerprint=mutation_fingerprint,
                reload_plan=reload_plan,
                details=details,
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
                    "result": details,
                    "lifecycle": lifecycle,
                    "trace_id": trace_id,
                    "mutation_fingerprint": mutation_fingerprint,
                    "mutation_guard": mutation_guard,
                    "mutation_audit": mutation_audit,
                    "reload_plan": reload_plan,
                    "rollback": rollback,
                    "provenance": provenance,
                    "mutation_transaction": transaction.to_dict(),
                },
            }

        if action in {"enable", "disable"}:
            plugin_name = str(kwargs.get("plugin_name", "")).strip()
            if not plugin_name:
                return self._error_response("plugin_name is required for enable/disable actions")
            before_snapshot = self._snapshot_plugin_inventory(manager)

            enabled = action == "enable"
            trace_id = self._build_trace_id()
            transaction = self._start_mutation_transaction(
                trace_id=trace_id,
                action=action,
                plugin_name=plugin_name,
                requirement=None,
            )
            mutation_fingerprint = self._build_mutation_fingerprint(
                action=action,
                plugin_name=plugin_name,
            )
            mutation_guard = self._evaluate_mutation_guard(mutation_fingerprint)
            rollback = self._build_rollback_metadata(
                action=action,
                plugin_name=plugin_name,
                before_snapshot=before_snapshot,
            )
            if mutation_guard["blocked"] and not dry_run:
                transaction.add_phase(
                    MutationTransactionStatus.BLOCKED,
                    details={"mutation_guard": mutation_guard},
                )
                mutation_audit = self._record_mutation_audit(
                    trace_id=trace_id,
                    action=action,
                    plugin_name=plugin_name,
                    requirement=None,
                    mutation_fingerprint=mutation_fingerprint,
                    status="blocked",
                    dry_run=False,
                    rollback=rollback,
                    message="mutation blocked by loop guard",
                    details={
                        "mutation_guard": mutation_guard,
                        "mutation_transaction": transaction.to_dict(),
                    },
                )
                return self._error_response(
                    "mutation blocked by loop guard",
                    action=action,
                    plugin_name=plugin_name,
                    trace_id=trace_id,
                    mutation_fingerprint=mutation_fingerprint,
                    mutation_guard=mutation_guard,
                    mutation_audit=mutation_audit,
                    rollback=rollback,
                    mutation_transaction=transaction.to_dict(),
                )
            reload_plan = self._build_reload_plan(
                manager=manager,
                action=action,
                plugin_name=plugin_name,
                dry_run=dry_run,
                reason=f"{action} plugin {plugin_name}",
            )
            if dry_run:
                transaction.add_phase(
                    MutationTransactionStatus.DRY_RUN,
                    details={"reload_plan": reload_plan, "rollback": rollback},
                )
                mutation_audit = self._record_mutation_audit(
                    trace_id=trace_id,
                    action=action,
                    plugin_name=plugin_name,
                    requirement=None,
                    mutation_fingerprint=mutation_fingerprint,
                    status="dry_run",
                    dry_run=True,
                    rollback=rollback,
                    message="dry_run",
                    details={
                        "reload_plan": reload_plan,
                        "mutation_transaction": transaction.to_dict(),
                    },
                )
                return {
                    "title": f"Plugin {action} plan",
                    "output": f"[dry-run] Would set plugin '{plugin_name}' to enabled={enabled}.",
                    "metadata": {
                        "action": action,
                        "plugin_name": plugin_name,
                        "dry_run": True,
                        "trace_id": trace_id,
                        "mutation_fingerprint": mutation_fingerprint,
                        "mutation_guard": mutation_guard,
                        "mutation_audit": mutation_audit,
                        "reload_plan": reload_plan,
                        "rollback": rollback,
                        "mutation_transaction": transaction.to_dict(),
                        "provenance_preview": {
                            "before_count": len(before_snapshot),
                        },
                    },
                }

            diagnostics = await manager.set_plugin_enabled(
                plugin_name,
                enabled=enabled,
                tenant_id=self._tenant_id,
            )
            after_snapshot = self._snapshot_plugin_inventory(manager)
            provenance = self._build_provenance_summary(
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
            )
            mutation_audit = self._record_mutation_audit(
                trace_id=trace_id,
                action=action,
                plugin_name=plugin_name,
                requirement=None,
                mutation_fingerprint=mutation_fingerprint,
                status="applied",
                dry_run=False,
                rollback=rollback,
                message=f"plugin {action}d",
                details={
                    "provenance": provenance,
                    "mutation_transaction": transaction.to_dict(),
                },
            )
            details = {
                "diagnostics": [_serialize_diagnostic(item) for item in diagnostics],
                "provenance": provenance,
                "mutation_guard": mutation_guard,
                "mutation_audit": mutation_audit,
                "rollback": rollback,
            }
            lifecycle = self._run_lifecycle(
                action=action,
                plugin_name=plugin_name,
                trace_id=trace_id,
                mutation_fingerprint=mutation_fingerprint,
                reload_plan=reload_plan,
                rollback=rollback,
            )
            transaction.add_phase(
                MutationTransactionStatus.APPLIED,
                details={"provenance": provenance},
            )
            transaction.add_phase(
                MutationTransactionStatus.VERIFIED,
                details={"probe": lifecycle.get("probe", {})},
            )
            details["mutation_transaction"] = transaction.to_dict()
            self._append_toolset_changed_event(
                action=action,
                plugin_name=plugin_name,
                lifecycle=lifecycle,
                trace_id=trace_id,
                mutation_fingerprint=mutation_fingerprint,
                reload_plan=reload_plan,
                details=details,
            )
            return {
                "title": f"Plugin {action}d",
                "output": f"Plugin '{plugin_name}' is now {'enabled' if enabled else 'disabled'}.",
                "metadata": {
                    "action": action,
                    "plugin_name": plugin_name,
                    "diagnostics": [_serialize_diagnostic(item) for item in diagnostics],
                    "provenance": provenance,
                    "lifecycle": lifecycle,
                    "trace_id": trace_id,
                    "mutation_fingerprint": mutation_fingerprint,
                    "mutation_guard": mutation_guard,
                    "mutation_audit": mutation_audit,
                    "reload_plan": reload_plan,
                    "rollback": rollback,
                    "mutation_transaction": transaction.to_dict(),
                },
            }

        if action == "uninstall":
            plugin_name = str(kwargs.get("plugin_name", "")).strip()
            if not plugin_name:
                return self._error_response("plugin_name is required for uninstall action")
            before_snapshot = self._snapshot_plugin_inventory(manager)

            trace_id = self._build_trace_id()
            transaction = self._start_mutation_transaction(
                trace_id=trace_id,
                action=action,
                plugin_name=plugin_name,
                requirement=None,
            )
            mutation_fingerprint = self._build_mutation_fingerprint(
                action=action,
                plugin_name=plugin_name,
            )
            mutation_guard = self._evaluate_mutation_guard(mutation_fingerprint)
            rollback = self._build_rollback_metadata(
                action=action,
                plugin_name=plugin_name,
                before_snapshot=before_snapshot,
            )
            if mutation_guard["blocked"] and not dry_run:
                transaction.add_phase(
                    MutationTransactionStatus.BLOCKED,
                    details={"mutation_guard": mutation_guard},
                )
                mutation_audit = self._record_mutation_audit(
                    trace_id=trace_id,
                    action=action,
                    plugin_name=plugin_name,
                    requirement=None,
                    mutation_fingerprint=mutation_fingerprint,
                    status="blocked",
                    dry_run=False,
                    rollback=rollback,
                    message="mutation blocked by loop guard",
                    details={
                        "mutation_guard": mutation_guard,
                        "mutation_transaction": transaction.to_dict(),
                    },
                )
                return self._error_response(
                    "mutation blocked by loop guard",
                    action=action,
                    plugin_name=plugin_name,
                    trace_id=trace_id,
                    mutation_fingerprint=mutation_fingerprint,
                    mutation_guard=mutation_guard,
                    mutation_audit=mutation_audit,
                    rollback=rollback,
                    mutation_transaction=transaction.to_dict(),
                )
            reload_plan = self._build_reload_plan(
                manager=manager,
                action=action,
                plugin_name=plugin_name,
                dry_run=dry_run,
                reason=f"uninstall plugin {plugin_name}",
            )
            if dry_run:
                transaction.add_phase(
                    MutationTransactionStatus.DRY_RUN,
                    details={"reload_plan": reload_plan, "rollback": rollback},
                )
                mutation_audit = self._record_mutation_audit(
                    trace_id=trace_id,
                    action=action,
                    plugin_name=plugin_name,
                    requirement=None,
                    mutation_fingerprint=mutation_fingerprint,
                    status="dry_run",
                    dry_run=True,
                    rollback=rollback,
                    message="dry_run",
                    details={
                        "reload_plan": reload_plan,
                        "mutation_transaction": transaction.to_dict(),
                    },
                )
                return {
                    "title": "Plugin uninstall plan",
                    "output": f"[dry-run] Would uninstall plugin '{plugin_name}'.",
                    "metadata": {
                        "action": action,
                        "plugin_name": plugin_name,
                        "dry_run": True,
                        "trace_id": trace_id,
                        "mutation_fingerprint": mutation_fingerprint,
                        "mutation_guard": mutation_guard,
                        "mutation_audit": mutation_audit,
                        "reload_plan": reload_plan,
                        "rollback": rollback,
                        "mutation_transaction": transaction.to_dict(),
                        "provenance_preview": {
                            "before_count": len(before_snapshot),
                        },
                    },
                }

            result = await manager.uninstall_plugin(plugin_name)
            if not result.get("success"):
                transaction.add_phase(
                    MutationTransactionStatus.FAILED,
                    details={"result": result},
                )
                mutation_audit = self._record_mutation_audit(
                    trace_id=trace_id,
                    action=action,
                    plugin_name=plugin_name,
                    requirement=None,
                    mutation_fingerprint=mutation_fingerprint,
                    status="failed",
                    dry_run=False,
                    rollback=rollback,
                    message="plugin uninstall failed",
                    details={
                        "result": result,
                        "mutation_transaction": transaction.to_dict(),
                    },
                )
                return self._error_response(
                    "plugin uninstall failed",
                    action=action,
                    plugin_name=plugin_name,
                    details=result,
                    trace_id=trace_id,
                    mutation_fingerprint=mutation_fingerprint,
                    mutation_guard=mutation_guard,
                    mutation_audit=mutation_audit,
                    rollback=rollback,
                    mutation_transaction=transaction.to_dict(),
                )
            after_snapshot = self._snapshot_plugin_inventory(manager)
            provenance = self._build_provenance_summary(
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
            )
            rollback = self._build_rollback_metadata(
                action=action,
                plugin_name=plugin_name,
                before_snapshot=before_snapshot,
                provenance=provenance,
            )
            mutation_audit = self._record_mutation_audit(
                trace_id=trace_id,
                action=action,
                plugin_name=plugin_name,
                requirement=None,
                mutation_fingerprint=mutation_fingerprint,
                status="applied",
                dry_run=False,
                rollback=rollback,
                message="plugin uninstalled",
                details={
                    "provenance": provenance,
                    "mutation_transaction": transaction.to_dict(),
                },
            )
            details = dict(result)
            details["provenance"] = provenance
            details["mutation_guard"] = mutation_guard
            details["mutation_audit"] = mutation_audit
            details["rollback"] = rollback

            lifecycle = self._run_lifecycle(
                action=action,
                plugin_name=plugin_name,
                trace_id=trace_id,
                mutation_fingerprint=mutation_fingerprint,
                reload_plan=reload_plan,
                rollback=rollback,
            )
            transaction.add_phase(
                MutationTransactionStatus.APPLIED,
                details={"provenance": provenance},
            )
            transaction.add_phase(
                MutationTransactionStatus.VERIFIED,
                details={"probe": lifecycle.get("probe", {})},
            )
            details["mutation_transaction"] = transaction.to_dict()
            self._append_toolset_changed_event(
                action=action,
                plugin_name=plugin_name,
                lifecycle=lifecycle,
                trace_id=trace_id,
                mutation_fingerprint=mutation_fingerprint,
                reload_plan=reload_plan,
                details=details,
            )
            return {
                "title": "Plugin uninstalled",
                "output": f"Uninstalled plugin '{plugin_name}'",
                "metadata": {
                    "action": action,
                    "plugin_name": plugin_name,
                    "result": details,
                    "lifecycle": lifecycle,
                    "trace_id": trace_id,
                    "mutation_fingerprint": mutation_fingerprint,
                    "mutation_guard": mutation_guard,
                    "mutation_audit": mutation_audit,
                    "reload_plan": reload_plan,
                    "rollback": rollback,
                    "provenance": provenance,
                    "mutation_transaction": transaction.to_dict(),
                },
            }

        if action == "reload":
            before_snapshot = self._snapshot_plugin_inventory(manager)
            trace_id = self._build_trace_id()
            transaction = self._start_mutation_transaction(
                trace_id=trace_id,
                action=action,
                plugin_name=None,
                requirement=None,
            )
            mutation_fingerprint = self._build_mutation_fingerprint(
                action=action,
                plugin_name=None,
            )
            mutation_guard = self._evaluate_mutation_guard(mutation_fingerprint)
            rollback = self._build_rollback_metadata(
                action=action,
                plugin_name=None,
                before_snapshot=before_snapshot,
            )
            if mutation_guard["blocked"] and not dry_run:
                transaction.add_phase(
                    MutationTransactionStatus.BLOCKED,
                    details={"mutation_guard": mutation_guard},
                )
                mutation_audit = self._record_mutation_audit(
                    trace_id=trace_id,
                    action=action,
                    plugin_name=None,
                    requirement=None,
                    mutation_fingerprint=mutation_fingerprint,
                    status="blocked",
                    dry_run=False,
                    rollback=rollback,
                    message="mutation blocked by loop guard",
                    details={
                        "mutation_guard": mutation_guard,
                        "mutation_transaction": transaction.to_dict(),
                    },
                )
                return self._error_response(
                    "mutation blocked by loop guard",
                    action=action,
                    trace_id=trace_id,
                    mutation_fingerprint=mutation_fingerprint,
                    mutation_guard=mutation_guard,
                    mutation_audit=mutation_audit,
                    rollback=rollback,
                    mutation_transaction=transaction.to_dict(),
                )
            reload_plan = self._build_reload_plan(
                manager=manager,
                action=action,
                plugin_name=None,
                dry_run=dry_run,
                reason="manual reload request",
            )
            if dry_run:
                transaction.add_phase(
                    MutationTransactionStatus.DRY_RUN,
                    details={"reload_plan": reload_plan, "rollback": rollback},
                )
                mutation_audit = self._record_mutation_audit(
                    trace_id=trace_id,
                    action=action,
                    plugin_name=None,
                    requirement=None,
                    mutation_fingerprint=mutation_fingerprint,
                    status="dry_run",
                    dry_run=True,
                    rollback=rollback,
                    message="dry_run",
                    details={
                        "reload_plan": reload_plan,
                        "mutation_transaction": transaction.to_dict(),
                    },
                )
                return {
                    "title": "Plugin reload plan",
                    "output": "[dry-run] Plugin runtime reload plan generated.",
                    "metadata": {
                        "action": action,
                        "dry_run": True,
                        "trace_id": trace_id,
                        "mutation_fingerprint": mutation_fingerprint,
                        "mutation_guard": mutation_guard,
                        "mutation_audit": mutation_audit,
                        "reload_plan": reload_plan,
                        "rollback": rollback,
                        "mutation_transaction": transaction.to_dict(),
                        "provenance_preview": {
                            "before_count": len(before_snapshot),
                        },
                    },
                }

            diagnostics = await manager.reload()
            after_snapshot = self._snapshot_plugin_inventory(manager)
            provenance = self._build_provenance_summary(
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
            )
            mutation_audit = self._record_mutation_audit(
                trace_id=trace_id,
                action=action,
                plugin_name=None,
                requirement=None,
                mutation_fingerprint=mutation_fingerprint,
                status="applied",
                dry_run=False,
                rollback=rollback,
                message="plugin runtime reloaded",
                details={
                    "provenance": provenance,
                    "mutation_transaction": transaction.to_dict(),
                },
            )
            details = {
                "diagnostics": [_serialize_diagnostic(item) for item in diagnostics],
                "provenance": provenance,
                "mutation_guard": mutation_guard,
                "mutation_audit": mutation_audit,
                "rollback": rollback,
            }
            lifecycle = self._run_lifecycle(
                action=action,
                plugin_name=None,
                trace_id=trace_id,
                mutation_fingerprint=mutation_fingerprint,
                reload_plan=reload_plan,
                rollback=rollback,
            )
            transaction.add_phase(
                MutationTransactionStatus.APPLIED,
                details={"provenance": provenance},
            )
            transaction.add_phase(
                MutationTransactionStatus.VERIFIED,
                details={"probe": lifecycle.get("probe", {})},
            )
            details["mutation_transaction"] = transaction.to_dict()
            self._append_toolset_changed_event(
                action=action,
                plugin_name=None,
                lifecycle=lifecycle,
                trace_id=trace_id,
                mutation_fingerprint=mutation_fingerprint,
                reload_plan=reload_plan,
                details=details,
            )
            return {
                "title": "Plugin runtime reloaded",
                "output": "Plugin runtime discovery and registry reload completed.",
                "metadata": {
                    "action": action,
                    "diagnostics": [_serialize_diagnostic(item) for item in diagnostics],
                    "provenance": provenance,
                    "lifecycle": lifecycle,
                    "trace_id": trace_id,
                    "mutation_fingerprint": mutation_fingerprint,
                    "mutation_guard": mutation_guard,
                    "mutation_audit": mutation_audit,
                    "reload_plan": reload_plan,
                    "rollback": rollback,
                    "mutation_transaction": transaction.to_dict(),
                },
            }

        return self._error_response(f"Unsupported action: {action}")

    def _run_lifecycle(
        self,
        *,
        action: str,
        plugin_name: Optional[str],
        trace_id: str,
        mutation_fingerprint: Optional[str],
        reload_plan: Dict[str, Any],
        rollback: Dict[str, Any],
    ) -> Dict[str, Any]:
        lifecycle = SelfModifyingLifecycleOrchestrator.run_post_change(
            source=TOOL_NAME,
            tenant_id=self._tenant_id,
            project_id=self._project_id,
            clear_tool_definitions=True,
            metadata={
                "action": action,
                "plugin_name": plugin_name,
                "trace_id": trace_id,
                "mutation_fingerprint": mutation_fingerprint,
                "reload_plan": reload_plan,
                "rollback": rollback,
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
        trace_id: str,
        mutation_fingerprint: Optional[str],
        reload_plan: Dict[str, Any],
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
                    "trace_id": trace_id,
                    "mutation_fingerprint": mutation_fingerprint,
                    "reload_plan": reload_plan,
                    "details": details,
                    "lifecycle": lifecycle,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    def _build_reload_plan(
        self,
        *,
        manager: Any,  # noqa: ANN401
        action: str,
        plugin_name: Optional[str],
        dry_run: bool,
        reason: Optional[str],
    ) -> Dict[str, Any]:
        plugins, diagnostics = manager.list_plugins(tenant_id=self._tenant_id)
        return build_plugin_reload_plan(
            action=action,
            dry_run=dry_run,
            plugin_name=plugin_name,
            tenant_id=self._tenant_id,
            plugins=plugins,
            diagnostics=diagnostics,
            reason=reason,
        )

    def _build_mutation_fingerprint(
        self,
        *,
        action: str,
        plugin_name: Optional[str],
        requirement: Optional[str] = None,
    ) -> Optional[str]:
        payload: Dict[str, Any] = {
            "action": action,
            "plugin_name": plugin_name,
            "requirement": requirement,
            "tenant_id": self._tenant_id,
            "project_id": self._project_id,
        }
        normalized_payload = {
            key: value for key, value in payload.items() if value is not None and value != ""
        }
        return build_mutation_fingerprint(TOOL_NAME, normalized_payload)

    def _snapshot_plugin_inventory(self, manager: Any) -> list[Dict[str, Any]]:  # noqa: ANN401
        plugins, _diagnostics = manager.list_plugins(tenant_id=self._tenant_id)
        snapshot: list[Dict[str, Any]] = []
        for plugin in plugins:
            snapshot.append(
                {
                    "name": str(plugin.get("name", "")),
                    "source": plugin.get("source"),
                    "package": plugin.get("package"),
                    "version": plugin.get("version"),
                    "requirement": plugin.get("requirement"),
                    "kind": plugin.get("kind"),
                    "manifest_id": plugin.get("manifest_id"),
                    "providers": list(plugin.get("providers") or []),
                    "skills": list(plugin.get("skills") or []),
                    "enabled": bool(plugin.get("enabled", True)),
                    "discovered": bool(plugin.get("discovered", True)),
                }
            )
        snapshot.sort(key=lambda item: item["name"])
        return snapshot

    @staticmethod
    def _build_provenance_summary(
        *,
        before_snapshot: list[Dict[str, Any]],
        after_snapshot: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        before_by_name = {item["name"]: item for item in before_snapshot}
        after_by_name = {item["name"]: item for item in after_snapshot}
        before_names = set(before_by_name.keys())
        after_names = set(after_by_name.keys())
        changed = sorted(
            name
            for name in (before_names & after_names)
            if before_by_name[name] != after_by_name[name]
        )
        return {
            "before_count": len(before_snapshot),
            "after_count": len(after_snapshot),
            "added": sorted(after_names - before_names),
            "removed": sorted(before_names - after_names),
            "changed": changed,
            "after_snapshot": after_snapshot,
        }

    def _evaluate_mutation_guard(self, mutation_fingerprint: Optional[str]) -> Dict[str, Any]:
        guard = {
            "blocked": False,
            "recent_count": 0,
            "threshold": self._mutation_loop_threshold,
            "window_seconds": self._mutation_loop_window_seconds,
            "last_seen_at": None,
        }
        if not mutation_fingerprint:
            return guard
        evaluated = self._mutation_ledger.evaluate_loop_guard(
            mutation_fingerprint,
            threshold=self._mutation_loop_threshold,
            window_seconds=self._mutation_loop_window_seconds,
        )
        guard.update(evaluated)
        return guard

    def _record_mutation_audit(
        self,
        *,
        trace_id: str,
        action: str,
        plugin_name: Optional[str],
        requirement: Optional[str],
        mutation_fingerprint: Optional[str],
        status: str,
        dry_run: bool,
        rollback: Dict[str, Any],
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "trace_id": trace_id,
            "source": TOOL_NAME,
            "tenant_id": self._tenant_id,
            "project_id": self._project_id,
            "action": action,
            "plugin_name": plugin_name,
            "requirement": requirement,
            "mutation_fingerprint": mutation_fingerprint,
            "status": status,
            "dry_run": bool(dry_run),
            "message": message,
            "rollback": rollback,
            "details": details or {},
        }
        return self._mutation_ledger.append(payload)

    def _build_rollback_metadata(
        self,
        *,
        action: str,
        plugin_name: Optional[str],
        before_snapshot: list[Dict[str, Any]],
        requirement: Optional[str] = None,
        provenance: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        rollback: Dict[str, Any] = {
            "source_action": action,
            "available": False,
            "action": None,
            "inputs": {},
            "reason": "",
        }
        if action == "enable" and plugin_name:
            rollback.update(
                {
                    "available": True,
                    "action": "disable",
                    "inputs": {"plugin_name": plugin_name},
                    "reason": "inverse enable by disabling the same plugin",
                }
            )
            return rollback
        if action == "disable" and plugin_name:
            rollback.update(
                {
                    "available": True,
                    "action": "enable",
                    "inputs": {"plugin_name": plugin_name},
                    "reason": "inverse disable by enabling the same plugin",
                }
            )
            return rollback
        if action == "reload":
            rollback.update(
                {
                    "available": True,
                    "action": "reload",
                    "inputs": {},
                    "reason": "re-apply runtime discovery reload",
                }
            )
            return rollback
        if action == "install":
            added_plugins = list((provenance or {}).get("added") or [])
            if added_plugins:
                rollback.update(
                    {
                        "available": True,
                        "action": "uninstall",
                        "inputs": {"plugin_names": added_plugins},
                        "reason": "uninstall newly added plugins",
                    }
                )
            else:
                rollback["reason"] = "no added plugins detected for rollback"
            return rollback
        if action == "uninstall":
            resolved_requirement = requirement or self._resolve_requirement_for_plugin(
                before_snapshot,
                plugin_name,
            )
            if resolved_requirement:
                rollback.update(
                    {
                        "available": True,
                        "action": "install",
                        "inputs": {"requirement": resolved_requirement},
                        "reason": "reinstall plugin requirement",
                    }
                )
            else:
                rollback["reason"] = "missing package requirement for reinstall rollback"
            return rollback
        rollback["reason"] = "no rollback mapping for action"
        return rollback

    @staticmethod
    def _resolve_requirement_for_plugin(
        snapshot: list[Dict[str, Any]],
        plugin_name: Optional[str],
    ) -> Optional[str]:
        if not plugin_name:
            return None
        plugin = next(
            (
                item
                for item in snapshot
                if str(item.get("name", "")).strip() == str(plugin_name).strip()
            ),
            None,
        )
        if not plugin:
            return None
        requirement = plugin.get("requirement")
        if isinstance(requirement, str) and requirement.strip():
            return requirement.strip()
        package = plugin.get("package")
        version = plugin.get("version")
        if isinstance(package, str) and package.strip():
            package_name = package.strip()
            if isinstance(version, str) and version.strip():
                return f"{package_name}=={version.strip()}"
            return package_name
        return None

    @staticmethod
    def _build_trace_id() -> str:
        return f"plugin_manager:{uuid4().hex}"

    def _start_mutation_transaction(
        self,
        *,
        trace_id: str,
        action: str,
        plugin_name: Optional[str],
        requirement: Optional[str],
    ) -> MutationTransaction:
        return MutationTransaction(
            source=TOOL_NAME,
            action=action,
            trace_id=trace_id,
            tenant_id=self._tenant_id,
            project_id=self._project_id,
            plugin_name=plugin_name,
            requirement=requirement,
        )

    @staticmethod
    def _as_bool(value: Any) -> bool:  # noqa: ANN401
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

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
    def _error_response(message: str, **extra: Any) -> Dict[str, Any]:  # noqa: ANN401
        return {
            "title": "Plugin Manager Failed",
            "output": f"Error: {message}",
            "metadata": {
                "action": "error",
                "error": message,
                **extra,
            },
        }


def _serialize_diagnostic(diagnostic: Any) -> Dict[str, Any]:  # noqa: ANN401
    return {
        "plugin_name": diagnostic.plugin_name,
        "code": diagnostic.code,
        "message": diagnostic.message,
        "level": diagnostic.level,
    }
