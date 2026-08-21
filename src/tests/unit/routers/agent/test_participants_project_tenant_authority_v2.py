"""Project lookup coverage for participant router V2 authority cutover."""

from __future__ import annotations

from inspect import signature
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.project_tenant_authority_v2 import (
    project_tenant_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.agent import participants

pytestmark = pytest.mark.unit


class _AuthorityObserved(Exception):
    """Stop an endpoint once its loader receives the expected authority."""


@pytest.mark.parametrize(
    "route_name",
    [
        "list_participants",
        "add_participant",
        "remove_participant",
        "set_coordinator",
        "set_focused_agent",
        "list_mention_candidates",
    ],
)
def test_participant_routes_declare_v2_project_tenant_authority(route_name: str) -> None:
    parameter = signature(getattr(participants, route_name)).parameters["project_tenant"]

    assert parameter.default.dependency is project_tenant_authority_dependency_v2


@pytest.mark.parametrize(
    "route_name",
    [
        "list_participants",
        "add_participant",
        "remove_participant",
        "set_coordinator",
        "set_focused_agent",
        "list_mention_candidates",
    ],
)
async def test_participant_routes_pass_v2_authority_to_loader(
    monkeypatch: pytest.MonkeyPatch,
    route_name: str,
) -> None:
    authority = SimpleNamespace(services=SimpleNamespace())

    async def authority_bound_loader(
        request: object,
        db: object,
        conversation_id: str,
        project_tenant: object,
    ) -> None:
        assert request is route_arguments["request"]
        assert db is route_arguments["db"]
        assert conversation_id == "conversation-1"
        assert project_tenant is authority
        raise _AuthorityObserved

    route_arguments = _route_arguments(route_name)
    route_arguments["project_tenant"] = authority
    monkeypatch.setattr(participants, "_load_conversation_and_project", authority_bound_loader)

    with pytest.raises(_AuthorityObserved):
        await getattr(participants, route_name)(**route_arguments)


async def test_loader_resolves_project_only_through_v2_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = SimpleNamespace(id="conversation-1", project_id="project-1")
    project = SimpleNamespace(id="project-1", tenant_id="tenant-1")
    conversation_repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=conversation),
    )
    project_repository = SimpleNamespace(find_by_id=AsyncMock(return_value=project))
    container_without_project_repository = SimpleNamespace(
        conversation_repository=Mock(return_value=conversation_repository),
    )
    authority = SimpleNamespace(
        services=SimpleNamespace(project_repository=project_repository),
    )
    monkeypatch.setattr(
        participants,
        "get_container_with_db",
        Mock(return_value=container_without_project_repository),
    )

    loaded = await participants._load_conversation_and_project(
        MagicMock(),
        MagicMock(),
        "conversation-1",
        authority,
    )

    assert loaded == (conversation_repository, conversation, project)
    conversation_repository.find_by_id.assert_awaited_once_with("conversation-1")
    project_repository.find_by_id.assert_awaited_once_with("project-1")


async def test_loader_does_not_query_project_before_conversation_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_repository = SimpleNamespace(find_by_id=AsyncMock(return_value=None))
    project_repository = SimpleNamespace(find_by_id=AsyncMock())
    container = SimpleNamespace(
        conversation_repository=Mock(return_value=conversation_repository),
    )
    authority = SimpleNamespace(
        services=SimpleNamespace(project_repository=project_repository),
    )
    monkeypatch.setattr(
        participants,
        "get_container_with_db",
        Mock(return_value=container),
    )

    with pytest.raises(HTTPException) as error:
        await participants._load_conversation_and_project(
            MagicMock(),
            MagicMock(),
            "missing-conversation",
            authority,
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Conversation not found"
    project_repository.find_by_id.assert_not_awaited()


async def test_loader_preserves_project_not_found_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = SimpleNamespace(id="conversation-1", project_id="missing-project")
    conversation_repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=conversation),
    )
    project_repository = SimpleNamespace(find_by_id=AsyncMock(return_value=None))
    container = SimpleNamespace(
        conversation_repository=Mock(return_value=conversation_repository),
    )
    authority = SimpleNamespace(
        services=SimpleNamespace(project_repository=project_repository),
    )
    monkeypatch.setattr(
        participants,
        "get_container_with_db",
        Mock(return_value=container),
    )

    with pytest.raises(HTTPException) as error:
        await participants._load_conversation_and_project(
            MagicMock(),
            MagicMock(),
            "conversation-1",
            authority,
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Project not found"
    project_repository.find_by_id.assert_awaited_once_with("missing-project")


def _route_arguments(route_name: str) -> dict[str, object]:
    arguments: dict[str, object] = {
        "conversation_id": "conversation-1",
        "request": MagicMock(),
        "current_user": SimpleNamespace(id="user-1"),
        "tenant_id": "tenant-1",
        "db": MagicMock(),
    }
    if route_name == "add_participant":
        arguments["data"] = participants.ParticipantAddRequest(agent_id="agent-1")
    elif route_name == "remove_participant":
        arguments["agent_id"] = "agent-1"
        arguments["data"] = None
    elif route_name == "set_coordinator":
        arguments["data"] = participants.CoordinatorSetRequest(agent_id="agent-1")
    elif route_name == "set_focused_agent":
        arguments["data"] = participants.FocusedAgentSetRequest(agent_id="agent-1")
    elif route_name == "list_mention_candidates":
        arguments["include_inactive"] = False
    return arguments
