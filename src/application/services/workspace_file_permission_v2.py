"""Bind confined builtin filesystem calls to fresh canonical sandbox authority."""

from __future__ import annotations

import posixpath
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.approved_run_tool_permission_v2 import (
    _read_run,
    current_approved_run_guard_v2,
)
from src.application.services.chat_run_tool_permission_v2 import current_chat_run_guard_v2
from src.domain.ports.services.sandbox_port import SandboxPort, SandboxStatus
from src.infrastructure.adapters.secondary.persistence.models import AgentRunAuthorityModel
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


def _denied() -> RuntimeV2Error:
    return RuntimeV2Error(
        "workspace_file_permission_denied",
        "Workspace file operation does not match run environment",
    )


async def require_workspace_file_binding_v2(
    *,
    sandbox_id: str,
    workspace_root: str,
    sandbox_port: SandboxPort,
) -> None:
    """Use only server metadata, live sandbox labels and persisted run identities.

    Ordinary chat receives its first environment binding from this trusted
    runtime boundary. An existing plan/chat binding is immutable; peer chains
    share the same sandbox instead of inheriting a broader receiver environment.
    """
    approved = current_approved_run_guard_v2()
    chat = current_chat_run_guard_v2()
    guard = approved or chat
    if guard is None or (approved is not None and chat is not None):
        raise _denied()
    instance = await sandbox_port.get_sandbox(sandbox_id)
    if (
        instance is None
        or instance.id != sandbox_id
        or instance.status != SandboxStatus.RUNNING
        or instance.labels.get("memstack.tenant_id") != guard.identity[0]
        or instance.labels.get("memstack.project_id") != guard.identity[1]
    ):
        raise _denied()
    if approved is not None:
        await approved.require("workspace_file_write")
    elif chat is not None:
        # The invocation's ASK capability was consumed at the raw-call boundary.
        # Recheck identity, cancellation and current policy without reusing it.
        await chat.decision("read", "", {})
    row = await _read_run(guard.sessions, guard.run_id, guard.identity, guard.child_run_id)
    rows = {row.id: row}
    binding = row.authorization_snapshot.get("sender_authority")
    from src.application.services.peer_chat_permission_validation_v2 import (
        _source,
        require_peer_sender_permission_v2,
    )

    await require_peer_sender_permission_v2(
        row, "workspace_file_write", guard.identity, guard.sessions
    )
    while binding is not None:
        if not isinstance(binding, dict) or not isinstance(binding.get("run_id"), str):
            raise _denied()
        if binding["run_id"] in rows:
            raise _denied()
        source, _ = await _source(guard.sessions, binding, guard.identity)
        rows[source.id] = source
        binding = source.authorization_snapshot.get("sender_authority")
    await _bind_environment_rows(guard.sessions, rows, sandbox_id, workspace_root)
    await _read_run(guard.sessions, guard.run_id, guard.identity, guard.child_run_id)


async def _bind_environment_rows(
    sessions: async_sessionmaker[AsyncSession],
    rows: dict[str, AgentRunAuthorityModel],
    sandbox_id: str,
    workspace_root: str,
) -> None:
    expected = {"id": sandbox_id, "workspace_path": workspace_root}
    async with sessions() as db:
        locked = list(
            (
                await db.scalars(
                    select(AgentRunAuthorityModel)
                    .where(AgentRunAuthorityModel.id.in_(rows))
                    .order_by(AgentRunAuthorityModel.id)
                    .with_for_update()
                )
            ).all()
        )
        if len(locked) != len(rows):
            raise _denied()
        for current in locked:
            original = rows[current.id]
            if (
                current.authorization_snapshot != original.authorization_snapshot
                or current.status != original.status
                or (current.tenant_id, current.project_id, current.conversation_id)
                != (original.tenant_id, original.project_id, original.conversation_id)
            ):
                raise _denied()
            environment = current.authorization_snapshot.get("environment")
            if environment is not None:
                if not isinstance(environment, Mapping) or any(
                    environment.get(key) != value for key, value in expected.items()
                ):
                    raise _denied()
            elif current.run_kind == "chat":
                current.authorization_snapshot = {
                    **current.authorization_snapshot,
                    "environment": {
                        **expected,
                        "kind": "sandbox",
                        "source": "builtin-workspace-fd",
                    },
                }
            else:
                raise _denied()
        await db.commit()


def parse_workspace_write_contract_v2(schema: dict[str, Any]) -> str | None:
    meta = schema.get("_meta")
    if not isinstance(meta, dict) or "memstack/workspace-write" not in meta:
        return None
    value = meta["memstack/workspace-write"]
    if not isinstance(value, dict) or set(value) != {"contract", "workspace_root"}:
        raise _denied()
    root = value["workspace_root"]
    if (
        value["contract"] != "directory-fd-write-v1"
        or not isinstance(root, str)
        or not root.startswith("/")
        or root == "/"
        or ".." in root.split("/")
        or "\x00" in root
    ):
        raise _denied()
    return root.rstrip("/")


def validate_confined_write_arguments_v2(arguments: dict[str, Any], root: str) -> None:
    allowed_fields = {"file_path", "path", "content", "mode", "append"}
    if set(arguments) - allowed_fields:
        raise _denied()
    requested = arguments.get("file_path", arguments.get("path"))
    if (
        not isinstance(requested, str)
        or not requested
        or "\x00" in requested
        or ".." in requested.split("/")
        or (
            "file_path" in arguments
            and "path" in arguments
            and arguments["file_path"] != arguments["path"]
        )
    ):
        raise _denied()
    target = posixpath.normpath(posixpath.join(root, requested))
    if not target.startswith(root + "/"):
        raise _denied()
