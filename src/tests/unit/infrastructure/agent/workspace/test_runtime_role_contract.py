from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_LEADER,
    WORKSPACE_ROLE_WORKER,
    derive_workspace_session_role,
)


def test_derive_workspace_session_role_returns_worker_for_bound_task() -> None:
    assert derive_workspace_session_role(has_workspace_binding=True) == WORKSPACE_ROLE_WORKER


def test_derive_workspace_session_role_returns_leader_without_binding() -> None:
    assert derive_workspace_session_role(has_workspace_binding=False) == WORKSPACE_ROLE_LEADER
