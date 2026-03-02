"""Tool for plugin runtime install/list/enable/disable/reload operations."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from src.infrastructure.agent.plugins.manager import get_plugin_runtime_manager
from src.infrastructure.agent.plugins.reload_planner import build_plugin_reload_plan
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.mutation_ledger import MutationLedger, get_mutation_ledger
from src.infrastructure.agent.tools.mutation_transaction import (
    MutationTransaction,
    MutationTransactionStatus,
)
from src.infrastructure.agent.tools.result import ToolResult
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



def _serialize_diagnostic(diagnostic: Any) -> dict[str, Any]:
    return {
        "plugin_name": diagnostic.plugin_name,
        "code": diagnostic.code,
        "message": diagnostic.message,
        "level": diagnostic.level,
    }


# ---------------------------------------------------------------------------
# @tool_define migration  (functional equivalent of PluginManagerTool)
# ---------------------------------------------------------------------------


# Module-level DI state --------------------------------------------------

_pm_tenant_id: str | None = None
_pm_project_id: str | None = None
_pm_mutation_ledger: MutationLedger | None = None
_pm_loop_threshold: int = 10
_pm_loop_window_seconds: int = 120


def configure_plugin_manager(
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    mutation_ledger: MutationLedger | None = None,
    mutation_loop_threshold: int = 10,
    mutation_loop_window_seconds: int = 120,
) -> None:
    """Configure module-level state for the plugin_manager tool."""
    global _pm_tenant_id, _pm_project_id, _pm_mutation_ledger
    global _pm_loop_threshold, _pm_loop_window_seconds
    _pm_tenant_id = tenant_id
    _pm_project_id = project_id
    _pm_mutation_ledger = mutation_ledger or get_mutation_ledger()
    _pm_loop_threshold = max(1, int(mutation_loop_threshold))
    _pm_loop_window_seconds = max(1, int(mutation_loop_window_seconds))


def _pm_get_ledger() -> MutationLedger:
    """Return the configured ledger, initialising lazily if needed."""
    global _pm_mutation_ledger
    if _pm_mutation_ledger is None:
        _pm_mutation_ledger = get_mutation_ledger()
    return _pm_mutation_ledger


# Standalone equivalents of class-private static helpers.
# Inlined to avoid both ruff B009 (getattr with constant) and
# pyright reportPrivateUsage.  The original class code is NOT modified.


def _pm_resolve_requirement_for_plugin(
    before_snapshot: list[Any],
    plugin_name: str | None,
) -> str | None:
    """Resolve a pip requirement string for *plugin_name* from a snapshot."""
    if not plugin_name:
        return None
    plugin = next(
        (
            item
            for item in before_snapshot
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


def _pm_build_provenance_summary(
    *,
    before_snapshot: list[Any],
    after_snapshot: list[Any],
) -> dict[str, Any]:
    """Build a before/after provenance dict from plugin snapshots."""
    before_by_name: dict[str, Any] = {
        item["name"]: item for item in before_snapshot
    }
    after_by_name: dict[str, Any] = {
        item["name"]: item for item in after_snapshot
    }
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


def _pm_format_plugin_list(plugins: list[Any]) -> str:
    """Format a plugin inventory list into a human-readable string."""
    if not plugins:
        return "No plugins discovered."
    lines: list[str] = []
    for item in plugins:
        source = item.get("source") or "unknown"
        package = item.get("package") or "-"
        enabled = "enabled" if item.get("enabled", True) else "disabled"
        lines.append(
            f"- {item['name']} [{enabled}] source={source} package={package}",
        )
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Mutation lifecycle helpers (module-level, shared by all action handlers)
# ---------------------------------------------------------------------------


def _pm_init_mutation_context(
    manager: Any,
    action: str,
    dry_run: bool,
    plugin_name: str | None,
    requirement: str | None,
) -> _MutationContext:
    """Create and populate a _MutationContext for the given action."""
    ctx = _MutationContext(
        action=action,
        plugin_name=plugin_name,
        requirement=requirement,
        dry_run=dry_run,
        manager=manager,
    )
    ctx.before_snapshot = _pm_snapshot_plugin_inventory(manager)
    ctx.trace_id = f"plugin_manager:{uuid4().hex}"
    ctx.transaction = MutationTransaction(
        source=TOOL_NAME,
        action=action,
        trace_id=ctx.trace_id,
        tenant_id=_pm_tenant_id,
        project_id=_pm_project_id,
        plugin_name=plugin_name,
        requirement=requirement,
    )
    ctx.mutation_fingerprint = _pm_build_mutation_fingerprint(
        action=action, plugin_name=plugin_name, requirement=requirement,
    )
    ctx.mutation_guard = _pm_evaluate_mutation_guard(ctx.mutation_fingerprint)
    ctx.rollback = _pm_build_rollback_metadata(
        action=action,
        plugin_name=plugin_name,
        before_snapshot=ctx.before_snapshot,
        requirement=requirement,
    )
    return ctx


def _pm_snapshot_plugin_inventory(manager: Any) -> list[dict[str, Any]]:
    """Snapshot the current plugin inventory for provenance diffing."""
    plugins, _diagnostics = manager.list_plugins(tenant_id=_pm_tenant_id)
    snapshot: list[dict[str, Any]] = []
    for item in plugins:
        snapshot.append(
            {
                "name": str(item.get("name", "")),
                "source": item.get("source"),
                "package": item.get("package"),
                "version": item.get("version"),
                "requirement": item.get("requirement"),
                "kind": item.get("kind"),
                "manifest_id": item.get("manifest_id"),
                "providers": list(item.get("providers") or []),
                "skills": list(item.get("skills") or []),
                "enabled": bool(item.get("enabled", True)),
                "discovered": bool(item.get("discovered", True)),
            }
        )
    snapshot.sort(key=lambda p: p["name"])
    return snapshot


def _pm_build_mutation_fingerprint(
    *,
    action: str,
    plugin_name: str | None,
    requirement: str | None = None,
) -> str | None:
    """Build a deterministic fingerprint for loop-guard matching."""
    payload: dict[str, Any] = {
        "action": action,
        "plugin_name": plugin_name,
        "requirement": requirement,
        "tenant_id": _pm_tenant_id,
        "project_id": _pm_project_id,
    }
    normalized = {
        k: v for k, v in payload.items() if v is not None and v != ""
    }
    return build_mutation_fingerprint(TOOL_NAME, normalized)


def _pm_evaluate_mutation_guard(
    mutation_fingerprint: str | None,
) -> dict[str, Any]:
    """Evaluate the loop-guard for the given fingerprint."""
    guard: dict[str, Any] = {
        "blocked": False,
        "recent_count": 0,
        "threshold": _pm_loop_threshold,
        "window_seconds": _pm_loop_window_seconds,
        "last_seen_at": None,
    }
    if not mutation_fingerprint:
        return guard
    evaluated = _pm_get_ledger().evaluate_loop_guard(
        mutation_fingerprint,
        threshold=_pm_loop_threshold,
        window_seconds=_pm_loop_window_seconds,
    )
    guard.update(evaluated)
    return guard


def _pm_record_mutation_audit(
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
    """Append a mutation audit record to the ledger and return it."""
    payload: dict[str, Any] = {
        "trace_id": trace_id,
        "source": TOOL_NAME,
        "tenant_id": _pm_tenant_id,
        "project_id": _pm_project_id,
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
    return _pm_get_ledger().append(payload)


def _pm_build_reload_plan(
    *,
    manager: Any,
    action: str,
    plugin_name: str | None,
    dry_run: bool,
    reason: str | None,
) -> dict[str, Any]:
    """Build a reload plan dict for the current plugin inventory."""
    plugins, diagnostics = manager.list_plugins(tenant_id=_pm_tenant_id)
    return build_plugin_reload_plan(
        action=action,
        dry_run=dry_run,
        plugin_name=plugin_name,
        tenant_id=_pm_tenant_id,
        plugins=plugins,
        diagnostics=diagnostics,
        reason=reason,
    )


def _pm_build_reload_plan_for_ctx(
    mctx: _MutationContext,
    reason: str,
) -> None:
    """Populate mctx.reload_plan in-place."""
    mctx.reload_plan = _pm_build_reload_plan(
        manager=mctx.manager,
        action=mctx.action,
        plugin_name=mctx.plugin_name,
        dry_run=mctx.dry_run,
        reason=reason,
    )


def _pm_build_rollback_metadata(
    *,
    action: str,
    plugin_name: str | None,
    before_snapshot: list[dict[str, Any]],
    requirement: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build rollback metadata for the given action."""
    rollback: dict[str, Any] = {
        "source_action": action,
        "available": False,
        "action": None,
        "inputs": {},
        "reason": "",
    }
    if action == "enable" and plugin_name:
        rollback.update({
            "available": True,
            "action": "disable",
            "inputs": {"plugin_name": plugin_name},
            "reason": "inverse enable by disabling the same plugin",
        })
        return rollback
    if action == "disable" and plugin_name:
        rollback.update({
            "available": True,
            "action": "enable",
            "inputs": {"plugin_name": plugin_name},
            "reason": "inverse disable by enabling the same plugin",
        })
        return rollback
    if action == "reload":
        rollback.update({
            "available": True,
            "action": "reload",
            "inputs": {},
            "reason": "re-apply runtime discovery reload",
        })
        return rollback
    if action == "install":
        added_plugins = list((provenance or {}).get("added") or [])
        if added_plugins:
            rollback.update({
                "available": True,
                "action": "uninstall",
                "inputs": {"plugin_names": added_plugins},
                "reason": "uninstall newly added plugins",
            })
        else:
            rollback["reason"] = "no added plugins detected for rollback"
        return rollback
    if action == "uninstall":
        resolved = requirement or _pm_resolve_requirement_for_plugin(
            before_snapshot, plugin_name,
        )
        if resolved:
            rollback.update({
                "available": True,
                "action": "install",
                "inputs": {"requirement": resolved},
                "reason": "reinstall plugin requirement",
            })
        else:
            rollback["reason"] = "missing package requirement for reinstall rollback"
        return rollback
    rollback["reason"] = "no rollback mapping for action"
    return rollback


