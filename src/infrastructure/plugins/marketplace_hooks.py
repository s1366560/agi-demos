"""Run approved marketplace lifecycle commands inside the owning project's sandbox."""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.services.sandbox_resource_port import SandboxResourcePort
from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)
from src.infrastructure.plugins.marketplace_snapshot_cache import lease_marketplace_snapshots

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from src.infrastructure.plugins.v2.runtime import OperationContextV2
_EVENTS = {
    "agent.session.start": "session_start",
    "agent.before_request": "before_request",
    "tools.after_execute": "after_tool_execute",
}


class MarketplaceHookError(RuntimeError):
    """An approved hook failed; the triggering operation must stop."""


async def execute_marketplace_hooks(
    *,
    db: AsyncSession,
    sandbox: SandboxResourcePort,
    tenant_id: str,
    project_id: str,
    event: str,
    payload: dict[str, Any],
) -> None:
    """Query exact active project installations and execute their bounded hook snapshot."""
    hook_event = _EVENTS.get(event)
    if hook_event is None:
        return
    records = await db.scalars(
        select(MarketplaceRecordV3)
        .where(
            MarketplaceRecordV3.tenant_id == tenant_id,
            MarketplaceRecordV3.project_id == project_id,
            MarketplaceRecordV3.kind == "installation",
        )
        .order_by(MarketplaceRecordV3.id)
    )
    for record in records:
        installation = record.payload
        if installation.get("status") != "enabled":
            continue
        hooks = installation.get("package", {}).get("resources", {}).get("hooks", [])
        matching = [hook for hook in hooks if hook["event"] == hook_event]
        if not matching:
            continue
        if "process:execute" not in installation.get("approved_permissions", []):
            raise MarketplaceHookError("Marketplace hook execution permission is missing")
        root = installation.get("runtime_root")
        if not isinstance(root, str) or not root.startswith("/workspace/.memstack/plugins/"):
            raise MarketplaceHookError(
                "Marketplace hook package is not staged in the project sandbox"
            )
        # Event input is protocol context, never arbitrary credentials or full model prompts.
        context = {
            key: payload[key]
            for key in ("session_id", "conversation_id", "tool_name", "call_id", "event_id")
            if key in payload
        }
        context.update({"event": hook_event, "tenant_id": tenant_id, "project_id": project_id})
        encoded = json.dumps(context, ensure_ascii=True)
        for hook in matching:
            command = (
                hook["command"]
                .replace("${PLUGIN_ROOT}", shlex.quote(root))
                .replace("${CLAUDE_PLUGIN_ROOT}", shlex.quote(root))
            )
            timeout = min(30, max(1, hook.get("timeout_seconds", 30)))
            started = time.monotonic()
            succeeded = False
            try:
                async with lease_marketplace_snapshots(
                    db, tenant_id, project_id, runtime_root=root, sandbox=sandbox
                ):
                    result = await asyncio.wait_for(
                        sandbox.execute_tool(
                            project_id=project_id,
                            tool_name="bash",
                            arguments={
                                "command": f"printf '%s' {shlex.quote(encoded)} | {command}",
                                "working_dir": root,
                                "timeout": timeout,
                            },
                            timeout=float(timeout),
                        ),
                        timeout=timeout + 1,
                    )
                metadata = result.get("metadata", {})
                if (
                    result.get("isError")
                    or result.get("is_error")
                    or metadata.get("exit_code", 0) != 0
                ):
                    raise MarketplaceHookError(
                        "Marketplace hook failed; disable the plugin or fix its configuration before retrying"
                    )
                succeeded = True
            except TimeoutError as exc:
                raise MarketplaceHookError(
                    "Marketplace hook exceeded its execution timeout"
                ) from exc
            finally:
                logger.info(
                    "Marketplace hook installation=%s event=%s success=%s latency_ms=%d",
                    record.id,
                    hook_event,
                    succeeded,
                    int((time.monotonic() - started) * 1000),
                )


async def dispatch_marketplace_hooks(
    operation: OperationContextV2, *, event: str, payload: dict[str, Any]
) -> None:
    """Resolve existing generation-owned DB/sandbox services, without host-side execution."""
    if event not in _EVENTS:
        return
    from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
    from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
    from src.infrastructure.plugins.v2.sandbox_operation_services import (
        SANDBOX_OPERATION_APPLICATION_SERVICE_V2,
        SandboxOperationApplicationResolverProtocolV2,
    )

    try:
        db = operation.require(OPERATION_DB_SESSION_SERVICE_V2)
    except RuntimeV2Error as exc:
        # Lightweight plugin-host operations have no database or marketplace resources.
        if getattr(exc, "code", "") == "missing_service":
            return
        raise
    if not isinstance(db, AsyncSession):
        return
    scope = operation.context.scope
    if not scope.tenant_id or not scope.project_id:
        return
    # Resolve sandbox lazily only when an active installation actually declares hooks.
    rows = await db.scalars(
        select(MarketplaceRecordV3).where(
            MarketplaceRecordV3.tenant_id == scope.tenant_id,
            MarketplaceRecordV3.project_id == scope.project_id,
            MarketplaceRecordV3.kind == "installation",
        )
    )
    if not any(
        row.payload.get("status") == "enabled"
        and row.payload.get("package", {}).get("resources", {}).get("hooks")
        for row in rows
    ):
        return
    resolver = operation.require(SANDBOX_OPERATION_APPLICATION_SERVICE_V2)
    if not isinstance(resolver, SandboxOperationApplicationResolverProtocolV2):
        raise TypeError("Sandbox marketplace hook service is unavailable")
    sandbox = resolver.resolve(operation).sandbox_resource
    await execute_marketplace_hooks(
        db=db,
        sandbox=sandbox,
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        event=event,
        payload=payload,
    )
