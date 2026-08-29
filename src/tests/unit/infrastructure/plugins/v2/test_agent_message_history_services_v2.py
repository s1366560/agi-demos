"""V2 application seam coverage for Agent message history queries."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.routers.agent.messages import (
    get_conversation_messages,
    get_conversation_tool_executions,
)
from src.infrastructure.plugins.v2.agent_message_history_services import (
    AGENT_MESSAGE_HISTORY_MODULE_V2,
    AgentMessageHistoryAccessDeniedV2,
    AgentMessageHistoryRepositoriesV2,
    AgentMessageHistoryServiceV2,
)
from src.infrastructure.plugins.v2.composer import load_profile_document_v2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"


class _ConversationAccess:
    def __init__(self, conversation: object | None) -> None:
        self.conversation = conversation

    async def find_by_id(self, _conversation_id: str) -> object | None:
        return self.conversation


class _ProjectAccess:
    def __init__(self) -> None:
        self.require_access = AsyncMock()


def _service(*, conversation: object | None = None) -> AgentMessageHistoryServiceV2:
    return AgentMessageHistoryServiceV2(
        repositories=AgentMessageHistoryRepositoriesV2(
            event=AsyncMock(),
            tool_execution=AsyncMock(),
            hitl_request=AsyncMock(),
            tenant_membership=SimpleNamespace(contains=AsyncMock(return_value=True)),
        ),
        conversation_access=_ConversationAccess(conversation),
        project_access=_ProjectAccess(),
    )


async def test_message_history_requires_exact_conversation_scope_before_project_access() -> None:
    service = _service(
        conversation=SimpleNamespace(
            id="conversation-a",
            tenant_id="tenant-a",
            project_id="project-a",
            user_id="user-a",
        )
    )

    conversation = await service.require_conversation_access(
        conversation_id="conversation-a",
        tenant_id="tenant-a",
        project_id="project-a",
        user_id="user-a",
    )

    assert conversation.id == "conversation-a"
    service.project_access.require_access.assert_awaited_once_with(
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
    )


async def test_message_history_rejects_cross_project_scope_without_membership_lookup() -> None:
    service = _service(
        conversation=SimpleNamespace(
            id="conversation-a",
            tenant_id="tenant-a",
            project_id="project-other",
            user_id="user-a",
        )
    )

    with pytest.raises(AgentMessageHistoryAccessDeniedV2):
        await service.require_conversation_access(
            conversation_id="conversation-a",
            tenant_id="tenant-a",
            project_id="project-a",
            user_id="user-a",
        )

    service.project_access.require_access.assert_not_awaited()


async def test_message_history_rejects_missing_tenant_membership() -> None:
    service = _service(
        conversation=SimpleNamespace(
            id="conversation-a",
            tenant_id="tenant-a",
            project_id="project-a",
            user_id="user-a",
        )
    )
    service.repositories.tenant_membership.contains.return_value = False

    with pytest.raises(AgentMessageHistoryAccessDeniedV2):
        await service.require_conversation_access(
            conversation_id="conversation-a",
            tenant_id="tenant-a",
            project_id="project-a",
            user_id="user-a",
        )

    service.repositories.tenant_membership.contains.assert_awaited_once_with(
        tenant_id="tenant-a",
        user_id="user-a",
    )
    service.project_access.require_access.assert_not_awaited()


async def test_message_history_filters_message_records_to_the_requested_conversation() -> None:
    service = _service()
    service.repositories.tool_execution.list_by_message.return_value = [
        SimpleNamespace(conversation_id="conversation-a"),
        SimpleNamespace(conversation_id="conversation-b"),
    ]

    records = await service.list_tool_executions(
        conversation_id="conversation-a",
        message_id="message-a",
        limit=25,
    )

    assert [record.conversation_id for record in records] == ["conversation-a"]
    service.repositories.tool_execution.list_by_message.assert_awaited_once_with(
        "message-a",
        limit=25,
    )


def test_message_history_module_is_an_explicit_profile_consumer() -> None:
    profile = load_profile_document_v2(_PROFILE_PATH)
    entry = next(
        entry for entry in profile.entries if entry.module_ref == AGENT_MESSAGE_HISTORY_MODULE_V2
    )

    assert entry.enabled is True
    assert entry.config == {"strategy": "operation-scoped-providers"}
    assert entry.inject == {
        "conversation_access": "service:application.conversation-access",
        "project_access": "service:application.project-access",
        "repositories": "service:persistence.agent-message-history-repository-provider",
    }


def test_message_history_routes_have_no_static_container_lookup() -> None:
    for handler in (get_conversation_messages, get_conversation_tool_executions):
        source = inspect.getsource(handler)
        assert "get_container_with_db" not in source
        assert "container." not in source