def _pm_run_lifecycle(
    *,
    action: str,
    plugin_name: str | None,
    trace_id: str,
    mutation_fingerprint: str | None,
    reload_plan: dict[str, Any],
    rollback: dict[str, Any],
) -> dict[str, Any]:
    """Run SelfModifyingLifecycleOrchestrator.run_post_change."""
    lifecycle = SelfModifyingLifecycleOrchestrator.run_post_change(
        source=TOOL_NAME,
        tenant_id=_pm_tenant_id,
        project_id=_pm_project_id,
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
        _pm_tenant_id,
        _pm_project_id,
        lifecycle.get("cache_invalidation", {}),
    )
    return lifecycle


# ---------------------------------------------------------------------------
# Guard / dry-run / finalize / failure — shared mutation-phase helpers
# ---------------------------------------------------------------------------


def _pm_check_guard_blocked(
    mctx: _MutationContext,
) -> ToolResult | None:
    """Return a ToolResult if the mutation is blocked, else None."""
    if not (mctx.mutation_guard["blocked"] and not mctx.dry_run):
        return None
    assert mctx.transaction is not None
    mctx.transaction.add_phase(
        MutationTransactionStatus.BLOCKED,
        details={"mutation_guard": mctx.mutation_guard},
    )
    mctx.mutation_audit = _pm_record_mutation_audit(
        trace_id=mctx.trace_id,
        action=mctx.action,
        plugin_name=mctx.plugin_name,
        requirement=mctx.requirement,
        mutation_fingerprint=mctx.mutation_fingerprint,
        status="blocked",
        dry_run=False,
        rollback=mctx.rollback,
        message="mutation blocked by loop guard",
        details={
            "mutation_guard": mctx.mutation_guard,
            "mutation_transaction": mctx.transaction.to_dict(),
        },
    )
    extra: dict[str, Any] = {
        "action": mctx.action,
        "trace_id": mctx.trace_id,
        "mutation_fingerprint": mctx.mutation_fingerprint,
        "mutation_guard": mctx.mutation_guard,
        "mutation_audit": mctx.mutation_audit,
        "rollback": mctx.rollback,
        "mutation_transaction": mctx.transaction.to_dict(),
    }
    if mctx.plugin_name:
        extra["plugin_name"] = mctx.plugin_name
    if mctx.requirement:
        extra["requirement"] = mctx.requirement
    return ToolResult(
        output="Error: mutation blocked by loop guard",
        is_error=True,
        title="Plugin Manager Failed",
        metadata={"action": "error", "error": "mutation blocked by loop guard", **extra},
    )


