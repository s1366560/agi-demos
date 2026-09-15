"""Host authority bindings cannot be forged through lifecycle metadata."""

import pytest

from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry


@pytest.mark.unit
@pytest.mark.parametrize(
    "method",
    [
        "create_run",
        "attach_metadata",
        "mark_running",
        "mark_completed",
        "mark_failed",
        "mark_cancelled",
        "mark_timed_out",
    ],
)
def test_chat_authority_survives_every_generic_mutation(method):
    registry = SubAgentRunRegistry()
    run = registry.create_run(
        "cid",
        "reader",
        "task",
        run_id="child",
        metadata={
            "chat_permission_run_id": "forged",
            "chat_permission_mode": "full_access",
        },
    )
    assert "chat_permission_run_id" not in run.metadata
    registry.bind_chat_permission_authority("cid", "child", chat_run_id="real-parent", mode="ask")
    if method in {"mark_completed", "mark_failed"}:
        registry.mark_running("cid", "child")
    metadata = {"chat_permission_run_id": "forged", "chat_permission_mode": "full_access"}
    with pytest.raises(ValueError):
        if method == "create_run":
            registry.create_run("cid", "reader", "task", run_id="child", metadata=metadata)
        elif method == "mark_failed":
            registry.mark_failed("cid", "child", "error", metadata=metadata)
        else:
            getattr(registry, method)("cid", "child", metadata=metadata)
    assert registry.get_run("cid", "child").metadata["chat_permission_mode"] == "ask"


@pytest.mark.unit
@pytest.mark.parametrize("first", ["chat", "plan"])
def test_child_cannot_bind_two_different_authority_kinds(first):
    registry = SubAgentRunRegistry()
    registry.create_run("cid", "reader", "task", run_id="child")

    def chat():
        return registry.bind_chat_permission_authority(
            "cid", "child", chat_run_id="chat", mode="ask"
        )

    def plan():
        return registry.bind_approved_plan_authority(
            "cid", "child", approved_run_id="plan", ceiling="read_only"
        )

    (chat if first == "chat" else plan)()
    with pytest.raises(ValueError):
        (plan if first == "chat" else chat)()
