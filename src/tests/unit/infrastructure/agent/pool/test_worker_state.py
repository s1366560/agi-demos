"""Retirement gates for process-global Agent Pool adapter state."""

from src.infrastructure.agent.state import agent_worker_state


def test_process_global_pool_adapter_seam_is_retired() -> None:
    """The Agent Pool is generation-owned and must not expose worker globals."""
    retired_names = {
        "_pool_adapter",
        "get_pool_adapter",
        "is_pool_enabled",
        "set_pool_adapter",
    }

    assert retired_names.isdisjoint(vars(agent_worker_state))
    assert retired_names.isdisjoint(agent_worker_state.__all__)
