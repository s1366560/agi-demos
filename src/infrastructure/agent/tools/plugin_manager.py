"""Tool for plugin runtime install/list/enable/disable/reload operations."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
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


@dataclass
class _MutationContext:
    """Shared state accumulated during a mutation action."""

    action: str
    plugin_name: str | None
    requirement: str | None
    dry_run: bool
    manager: Any
    before_snapshot: list[dict[str, Any]] = field(default_factory=list)
    trace_id: str = ""
    transaction: MutationTransaction | None = None
    mutation_fingerprint: str | None = None
    mutation_guard: dict[str, Any] = field(default_factory=dict)
    rollback: dict[str, Any] = field(default_factory=dict)
    reload_plan: dict[str, Any] = field(default_factory=dict)
    mutation_audit: dict[str, Any] = field(default_factory=dict)


class PluginManagerTool(AgentTool):
    """Manage runtime plugins installed via Python package entry points."""

    def __init__(
        self,
        tenant_id: str | None,
        project_id: str | None,
        *,
        mutation_ledger: MutationLedger | None = None,
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

    def get_parameters_schema(self) -> dict[str, Any]:
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

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Execute plugin management operation."""
        action = str(kwargs.get("action", "list")).strip().lower() or "list"
        dry_run = self._as_bool(kwargs.get("dry_run", False))
        manager = get_plugin_runtime_manager()

        if action == "list":
            return self._handle_list(manager)

        handler = self._get_mutation_handler(action)
        if handler is None:
            return self._error_response(f"Unsupported action: {action}")

        return await handler(manager, dry_run, kwargs)

    def _handle_list(self, manager: Any) -> dict[str, Any]:
        plugins, diagnostics = manager.list_plugins(tenant_id=self._tenant_id)
        return {
            "title": "Plugin runtime status",
            "output": self._format_plugin_list(plugins),
            "metadata": {
                "action": "list",
                "plugins": plugins,
                "diagnostics": [_serialize_diagnostic(item) for item in diagnostics],
            },
        }

    def _get_mutation_handler(self, action: str) -> Any:
        handlers: dict[str, Any] = {
            "install": self._handle_install,
            "enable": self._handle_enable_disable,
            "disable": self._handle_enable_disable,
            "uninstall": self._handle_uninstall,
            "reload": self._handle_reload,
        }
        return handlers.get(action)

    # ------------------------------------------------------------------
    # Mutation lifecycle helpers (shared across all mutation actions)
    # ------------------------------------------------------------------

    def _init_mutation_context(
        self,
        manager: Any,
        action: str,
        dry_run: bool,
        plugin_name: str | None,
        requirement: str | None,
    ) -> _MutationContext:
        ctx = _MutationContext(
            action=action,
            plugin_name=plugin_name,
            requirement=requirement,
            dry_run=dry_run,
            manager=manager,
        )
        ctx.before_snapshot = self._snapshot_plugin_inventory(manager)
        ctx.trace_id = self._build_trace_id()
        ctx.transaction = self._start_mutation_transaction(
            trace_id=ctx.trace_id,
            action=action,
            plugin_name=plugin_name,
            requirement=requirement,
        )
        ctx.mutation_fingerprint = self._build_mutation_fingerprint(
            action=action,
            plugin_name=plugin_name,
            requirement=requirement,
        )
        ctx.mutation_guard = self._evaluate_mutation_guard(ctx.mutation_fingerprint)
        ctx.rollback = self._build_rollback_metadata(
            action=action,
            plugin_name=plugin_name,
            before_snapshot=ctx.before_snapshot,
            requirement=requirement,
        )
        return ctx

    def _check_guard_blocked(self, ctx: _MutationContext) -> dict[str, Any] | None:
        if not (ctx.mutation_guard["blocked"] and not ctx.dry_run):
            return None
        assert ctx.transaction is not None
        ctx.transaction.add_phase(
            MutationTransactionStatus.BLOCKED,
            details={"mutation_guard": ctx.mutation_guard},
        )
        ctx.mutation_audit = self._record_mutation_audit(
            trace_id=ctx.trace_id,
            action=ctx.action,
            plugin_name=ctx.plugin_name,
            requirement=ctx.requirement,
            mutation_fingerprint=ctx.mutation_fingerprint,
            status="blocked",
            dry_run=False,
            rollback=ctx.rollback,
            message="mutation blocked by loop guard",
            details={
                "mutation_guard": ctx.mutation_guard,
                "mutation_transaction": ctx.transaction.to_dict(),
            },
        )
        extra: dict[str, Any] = {
            "action": ctx.action,
            "trace_id": ctx.trace_id,
            "mutation_fingerprint": ctx.mutation_fingerprint,
            "mutation_guard": ctx.mutation_guard,
            "mutation_audit": ctx.mutation_audit,
            "rollback": ctx.rollback,
            "mutation_transaction": ctx.transaction.to_dict(),
        }
        if ctx.plugin_name:
            extra["plugin_name"] = ctx.plugin_name
        if ctx.requirement:
            extra["requirement"] = ctx.requirement
        return self._error_response("mutation blocked by loop guard", **extra)

    def _build_reload_plan_for_ctx(self, ctx: _MutationContext, reason: str) -> None:
        ctx.reload_plan = self._build_reload_plan(
            manager=ctx.manager,
            action=ctx.action,
            plugin_name=ctx.plugin_name,
            dry_run=ctx.dry_run,
            reason=reason,
        )

    def _handle_dry_run(
        self,
        ctx: _MutationContext,
        title: str,
        output: str,
    ) -> dict[str, Any]:
        assert ctx.transaction is not None
        ctx.transaction.add_phase(
            MutationTransactionStatus.DRY_RUN,
            details={"reload_plan": ctx.reload_plan, "rollback": ctx.rollback},
        )
        ctx.mutation_audit = self._record_mutation_audit(
            trace_id=ctx.trace_id,
            action=ctx.action,
            plugin_name=ctx.plugin_name,
            requirement=ctx.requirement,
            mutation_fingerprint=ctx.mutation_fingerprint,
            status="dry_run",
            dry_run=True,
            rollback=ctx.rollback,
            message="dry_run",
            details={
                "reload_plan": ctx.reload_plan,
                "mutation_transaction": ctx.transaction.to_dict(),
            },
        )
        metadata: dict[str, Any] = {
            "action": ctx.action,
            "dry_run": True,
            "trace_id": ctx.trace_id,
            "mutation_fingerprint": ctx.mutation_fingerprint,
            "mutation_guard": ctx.mutation_guard,
            "mutation_audit": ctx.mutation_audit,
            "reload_plan": ctx.reload_plan,
            "rollback": ctx.rollback,
            "mutation_transaction": ctx.transaction.to_dict(),
            "provenance_preview": {"before_count": len(ctx.before_snapshot)},
        }
        if ctx.plugin_name:
            metadata["plugin_name"] = ctx.plugin_name
        if ctx.requirement:
            metadata["requirement"] = ctx.requirement
        return {"title": title, "output": output, "metadata": metadata}

    def _finalize_mutation(
        self,
        ctx: _MutationContext,
        result_details: dict[str, Any],
        title: str,
        output: str,
        success_message: str,
    ) -> dict[str, Any]:
        assert ctx.transaction is not None
        after_snapshot = self._snapshot_plugin_inventory(ctx.manager)
        provenance = self._build_provenance_summary(
            before_snapshot=ctx.before_snapshot,
            after_snapshot=after_snapshot,
        )
        ctx.rollback = self._build_rollback_metadata(
            action=ctx.action,
            plugin_name=ctx.plugin_name,
            before_snapshot=ctx.before_snapshot,
            requirement=ctx.requirement,
            provenance=provenance,
        )
        ctx.mutation_audit = self._record_mutation_audit(
            trace_id=ctx.trace_id,
            action=ctx.action,
            plugin_name=ctx.plugin_name,
            requirement=ctx.requirement,
            mutation_fingerprint=ctx.mutation_fingerprint,
            status="applied",
            dry_run=False,
            rollback=ctx.rollback,
            message=success_message,
            details={
                "provenance": provenance,
                "mutation_transaction": ctx.transaction.to_dict(),
            },
        )
        details = dict(result_details)
        details["provenance"] = provenance
        details["mutation_guard"] = ctx.mutation_guard
        details["mutation_audit"] = ctx.mutation_audit
        details["rollback"] = ctx.rollback

        lifecycle = self._run_lifecycle(
            action=ctx.action,
            plugin_name=ctx.plugin_name,
            trace_id=ctx.trace_id,
            mutation_fingerprint=ctx.mutation_fingerprint,
            reload_plan=ctx.reload_plan,
            rollback=ctx.rollback,
        )
        ctx.transaction.add_phase(
            MutationTransactionStatus.APPLIED,
            details={"provenance": provenance},
        )
        ctx.transaction.add_phase(
            MutationTransactionStatus.VERIFIED,
            details={"probe": lifecycle.get("probe", {})},
        )
        details["mutation_transaction"] = ctx.transaction.to_dict()
        self._append_toolset_changed_event(
            action=ctx.action,
            plugin_name=ctx.plugin_name,
            lifecycle=lifecycle,
            trace_id=ctx.trace_id,
            mutation_fingerprint=ctx.mutation_fingerprint,
            reload_plan=ctx.reload_plan,
            details=details,
        )
        metadata: dict[str, Any] = {
            "action": ctx.action,
            "result": details,
            "lifecycle": lifecycle,
            "trace_id": ctx.trace_id,
            "mutation_fingerprint": ctx.mutation_fingerprint,
            "mutation_guard": ctx.mutation_guard,
            "mutation_audit": ctx.mutation_audit,
            "reload_plan": ctx.reload_plan,
            "rollback": ctx.rollback,
            "provenance": provenance,
            "mutation_transaction": ctx.transaction.to_dict(),
        }
        if ctx.plugin_name:
            metadata["plugin_name"] = ctx.plugin_name
        if ctx.requirement:
            metadata["requirement"] = ctx.requirement
        return {"title": title, "output": output, "metadata": metadata}

    def _handle_action_failure(
        self,
        ctx: _MutationContext,
        result: dict[str, Any],
        fail_message: str,
    ) -> dict[str, Any]:
        assert ctx.transaction is not None
        ctx.transaction.add_phase(
            MutationTransactionStatus.FAILED,
            details={"result": result},
        )
        ctx.mutation_audit = self._record_mutation_audit(
            trace_id=ctx.trace_id,
            action=ctx.action,
            plugin_name=ctx.plugin_name,
            requirement=ctx.requirement,
            mutation_fingerprint=ctx.mutation_fingerprint,
            status="failed",
            dry_run=False,
            rollback=ctx.rollback,
            message=fail_message,
            details={
                "result": result,
                "mutation_transaction": ctx.transaction.to_dict(),
            },
        )
        extra: dict[str, Any] = {
            "action": ctx.action,
            "details": result,
            "trace_id": ctx.trace_id,
            "mutation_fingerprint": ctx.mutation_fingerprint,
            "mutation_guard": ctx.mutation_guard,
            "mutation_audit": ctx.mutation_audit,
            "rollback": ctx.rollback,
            "mutation_transaction": ctx.transaction.to_dict(),
        }
        if ctx.plugin_name:
            extra["plugin_name"] = ctx.plugin_name
        if ctx.requirement:
            extra["requirement"] = ctx.requirement
        return self._error_response(fail_message, **extra)

    # ------------------------------------------------------------------
    # Per-action handlers
    # ------------------------------------------------------------------

    async def _handle_install(
        self, manager: Any, dry_run: bool, kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        requirement = str(kwargs.get("requirement", "")).strip()
        if not requirement:
            return self._error_response("requirement is required for install action")

        ctx = self._init_mutation_context(manager, "install", dry_run, None, requirement)

        blocked = self._check_guard_blocked(ctx)
        if blocked:
            return blocked

        self._build_reload_plan_for_ctx(ctx, f"install requirement {requirement}")

        if dry_run:
            return self._handle_dry_run(
                ctx,
                title="Plugin install plan",
                output=f"[dry-run] Would install requirement: {requirement}",
            )

        result = await manager.install_plugin(requirement)
        if not result.get("success"):
            return self._handle_action_failure(ctx, result, "plugin install failed")

        new_plugins = ", ".join(result.get("new_plugins", [])) or "(none)"
        return self._finalize_mutation(
            ctx,
            result_details=dict(result),
            title="Plugin installed",
            output=f"Installed requirement: {requirement}\nDiscovered plugins: {new_plugins}",
            success_message="plugin installed",
        )

    async def _handle_enable_disable(
        self, manager: Any, dry_run: bool, kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        action = str(kwargs.get("action", "enable")).strip().lower()
        plugin_name = str(kwargs.get("plugin_name", "")).strip()
        if not plugin_name:
            return self._error_response("plugin_name is required for enable/disable actions")

        enabled = action == "enable"
        ctx = self._init_mutation_context(manager, action, dry_run, plugin_name, None)

        blocked = self._check_guard_blocked(ctx)
        if blocked:
            return blocked

        self._build_reload_plan_for_ctx(ctx, f"{action} plugin {plugin_name}")

        if dry_run:
            return self._handle_dry_run(
                ctx,
                title=f"Plugin {action} plan",
                output=f"[dry-run] Would set plugin '{plugin_name}' to enabled={enabled}.",
            )

        diagnostics = await manager.set_plugin_enabled(
            plugin_name, enabled=enabled, tenant_id=self._tenant_id
        )
        result_details = {
            "diagnostics": [_serialize_diagnostic(item) for item in diagnostics],
        }
        return self._finalize_mutation(
            ctx,
            result_details=result_details,
            title=f"Plugin {action}d",
            output=f"Plugin '{plugin_name}' is now {'enabled' if enabled else 'disabled'}.",
            success_message=f"plugin {action}d",
        )

    async def _handle_uninstall(
        self, manager: Any, dry_run: bool, kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        plugin_name = str(kwargs.get("plugin_name", "")).strip()
        if not plugin_name:
            return self._error_response("plugin_name is required for uninstall action")

        ctx = self._init_mutation_context(manager, "uninstall", dry_run, plugin_name, None)

        blocked = self._check_guard_blocked(ctx)
        if blocked:
            return blocked

        self._build_reload_plan_for_ctx(ctx, f"uninstall plugin {plugin_name}")

        if dry_run:
            return self._handle_dry_run(
                ctx,
                title="Plugin uninstall plan",
                output=f"[dry-run] Would uninstall plugin '{plugin_name}'.",
            )

        result = await manager.uninstall_plugin(plugin_name)
        if not result.get("success"):
            return self._handle_action_failure(ctx, result, "plugin uninstall failed")

        return self._finalize_mutation(
            ctx,
            result_details=dict(result),
            title="Plugin uninstalled",
            output=f"Uninstalled plugin '{plugin_name}'",
            success_message="plugin uninstalled",
        )

    async def _handle_reload(
        self, manager: Any, dry_run: bool, _kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        ctx = self._init_mutation_context(manager, "reload", dry_run, None, None)

        blocked = self._check_guard_blocked(ctx)
        if blocked:
            return blocked

        self._build_reload_plan_for_ctx(ctx, "manual reload request")

        if dry_run:
            return self._handle_dry_run(
                ctx,
                title="Plugin reload plan",
                output="[dry-run] Plugin runtime reload plan generated.",
            )

        diagnostics = await manager.reload()
        result_details = {
            "diagnostics": [_serialize_diagnostic(item) for item in diagnostics],
        }
        return self._finalize_mutation(
            ctx,
            result_details=result_details,
            title="Plugin runtime reloaded",
            output="Plugin runtime discovery and registry reload completed.",
            success_message="plugin runtime reloaded",
        )

    # ------------------------------------------------------------------
    # Existing helpers (unchanged)
    # ------------------------------------------------------------------

    def _run_lifecycle(
        self,
        *,
        action: str,
        plugin_name: str | None,
        trace_id: str,
        mutation_fingerprint: str | None,
        reload_plan: dict[str, Any],
        rollback: dict[str, Any],
    ) -> dict[str, Any]:
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
        plugin_name: str | None,
        lifecycle: dict[str, Any],
        trace_id: str,
        mutation_fingerprint: str | None,
        reload_plan: dict[str, Any],
        details: dict[str, Any],
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
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def _build_reload_plan(
        self,
        *,
        manager: Any,
        action: str,
        plugin_name: str | None,
        dry_run: bool,
        reason: str | None,
    ) -> dict[str, Any]:
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
        plugin_name: str | None,
        requirement: str | None = None,
    ) -> str | None:
        payload: dict[str, Any] = {
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

    def _snapshot_plugin_inventory(self, manager: Any) -> list[dict[str, Any]]:
        plugins, _diagnostics = manager.list_plugins(tenant_id=self._tenant_id)
        snapshot: list[dict[str, Any]] = []
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
        before_snapshot: list[dict[str, Any]],
        after_snapshot: list[dict[str, Any]],
    ) -> dict[str, Any]:
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

    def _evaluate_mutation_guard(self, mutation_fingerprint: str | None) -> dict[str, Any]:
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
        plugin_name: str | None,
        requirement: str | None,
        mutation_fingerprint: str | None,
        status: str,
        dry_run: bool,
        rollback: dict[str, Any],
        message: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
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
        plugin_name: str | None,
        before_snapshot: list[dict[str, Any]],
        requirement: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rollback: dict[str, Any] = {
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
        snapshot: list[dict[str, Any]],
        plugin_name: str | None,
    ) -> str | None:
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
        plugin_name: str | None,
        requirement: str | None,
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
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def _format_plugin_list(plugins: list[dict[str, Any]]) -> str:
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
    def _error_response(message: str, **extra: Any) -> dict[str, Any]:
        return {
            "title": "Plugin Manager Failed",
            "output": f"Error: {message}",
            "metadata": {
                "action": "error",
                "error": message,
                **extra,
            },
        }


def _serialize_diagnostic(diagnostic: Any) -> dict[str, Any]:
    return {
        "plugin_name": diagnostic.plugin_name,
        "code": diagnostic.code,
        "message": diagnostic.message,
        "level": diagnostic.level,
    }