def _pm_handle_dry_run(
    mctx: _MutationContext,
    title: str,
    output: str,
) -> ToolResult:
    """Build a ToolResult for a dry-run mutation."""
    assert mctx.transaction is not None
    mctx.transaction.add_phase(
        MutationTransactionStatus.DRY_RUN,
        details={"reload_plan": mctx.reload_plan, "rollback": mctx.rollback},
    )
    mctx.mutation_audit = _pm_record_mutation_audit(
        trace_id=mctx.trace_id,
        action=mctx.action,
        plugin_name=mctx.plugin_name,
        requirement=mctx.requirement,
        mutation_fingerprint=mctx.mutation_fingerprint,
        status="dry_run",
        dry_run=True,
        rollback=mctx.rollback,
        message="dry_run",
        details={
            "reload_plan": mctx.reload_plan,
            "mutation_transaction": mctx.transaction.to_dict(),
        },
    )
    metadata: dict[str, Any] = {
        "action": mctx.action,
        "dry_run": True,
        "trace_id": mctx.trace_id,
        "mutation_fingerprint": mctx.mutation_fingerprint,
        "mutation_guard": mctx.mutation_guard,
        "mutation_audit": mctx.mutation_audit,
        "reload_plan": mctx.reload_plan,
        "rollback": mctx.rollback,
        "mutation_transaction": mctx.transaction.to_dict(),
        "provenance_preview": {"before_count": len(mctx.before_snapshot)},
    }
    if mctx.plugin_name:
        metadata["plugin_name"] = mctx.plugin_name
    if mctx.requirement:
        metadata["requirement"] = mctx.requirement
    return ToolResult(output=output, title=title, metadata=metadata)


