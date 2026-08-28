"""Retirement gates for process-global HITL worker state."""

from src.infrastructure.agent.state import agent_worker_state


def test_process_global_hitl_worker_facade_is_retired() -> None:
    """HITL listener and waiter state must stay in the dedicated HITL runtime."""
    retired_names = {
        "_hitl_response_listener",
        "get_hitl_response_listener",
        "get_session_registry",
        "register_hitl_waiter",
        "set_hitl_response_listener",
        "unregister_hitl_waiter",
        "wait_for_hitl_response_realtime",
    }

    assert retired_names.isdisjoint(vars(agent_worker_state))
    assert retired_names.isdisjoint(agent_worker_state.__all__)
