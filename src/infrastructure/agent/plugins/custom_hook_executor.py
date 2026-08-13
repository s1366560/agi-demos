"""Runtime execution helpers for custom script/plugin hook handlers."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import inspect
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from src.domain.model.agent.tenant_agent_config import HookExecutorKind
from src.infrastructure.agent.plugins.hook_security_policy import (
    DEFAULT_CUSTOM_HOOK_TIMEOUT_SECONDS,
    HOST_ISOLATION_MODE,
    ISOLATION_MODE_SETTING_KEY,
    SANDBOX_ISOLATION_MODE,
    is_executor_allowed_for_family,
    normalize_hook_family,
    resolve_custom_hook_isolation_mode,
    resolve_custom_hook_timeout,
)
from src.infrastructure.agent.plugins.sandbox_runtime_hook_runner import (
    SandboxRuntimeHookRunner,
)
from src.infrastructure.agent.sandbox_resource_provider import get_sandbox_resource_port

if TYPE_CHECKING:
    from src.infrastructure.audit.audit_log_service import AuditLogService

REPO_ROOT = Path(__file__).resolve().parents[4]
ALLOWLISTED_SCRIPT_ROOTS = (REPO_ROOT / "src" / "infrastructure" / "agent" / "hooks" / "scripts",)
ALLOWLISTED_PLUGIN_ROOTS = (REPO_ROOT / "src" / "infrastructure" / "agent" / "plugins",)


def get_audit_service() -> AuditLogService:
    """Resolve the audit service without importing persistence models at module load time."""
    from src.infrastructure.audit.audit_log_service import (
        get_audit_service as resolve_audit_service,
    )

    return resolve_audit_service()


async def _log_custom_hook_audit(
    *,
    action: str,
    payload: dict[str, Any],
    executor_kind: str,
    source_ref: str,
    entrypoint: str,
    hook_family: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Record a custom runtime hook audit event without breaking execution."""
    try:
        await get_audit_service().log_event(
            action=action,
            resource_type="runtime_hook",
            resource_id=f"{executor_kind}:{source_ref}:{entrypoint}",
            actor="system",
            tenant_id=str(payload.get("tenant_id")) if payload.get("tenant_id") else None,
            details={
                "hook_name": payload.get("hook_identity", {}).get("hook_name"),
                "plugin_name": payload.get("hook_identity", {}).get("plugin_name"),
                "executor_kind": executor_kind,
                "source_ref": source_ref,
                "entrypoint": entrypoint,
                "hook_family": hook_family,
                **(details or {}),
            },
        )
    except Exception:
        # Audit logging must never break hook execution.
        return


