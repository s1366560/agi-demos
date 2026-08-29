"""Participant router coverage for the generation-owned V2 authority."""

from __future__ import annotations

from inspect import getsource, signature
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.conversation_participant_http_application_authority_v2 import (
    conversation_participant_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.agent import participants
from src.infrastructure.plugins.v2.conversation_participant_services import (
    ConversationParticipantConversationNotFoundV2,
    ConversationParticipantProjectNotFoundV2,
)

pytestmark = pytest.mark.unit


class _AuthorityObserved(Exception):
    """Stop an endpoint once its loader receives the expected authority."""


def test_participant_router_has_no_static_persistence_or_agent_registry_authority() -> None:
    source = getsource(participants)

    assert "get_container_with_db" not in source
    assert "SqlConversationRepository" not in source
    assert "project_tenant_authority_dependency_v2" not in source
    assert "agent_registry" not in source
    assert "Depends(get_db)" not in source


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
def test_participant_routes_declare_v2_participant_authority(route_name: str) -> None:
    parameter = signature(getattr(participants, route_name)).parameters["participant_authority"]

    assert (
        parameter.default.dependency
        is conversation_participant_http_application_authority_dependency_v2
    )


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
    authority = SimpleNamespace(service=SimpleNamespace())

    async def authority_bound_loader(
        service: object,
        conversation_id: str,
    ) -> None:
        assert service is authority.service
        assert conversation_id == "conversation-1"
        raise _AuthorityObserved

    route_arguments = _route_arguments(route_name)
    route_arguments["participant_authority"] = authority
    monkeypatch.setattr(participants, "_load_conversation_and_project", authority_bound_loader)

    with pytest.raises(_AuthorityObserved):
        await getattr(participants, route_name)(**route_arguments)


async def test_loader_resolves_conversation_and_project_only_through_v2_service() -> None:
    conversation = SimpleNamespace(id="conversation-1", project_id="project-1")
    project = SimpleNamespace(id="project-1", tenant_id="tenant-1")
    service = SimpleNamespace(
        load=AsyncMock(return_value=SimpleNamespace(conversation=conversation, project=project))
    )

    loaded = await participants._load_conversation_and_project(
        service,
        "conversation-1",
    )

    assert loaded == (conversation, project)
    service.load.assert_awaited_once_with("conversation-1")


async def test_loader_preserves_conversation_not_found_error() -> None:
    service = SimpleNamespace(
        load=AsyncMock(
            side_effect=ConversationParticipantConversationNotFoundV2("missing-conversation")
        )
    )

    with pytest.raises(HTTPException) as error:
        await participants._load_conversation_and_project(
            service,
            "missing-conversation",
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Conversation not found"


async def test_loader_preserves_project_not_found_error() -> None:
    service = SimpleNamespace(
        load=AsyncMock(side_effect=ConversationParticipantProjectNotFoundV2("missing-project"))
    )

    with pytest.raises(HTTPException) as error:
        await participants._load_conversation_and_project(
            service,
            "conversation-1",
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Project not found"


def _route_arguments(route_name: str) -> dict[str, object]:
    arguments: dict[str, object] = {
        "conversation_id": "conversation-1",
        "request": MagicMock(),
        "current_user": SimpleNamespace(id="user-1"),
        "tenant_id": "tenant-1",
        "participant_authority": SimpleNamespace(service=SimpleNamespace()),
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