async def _pm_finalize_mutation(
    tool_ctx: ToolContext,
    mctx: _MutationContext,
    result_details: dict[str, Any],
    title: str,
    output: str,
    success_message: str,
) -> ToolResult:
    """Complete a successful mutation: provenance, lifecycle, event, result."""
    assert mctx.transaction is not None
    after_snapshot = _pm_snapshot_plugin_inventory(mctx.manager)
    provenance = _pm_build_provenance_summary(
        before_snapshot=mctx.before_snapshot,
        after_snapshot=after_snapshot,
    )
    mctx.rollback = _pm_build_rollback_metadata(
        action=mctx.action,
        plugin_name=mctx.plugin_name,
        before_snapshot=mctx.before_snapshot,
        requirement=mctx.requirement,
        provenance=provenance,
    )
    mctx.mutation_audit = _pm_record_mutation_audit(
        trace_id=mctx.trace_id,
        action=mctx.action,
        plugin_name=mctx.plugin_name,
        requirement=mctx.requirement,
        mutation_fingerprint=mctx.mutation_fingerprint,
        status="applied",
        dry_run=False,
        rollback=mctx.rollback,
        message=success_message,
        details={
            "provenance": provenance,
            "mutation_transaction": mctx.transaction.to_dict(),
        },
    )
    details = dict(result_details)
    details["provenance"] = provenance
    details["mutation_guard"] = mctx.mutation_guard
    details["mutation_audit"] = mctx.mutation_audit
    details["rollback"] = mctx.rollback

    lifecycle = _pm_run_lifecycle(
        action=mctx.action,
        plugin_name=mctx.plugin_name,
        trace_id=mctx.trace_id,
        mutation_fingerprint=mctx.mutation_fingerprint,
        reload_plan=mctx.reload_plan,
        rollback=mctx.rollback,
    )
    mctx.transaction.add_phase(
        MutationTransactionStatus.APPLIED,
        details={"provenance": provenance},
    )
    mctx.transaction.add_phase(
        MutationTransactionStatus.VERIFIED,
        details={"probe": lifecycle.get("probe", {})},
    )
    details["mutation_transaction"] = mctx.transaction.to_dict()

    # Emit toolset_changed event via ctx.emit (replaces _pending_events)
    await tool_ctx.emit({
        "type": "toolset_changed",
        "data": {
            "source": TOOL_NAME,
            "tenant_id": _pm_tenant_id,
            "project_id": _pm_project_id,
            "action": mctx.action,
            "plugin_name": mctx.plugin_name,
            "trace_id": mctx.trace_id,
            "mutation_fingerprint": mctx.mutation_fingerprint,
            "reload_plan": mctx.reload_plan,
            "details": details,
            "lifecycle": lifecycle,
        },
        "timestamp": datetime.now(UTC).isoformat(),
    })

    metadata: dict[str, Any] = {
        "action": mctx.action,
        "result": details,
        "lifecycle": lifecycle,
        "trace_id": mctx.trace_id,
        "mutation_fingerprint": mctx.mutation_fingerprint,
        "mutation_guard": mctx.mutation_guard,
        "mutation_audit": mctx.mutation_audit,
        "reload_plan": mctx.reload_plan,
        "rollback": mctx.rollback,
        "provenance": provenance,
        "mutation_transaction": mctx.transaction.to_dict(),
    }
    if mctx.plugin_name:
        metadata["plugin_name"] = mctx.plugin_name
    if mctx.requirement:
        metadata["requirement"] = mctx.requirement
    return ToolResult(output=output, title=title, metadata=metadata)