def _resolve_source_path(
    *,
    executor_kind: str,
    source_ref: str,
) -> Path:
    normalized_source_ref = source_ref.strip()
    if not normalized_source_ref:
        raise ValueError("source_ref is required for custom runtime hook execution")
    candidate = Path(normalized_source_ref)
    if not candidate.is_absolute():
        candidate = (REPO_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()

    allowed_roots = (
        ALLOWLISTED_PLUGIN_ROOTS
        if executor_kind == HookExecutorKind.PLUGIN.value
        else ALLOWLISTED_SCRIPT_ROOTS
    )
    if not any(root in candidate.parents or candidate == root for root in allowed_roots):
        raise ValueError(f"Runtime hook source is outside the allowlist: {source_ref}")
    if not candidate.is_file():
        raise ValueError(f"Runtime hook source does not exist: {source_ref}")
    return candidate


def _requested_isolation_mode(payload: dict[str, Any]) -> str:
    """Best-effort extraction of requested isolation mode for audit details."""
    raw_settings = payload.get("hook_settings")
    if not isinstance(raw_settings, dict):
        return HOST_ISOLATION_MODE
    raw_mode = raw_settings.get(ISOLATION_MODE_SETTING_KEY, HOST_ISOLATION_MODE)
    return str(raw_mode).strip().lower() or HOST_ISOLATION_MODE


def _load_module_from_path(source_path: Path) -> ModuleType:
    digest = hashlib.sha256(str(source_path).encode("utf-8")).hexdigest()[:12]
    module_name = f"memstack_runtime_hook_{digest}_{int(source_path.stat().st_mtime_ns)}"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Unable to load runtime hook module from: {source_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def execute_custom_hook(  # noqa: C901, PLR0912, PLR0915
    *,
    executor_kind: str,
    source_ref: str,
    entrypoint: str,
    hook_family: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Execute custom runtime hook code from an allowlisted source."""
    normalized_kind = executor_kind.strip().lower()
    normalized_entrypoint = entrypoint.strip()
    normalized_hook_family = normalize_hook_family(hook_family)
    handler: Any | None = None
    if normalized_kind not in {
        HookExecutorKind.SCRIPT.value,
        HookExecutorKind.PLUGIN.value,
    }:
        await _log_custom_hook_audit(
            action="runtime_hook.custom_execution_failed",
            payload=payload,
            executor_kind=normalized_kind or executor_kind,
            source_ref=source_ref,
            entrypoint=normalized_entrypoint,
            hook_family=normalized_hook_family,
            details={
                "reason": "unsupported_executor_kind",
                "isolation_mode": _requested_isolation_mode(payload),
            },
        )
        raise ValueError(f"Unsupported custom hook executor kind: {executor_kind}")
    if not normalized_entrypoint:
        await _log_custom_hook_audit(
            action="runtime_hook.custom_execution_failed",
            payload=payload,
            executor_kind=normalized_kind,
            source_ref=source_ref,
            entrypoint=normalized_entrypoint,
            hook_family=normalized_hook_family,
            details={
                "reason": "missing_entrypoint",
                "isolation_mode": _requested_isolation_mode(payload),
            },
        )
        raise ValueError("entrypoint is required for custom runtime hook execution")
    if not is_executor_allowed_for_family(
        executor_kind=normalized_kind,
        hook_family=normalized_hook_family,
    ):
        await _log_custom_hook_audit(
            action="runtime_hook.custom_execution_blocked",
            payload=payload,
            executor_kind=normalized_kind,
            source_ref=source_ref,
            entrypoint=normalized_entrypoint,
            hook_family=normalized_hook_family,
            details={
                "reason": "executor_family_not_allowed",
                "isolation_mode": _requested_isolation_mode(payload),
            },
        )
        raise ValueError(
            f"Executor kind '{executor_kind}' is not allowed for hook family '{hook_family}'"
        )

    try:
        source_path = _resolve_source_path(
            executor_kind=normalized_kind,
            source_ref=source_ref,
        )
        timeout_seconds = resolve_custom_hook_timeout(
            payload.get("hook_settings", {})
            if isinstance(payload.get("hook_settings"), dict)
            else {"timeout_seconds": DEFAULT_CUSTOM_HOOK_TIMEOUT_SECONDS}
        )
        isolation_mode = resolve_custom_hook_isolation_mode(
            payload.get("hook_settings", {})
            if isinstance(payload.get("hook_settings"), dict)
            else {ISOLATION_MODE_SETTING_KEY: HOST_ISOLATION_MODE}
        )
        if isolation_mode != SANDBOX_ISOLATION_MODE:
            module = _load_module_from_path(source_path)
            handler = getattr(module, normalized_entrypoint, None)
            if handler is None or not callable(handler):
                raise ValueError(
                    f"Runtime hook entrypoint '{normalized_entrypoint}' was not found in {source_ref}"
                )
    except Exception as exc:
        await _log_custom_hook_audit(
            action="runtime_hook.custom_execution_failed",
            payload=payload,
            executor_kind=normalized_kind,
            source_ref=source_ref,
            entrypoint=normalized_entrypoint,
            hook_family=normalized_hook_family,
            details={
                "error": str(exc),
                "error_type": type(exc).__name__,
                "isolation_mode": _requested_isolation_mode(payload),
            },
        )
        raise

    if isolation_mode == SANDBOX_ISOLATION_MODE:
        project_id = str(payload.get("project_id") or "").strip()
        tenant_id = str(payload.get("tenant_id") or "").strip()
        if not project_id or not tenant_id:
            await _log_custom_hook_audit(
                action="runtime_hook.custom_execution_requires_sandbox",
                payload=payload,
                executor_kind=normalized_kind,
                source_ref=source_ref,
                entrypoint=normalized_entrypoint,
                hook_family=normalized_hook_family,
                details={
                    "reason": "missing_project_or_tenant_context",
                    "isolation_mode": isolation_mode,
                },
            )
            raise RuntimeError(
                "Sandbox-isolated custom hook execution requires project_id and tenant_id"
            )
        try:
            await _log_custom_hook_audit(
                action="runtime_hook.custom_execution_started",
                payload=payload,
                executor_kind=normalized_kind,
                source_ref=source_ref,
                entrypoint=normalized_entrypoint,
                hook_family=normalized_hook_family,
                details={
                    "timeout_seconds": timeout_seconds,
                    "isolation_mode": isolation_mode,
                },
            )
            sandbox_execution = await SandboxRuntimeHookRunner(get_sandbox_resource_port()).run(
                project_id=project_id,
                tenant_id=tenant_id,
                source_path=source_path,
                entrypoint=normalized_entrypoint,
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            await _log_custom_hook_audit(
                action="runtime_hook.custom_execution_failed",
                payload=payload,
                executor_kind=normalized_kind,
                source_ref=source_ref,
                entrypoint=normalized_entrypoint,
                hook_family=normalized_hook_family,
                details={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "isolation_mode": isolation_mode,
                },
            )
            raise
        result_type = "none" if sandbox_execution.result is None else "dict"
        await _log_custom_hook_audit(
            action="runtime_hook.custom_execution_succeeded",
            payload=payload,
            executor_kind=normalized_kind,
            source_ref=source_ref,
            entrypoint=normalized_entrypoint,
            hook_family=normalized_hook_family,
            details={
                "result_type": result_type,
                "isolation_mode": isolation_mode,
                "sandbox_id": sandbox_execution.sandbox_id,
            },
        )
        return sandbox_execution.result

    try:
        await _log_custom_hook_audit(
            action="runtime_hook.custom_execution_started",
            payload=payload,
            executor_kind=normalized_kind,
            source_ref=source_ref,
            entrypoint=normalized_entrypoint,
            hook_family=normalized_hook_family,
            details={
                "timeout_seconds": timeout_seconds,
                "isolation_mode": isolation_mode,
            },
        )

        if handler is None:
            raise RuntimeError(
                f"Runtime hook entrypoint '{normalized_entrypoint}' was not loaded for host execution"
            )

        if inspect.iscoroutinefunction(handler):
            result = await asyncio.wait_for(
                handler(dict(payload)),
                timeout=timeout_seconds,
            )
        else:
            result = await asyncio.wait_for(
                asyncio.to_thread(handler, dict(payload)),
                timeout=timeout_seconds,
            )
        if result is not None and not isinstance(result, dict):
            raise ValueError(
                f"Runtime hook entrypoint '{normalized_entrypoint}' must return dict or None"
            )
    except Exception as exc:
        await _log_custom_hook_audit(
            action="runtime_hook.custom_execution_failed",
            payload=payload,
            executor_kind=normalized_kind,
            source_ref=source_ref,
            entrypoint=normalized_entrypoint,
            hook_family=normalized_hook_family,
            details={
                "error": str(exc),
                "error_type": type(exc).__name__,
                "isolation_mode": isolation_mode,
            },
        )
        raise

    result_type = "none" if result is None else "dict"
    await _log_custom_hook_audit(
        action="runtime_hook.custom_execution_succeeded",
        payload=payload,
        executor_kind=normalized_kind,
        source_ref=source_ref,
        entrypoint=normalized_entrypoint,
        hook_family=normalized_hook_family,
        details={"result_type": result_type, "isolation_mode": isolation_mode},
    )
    return result
