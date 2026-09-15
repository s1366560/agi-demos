"""Versioned commands for a persisted child execution, independent of its parent run."""

import json
from functools import partial
from hashlib import sha256
from typing import Any

from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus
from src.infrastructure.plugins.v2.agent_subagent_control_services import (
    AgentSubAgentControlServiceProtocolV2,
)

from .async_run_registry_v2 import registry_transaction_v2
from .owner_lease_v2 import OWNER_PROTOCOL_V2
from .run_registry import SubAgentRunRegistry

_ACTIVE = {SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING}


class SubAgentControlConflictV2(ValueError):
    """The caller must reload exact child authority before a new command."""


def _revision(run: SubAgentRun) -> int:
    revision = run.metadata.get("control_revision", 0)
    if type(revision) is not int or revision < 0:
        raise SubAgentControlConflictV2("subagent_control_revision_invalid")
    return revision


def _snapshot(run: SubAgentRun) -> dict[str, Any]:
    actions = []
    if run.metadata.get("execution_protocol") == OWNER_PROTOCOL_V2 and not run.metadata.get(
        "cancel_requested"
    ):
        if run.status is SubAgentRunStatus.RUNNING:
            actions = ["steer", "kill_run"]
        elif run.status is SubAgentRunStatus.PENDING:
            actions = ["kill_run"]
    return {
        "run_id": run.run_id,
        "conversation_id": run.conversation_id,
        "subagent_name": run.subagent_name,
        "status": run.status.value,
        "control_revision": _revision(run),
        "allowed_actions": actions,
        "cancel_requested": run.metadata.get("cancel_requested") is True,
    }


async def execution_control_snapshot_v2(
    registry: SubAgentRunRegistry,
    conversation_id: str,
) -> list[dict[str, Any]]:
    return await registry_transaction_v2(
        registry, lambda memory: [_snapshot(run) for run in memory.list_runs(conversation_id)]
    )


def _register_command(
    memory: SubAgentRunRegistry,
    *,
    conversation_id: str,
    run_id: str,
    requested_by: str,
    action: str,
    expected_control_revision: int,
    idempotency_key: str,
    fingerprint: str,
) -> tuple[dict[str, Any], bool, bool]:
    run = memory.get_run(conversation_id, run_id)
    if run is None:
        raise SubAgentControlConflictV2("subagent_control_execution_not_found")
    receipts = dict(run.metadata.get("control_receipts", {}))
    existing = receipts.get(idempotency_key)
    if existing is not None:
        if existing["fingerprint"] != fingerprint:
            raise SubAgentControlConflictV2("subagent_control_idempotency_conflict")
        return (
            dict(existing),
            True,
            run.status in _ACTIVE
            and (action == "kill_run" or not run.metadata.get("cancel_requested")),
        )
    if _revision(run) != expected_control_revision:
        raise SubAgentControlConflictV2("subagent_control_revision_conflict")
    if action not in _snapshot(run)["allowed_actions"]:
        raise SubAgentControlConflictV2("subagent_control_action_unavailable")
    if action == "steer" and any(not item["delivered"] for item in receipts.values()):
        raise SubAgentControlConflictV2("subagent_control_delivery_pending")
    if len(receipts) >= 128 and action != "kill_run":
        raise SubAgentControlConflictV2("subagent_control_receipt_capacity_reached")
    revision = expected_control_revision + 1
    receipt = {"fingerprint": fingerprint, "control_revision": revision, "delivered": False}
    receipts[idempotency_key] = receipt
    metadata: dict[str, object] = {"control_revision": revision, "control_receipts": receipts}
    if action == "kill_run":
        metadata.update(cancel_requested=True, cancel_requested_by=requested_by)
    assert (
        memory.attach_metadata(conversation_id, run_id, metadata, expected_statuses=list(_ACTIVE))
        is not None
    )
    return receipt, False, True


async def request_execution_control_v2(
    registry: SubAgentRunRegistry,
    service: AgentSubAgentControlServiceProtocolV2,
    *,
    conversation_id: str,
    run_id: str,
    requested_by: str,
    action: str,
    expected_control_revision: int,
    idempotency_key: str,
    instruction: str | None,
) -> dict[str, Any]:
    """Commit intent first; only the owner may acknowledge execution terminal state.

    Receipts remain inside the scoped PG snapshot and replay across API restarts.
    Redis steering delivery is atomically deduplicated with the same command key.
    No expired receipt is evicted while this execution remains addressable.
    """
    fingerprint = sha256(
        json.dumps(
            {
                "action": action,
                "revision": expected_control_revision,
                "instruction": instruction,
                "user": requested_by,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

    receipt, duplicate, active = await registry_transaction_v2(
        registry,
        partial(
            _register_command,
            conversation_id=conversation_id,
            run_id=run_id,
            requested_by=requested_by,
            action=action,
            expected_control_revision=expected_control_revision,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
        ),
        write=True,
    )
    if not receipt["delivered"] and active:
        if action == "kill_run":
            await service.request_cancel(
                execution_id=run_id,
                requested_by=requested_by,
                reason=None,
                conversation_id=conversation_id,
            )
        else:
            await service.request_steer(
                execution_id=run_id,
                requested_by=requested_by,
                conversation_id=conversation_id,
                instruction=instruction or "",
                idempotency_key=idempotency_key,
            )

        def delivered(memory: SubAgentRunRegistry) -> bool:
            run = memory.get_run(conversation_id, run_id)
            if run is None:
                return True
            receipts = dict(run.metadata.get("control_receipts", {}))
            saved = dict(receipts[idempotency_key])
            saved["delivered"] = True
            receipts[idempotency_key] = saved
            memory.attach_metadata(conversation_id, run_id, {"control_receipts": receipts})
            return run.status not in _ACTIVE

        terminal = await registry_transaction_v2(registry, delivered, write=True)
        if terminal:
            await service.release_controls(execution_id=run_id)
    return {
        "accepted": True,
        "duplicate": duplicate,
        "action": action,
        "conversation_id": conversation_id,
        "run_id": run_id,
        "control_revision": receipt["control_revision"],
        "idempotency_key": idempotency_key,
    }
