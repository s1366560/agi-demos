"""Compatibility entry points for retired platform Workspace attempt recovery.

Avernet Core is the only authority for Workspace attempts and replay. These
functions remain temporarily importable by compatibility routes, but they
never start a worker, read legacy Workspace tables, or enqueue a legacy outbox.
"""

from __future__ import annotations


async def initialize_attempt_recovery() -> None:
    """Keep the retired startup hook fail-closed and inactive."""
    return None


async def recover_workspace_attempts_once(workspace_id: str) -> int:
    """Refuse legacy recovery while preserving the temporary call contract."""
    del workspace_id
    return 0


async def shutdown_attempt_recovery() -> None:
    """No-op because the retired worker can never be started."""
    return None


__all__ = [
    "initialize_attempt_recovery",
    "recover_workspace_attempts_once",
    "shutdown_attempt_recovery",
]