def _pm_handle_action_failure(
    mctx: _MutationContext,
    result: dict[str, Any],
    fail_message: str,
) -> ToolResult:
    """Build a ToolResult for a failed mutation action."""
    assert mctx.transaction is not None
    mctx.transaction.add_phase(
        MutationTransactionStatus.FAILED,
        details={"result": result},
    )
    mctx.mutation_audit = _pm_record_mutation_audit(
        trace_id=mctx.trace_id,
        action=mctx.action,
        plugin_name=mctx.plugin_name,
        requirement=mctx.requirement,
        mutation_fingerprint=mctx.mutation_fingerprint,
        status="failed",
        dry_run=False,
        rollback=mctx.rollback,
        message=fail_message,
        details={
            "result": result,
            "mutation_transaction": mctx.transaction.to_dict(),
        },
    )
    extra: dict[str, Any] = {
        "action": mctx.action,
        "details": result,
        "trace_id": mctx.trace_id,
        "mutation_fingerprint": mctx.mutation_fingerprint,
        "mutation_guard": mctx.mutation_guard,
        "mutation_audit": mctx.mutation_audit,
        "rollback": mctx.rollback,
        "mutation_transaction": mctx.transaction.to_dict(),
    }
    if mctx.plugin_name:
        extra["plugin_name"] = mctx.plugin_name
    if mctx.requirement:
        extra["requirement"] = mctx.requirement
    return ToolResult(
        output=f"Error: {fail_message}",
        is_error=True,
        title="Plugin Manager Failed",
        metadata={"action": "error", "error": fail_message, **extra},
    )


# ---------------------------------------------------------------------------
# Per-action handler functions
# ---------------------------------------------------------------------------


def _pm_handle_list(ctx: ToolContext) -> ToolResult:
    """Handle the 'list' action: return current plugin inventory."""
    _ = ctx  # unused but kept for uniform signature
    manager = get_plugin_runtime_manager()
    plugins, diagnostics = manager.list_plugins(tenant_id=_pm_tenant_id)
    return ToolResult(
        output=_pm_format_plugin_list(plugins),
        title="Plugin runtime status",
        metadata={
            "action": "list",
            "plugins": plugins,
            "diagnostics": [_serialize_diagnostic(d) for d in diagnostics],
        },
    )


