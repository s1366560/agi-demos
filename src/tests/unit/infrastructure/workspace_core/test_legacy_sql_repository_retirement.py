"""Regression coverage for the retired platform SQL Workspace repositories."""

from __future__ import annotations

import pytest

from src.configuration.containers.project_container import ProjectContainer
from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.secondary.persistence.sql_workspace_agent_repository import (
    LegacyWorkspaceAgentRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_collaboration_authority_repository import (
    LegacyWorkspaceCollaborationAuthorityRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_member_repository import (
    LegacyWorkspaceMemberRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_message_repository import (
    LegacyWorkspaceMessageRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_repository import (
    LegacyWorkspaceRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
    LegacyWorkspaceTaskRepository,
)
from src.infrastructure.workspace_core.legacy_runtime import (
    LegacyWorkspaceRuntimeRetiredError,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "repository_type",
    [
        LegacyWorkspaceAgentRepository,
        LegacyWorkspaceCollaborationAuthorityRepository,
        LegacyWorkspaceMemberRepository,
        LegacyWorkspaceMessageRepository,
        LegacyWorkspaceRepository,
        LegacyWorkspaceTaskRepository,
    ],
)
def test_legacy_sql_workspace_repositories_fail_closed_without_touching_session(
    repository_type: type[object],
) -> None:
    class SessionTrap:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"legacy repository accessed SQL session attribute {name}")

    with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="Avernet Workspace Core"):
        repository_type(SessionTrap())


@pytest.mark.unit
@pytest.mark.parametrize(
    "factory_name",
    [
        "topology_repository",
    ],
)
def test_project_container_workspace_factories_fail_closed_without_sql(
    factory_name: str,
) -> None:
    class SessionTrap:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"legacy container accessed SQL session attribute {name}")

    container = ProjectContainer(db=SessionTrap())  # type: ignore[arg-type]

    with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="Avernet Workspace Core"):
        getattr(container, factory_name)()


@pytest.mark.unit
def test_topology_static_service_facades_are_removed_after_workspace_core_cutover() -> None:
    assert "topology_service" not in vars(ProjectContainer)
    assert "topology_service" not in vars(DIContainer)


@pytest.mark.unit
def test_cyber_objective_static_di_facades_are_removed_after_workspace_core_cutover() -> None:
    assert "cyber_objective_repository" not in vars(ProjectContainer)
    assert "cyber_objective_repository" not in vars(DIContainer)


@pytest.mark.unit
def test_cyber_gene_static_di_facades_are_removed_after_workspace_core_cutover() -> None:
    assert "cyber_gene_repository" not in vars(ProjectContainer)
    assert "cyber_gene_repository" not in vars(DIContainer)


@pytest.mark.unit
def test_blackboard_static_di_facades_are_removed_after_workspace_core_cutover() -> None:
    retired_facades = {
        "blackboard_repository",
        "blackboard_service",
        "blackboard_file_repository",
        "blackboard_file_service",
    }

    assert retired_facades.isdisjoint(vars(ProjectContainer))
    assert retired_facades.isdisjoint(vars(DIContainer))
