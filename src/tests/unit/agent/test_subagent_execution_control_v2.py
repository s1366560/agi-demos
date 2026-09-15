"""Exact child execution commands never borrow parent revision or resource identity."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.subagent.execution_control_v2 import (
    SubAgentControlConflictV2,
    execution_control_snapshot_v2,
    request_execution_control_v2,
)
from src.infrastructure.agent.subagent.owner_lease_v2 import OWNER_PROTOCOL_V2
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry

pytestmark = pytest.mark.unit


def fixture():
    registry = SubAgentRunRegistry(sync_across_processes=False, recover_inflight_on_boot=False)
    registry.create_run(
        "conversation",
        "worker",
        "task",
        run_id="child",
        metadata={"execution_protocol": OWNER_PROTOCOL_V2, "parent_run_id": "completed-parent"},
    )
    registry.mark_running("conversation", "child")
    return registry, SimpleNamespace(request_cancel=AsyncMock(), request_steer=AsyncMock())


async def command(registry, service, **overrides):
    return await request_execution_control_v2(
        registry,
        service,
        conversation_id="conversation",
        run_id="child",
        requested_by="user",
        action="steer",
        expected_control_revision=0,
        idempotency_key="key-1",
        instruction="authorized instruction",
        **overrides,
    )


async def test_completed_parent_does_not_block_exact_child_steering_and_replay():
    registry, service = fixture()
    snapshot = await execution_control_snapshot_v2(registry, "conversation")
    assert snapshot[0]["allowed_actions"] == ["steer", "kill_run"]
    first = await command(registry, service)
    assert first["control_revision"] == 1
    assert first["duplicate"] is False
    assert (await command(registry, service))["duplicate"] is True
    service.request_steer.assert_awaited_once()
    registry.mark_completed("conversation", "child", summary="done")
    assert (await command(registry, service))["duplicate"] is True
    assert (await execution_control_snapshot_v2(registry, "conversation"))[0][
        "allowed_actions"
    ] == []


async def test_cancel_is_durable_request_until_owner_terminal_ack():
    registry, service = fixture()
    result = await request_execution_control_v2(
        registry,
        service,
        conversation_id="conversation",
        run_id="child",
        requested_by="user",
        action="kill_run",
        expected_control_revision=0,
        idempotency_key="kill",
        instruction=None,
    )
    assert result["accepted"] is True
    run = registry.get_run("conversation", "child")
    assert run.status.value == "running"
    assert run.metadata["cancel_requested"] is True
    assert (await execution_control_snapshot_v2(registry, "conversation"))[0][
        "allowed_actions"
    ] == []
    service.request_cancel.assert_awaited_once()


@pytest.mark.parametrize(
    "change",
    ["wrong-run", "wrong-conversation", "legacy", "terminal", "stale", "same-key-different-body"],
)
async def test_invalid_or_changed_execution_has_no_new_delivery(change):
    registry, service = fixture()
    args = {
        "conversation_id": "conversation",
        "run_id": "child",
        "requested_by": "user",
        "action": "steer",
        "expected_control_revision": 0,
        "idempotency_key": "key",
        "instruction": "first",
    }
    if change == "wrong-run":
        args["run_id"] = "worker"
    if change == "wrong-conversation":
        args["conversation_id"] = "other"
    if change == "legacy":
        registry.attach_metadata("conversation", "child", {"execution_protocol": None})
    if change == "terminal":
        registry.mark_completed("conversation", "child", summary="done")
    if change == "stale":
        args["expected_control_revision"] = 2
    if change == "same-key-different-body":
        await request_execution_control_v2(registry, service, **args)
        args["instruction"] = "second"
        service.request_steer.reset_mock()
    with pytest.raises(SubAgentControlConflictV2):
        await request_execution_control_v2(registry, service, **args)
    service.request_steer.assert_not_awaited()
    service.request_cancel.assert_not_awaited()


async def test_failed_steering_blocks_reordering_but_cancel_can_preempt():
    registry, service = fixture()
    service.request_steer.side_effect = RuntimeError("delivery unavailable")
    with pytest.raises(RuntimeError):
        await command(registry, service)
    service.request_steer.side_effect = None
    with pytest.raises(SubAgentControlConflictV2, match="delivery_pending"):
        await request_execution_control_v2(
            registry,
            service,
            conversation_id="conversation",
            run_id="child",
            requested_by="user",
            action="steer",
            expected_control_revision=1,
            idempotency_key="new",
            instruction="newer instruction",
        )
    service.request_steer.reset_mock()
    await request_execution_control_v2(
        registry,
        service,
        conversation_id="conversation",
        run_id="child",
        requested_by="user",
        action="kill_run",
        expected_control_revision=1,
        idempotency_key="kill",
        instruction=None,
    )
    await command(registry, service)
    service.request_steer.assert_not_awaited()


async def test_terminal_between_registration_and_delivery_releases_late_control():
    registry, service = fixture()

    async def finish_during_delivery(**kwargs):
        registry.mark_completed("conversation", "child", summary="owner completed")

    service.request_steer.side_effect = finish_during_delivery
    service.release_controls = AsyncMock()
    await command(registry, service)
    service.release_controls.assert_awaited_once_with(execution_id="child")
    assert registry.get_run("conversation", "child").status.value == "completed"