async def _pm_handle_install(
    ctx: ToolContext,
    requirement: str,
    dry_run: bool,
) -> ToolResult:
    """Handle the 'install' action."""
    if not requirement:
        return ToolResult(
            output="Error: requirement is required for install action",
            is_error=True,
            title="Plugin Manager Failed",
            metadata={
                "action": "error",
                "error": "requirement is required for install action",
            },
        )
    manager = get_plugin_runtime_manager()
    mctx = _pm_init_mutation_context(manager, "install", dry_run, None, requirement)

    blocked = _pm_check_guard_blocked(mctx)
    if blocked:
        return blocked

    _pm_build_reload_plan_for_ctx(mctx, f"install requirement {requirement}")

    if dry_run:
        return _pm_handle_dry_run(
            mctx,
            title="Plugin install plan",
            output=f"[dry-run] Would install requirement: {requirement}",
        )

    result = await manager.install_plugin(requirement)
    if not result.get("success"):
        return _pm_handle_action_failure(mctx, result, "plugin install failed")

    new_plugins = ", ".join(result.get("new_plugins", [])) or "(none)"
    return await _pm_finalize_mutation(
        ctx,
        mctx,
        result_details=dict(result),
        title="Plugin installed",
        output=f"Installed requirement: {requirement}\nDiscovered plugins: {new_plugins}",
        success_message="plugin installed",
    )


async def _pm_handle_enable_disable(
    ctx: ToolContext,
    action: str,
    plugin_name: str,
    dry_run: bool,
) -> ToolResult:
    """Handle the 'enable' or 'disable' action."""
    if not plugin_name:
        return ToolResult(
            output="Error: plugin_name is required for enable/disable actions",
            is_error=True,
            title="Plugin Manager Failed",
            metadata={
                "action": "error",
                "error": "plugin_name is required for enable/disable actions",
            },
        )
    manager = get_plugin_runtime_manager()
    enabled = action == "enable"
    mctx = _pm_init_mutation_context(manager, action, dry_run, plugin_name, None)

    blocked = _pm_check_guard_blocked(mctx)
    if blocked:
        return blocked

    _pm_build_reload_plan_for_ctx(mctx, f"{action} plugin {plugin_name}")

    if dry_run:
        return _pm_handle_dry_run(
            mctx,
            title=f"Plugin {action} plan",
            output=f"[dry-run] Would set plugin '{plugin_name}' to enabled={enabled}.",
        )

    diagnostics = await manager.set_plugin_enabled(
        plugin_name, enabled=enabled, tenant_id=_pm_tenant_id,
    )
    result_details: dict[str, Any] = {
        "diagnostics": [_serialize_diagnostic(d) for d in diagnostics],
    }
    return await _pm_finalize_mutation(
        ctx,
        mctx,
        result_details=result_details,
        title=f"Plugin {action}d",
        output=f"Plugin '{plugin_name}' is now {'enabled' if enabled else 'disabled'}.",
        success_message=f"plugin {action}d",
    )


async def _pm_handle_uninstall(
    ctx: ToolContext,
    plugin_name: str,
    dry_run: bool,
) -> ToolResult:
    """Handle the 'uninstall' action."""
    if not plugin_name:
        return ToolResult(
            output="Error: plugin_name is required for uninstall action",
            is_error=True,
            title="Plugin Manager Failed",
            metadata={
                "action": "error",
                "error": "plugin_name is required for uninstall action",
            },
        )
    manager = get_plugin_runtime_manager()
    mctx = _pm_init_mutation_context(manager, "uninstall", dry_run, plugin_name, None)

    blocked = _pm_check_guard_blocked(mctx)
    if blocked:
        return blocked

    _pm_build_reload_plan_for_ctx(mctx, f"uninstall plugin {plugin_name}")

    if dry_run:
        return _pm_handle_dry_run(
            mctx,
            title="Plugin uninstall plan",
            output=f"[dry-run] Would uninstall plugin '{plugin_name}'.",
        )

    result = await manager.uninstall_plugin(plugin_name)
    if not result.get("success"):
        return _pm_handle_action_failure(mctx, result, "plugin uninstall failed")

    return await _pm_finalize_mutation(
        ctx,
        mctx,
        result_details=dict(result),
        title="Plugin uninstalled",
        output=f"Uninstalled plugin '{plugin_name}'",
        success_message="plugin uninstalled",
    )


async def _pm_handle_reload(
    ctx: ToolContext,
    dry_run: bool,
) -> ToolResult:
    """Handle the 'reload' action."""
    manager = get_plugin_runtime_manager()
    mctx = _pm_init_mutation_context(manager, "reload", dry_run, None, None)

    blocked = _pm_check_guard_blocked(mctx)
    if blocked:
        return blocked

    _pm_build_reload_plan_for_ctx(mctx, "manual reload request")

    if dry_run:
        return _pm_handle_dry_run(
            mctx,
            title="Plugin reload plan",
            output="[dry-run] Plugin runtime reload plan generated.",
        )

    diagnostics = await manager.reload()
    result_details: dict[str, Any] = {
        "diagnostics": [_serialize_diagnostic(d) for d in diagnostics],
    }
    return await _pm_finalize_mutation(
        ctx,
        mctx,
        result_details=result_details,
        title="Plugin runtime reloaded",
        output="Plugin runtime discovery and registry reload completed.",
        success_message="plugin runtime reloaded",
    )


# ---------------------------------------------------------------------------
# @tool_define entry point
# ---------------------------------------------------------------------------


def _pm_as_bool(value: Any) -> bool:
    """Coerce a value to bool, matching PluginManagerTool._as_bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


@tool_define(
    name="plugin_manager",
    description=(
        "Manage runtime plugins with list/install/enable/disable/reload actions. "
        "Plugins can be discovered from local folders "
        "`.memstack/plugins/<name>/plugin.py` "
        "or Python entry points in group 'memstack.agent_plugins'. "
        "Use install to pip-install a package, then reload or enable specific "
        "plugin names."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "install", "enable", "disable", "reload", "uninstall"],
                "description": "Plugin management action. Default: list",
            },
            "requirement": {
                "type": "string",
                "description": (
                    "Package requirement for install action "
                    "(e.g. my-plugin-package==1.0.0)"
                ),
            },
            "plugin_name": {
                "type": "string",
                "description": "Plugin name for enable/disable/uninstall actions",
            },
            "dry_run": {
                "type": "boolean",
                "description": (
                    "When true, return mutation/reload plan without applying changes."
                ),
            },
        },
        "required": [],
    },
    permission="plugin_manager",
    category="plugin",
    tags=frozenset({"plugin", "mutation"}),
)
async def plugin_manager_tool(
    ctx: ToolContext,
    *,
    action: str = "list",
    requirement: str = "",
    plugin_name: str = "",
    dry_run: bool | str = False,
) -> ToolResult:
    """Manage runtime plugins (functional @tool_define equivalent)."""
    action = str(action).strip().lower() or "list"
    dry_run_bool = _pm_as_bool(dry_run)
    requirement = str(requirement).strip()
    plugin_name = str(plugin_name).strip()

    if action == "list":
        return _pm_handle_list(ctx)

    if action == "install":
        return await _pm_handle_install(ctx, requirement, dry_run_bool)

    if action in {"enable", "disable"}:
        return await _pm_handle_enable_disable(
            ctx, action, plugin_name, dry_run_bool,
        )

    if action == "uninstall":
        return await _pm_handle_uninstall(ctx, plugin_name, dry_run_bool)

    if action == "reload":
        return await _pm_handle_reload(ctx, dry_run_bool)

    return ToolResult(
        output=f"Error: Unsupported action: {action}",
        is_error=True,
        title="Plugin Manager Failed",
        metadata={"action": "error", "error": f"Unsupported action: {action}"},
    )
