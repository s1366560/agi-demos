"""Tests for the retired Python workspace chat execution path."""

from __future__ import annotations

import pytest
from fastapi import HTTPException, status


class _AccessTrap:
    def __getattribute__(self, name: str) -> object:
        raise AssertionError(f"retired workspace chat handler accessed {name}")


def _assert_workspace_core_unavailable(exc: HTTPException) -> None:
    assert exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc.detail == {
        "code": "WORKSPACE_CORE_UNAVAILABLE",
        "reason": "workspace_core_unavailable",
        "detail": "Workspace Core is unavailable",
    }


@pytest.mark.unit
class TestWorkspaceChatRouter:
    def test_module_keeps_contract_schemas_without_local_service_helpers(self) -> None:
        from src.infrastructure.adapters.primary.web.routers import workspace_chat

        assert {
            "SendMessageRequest",
            "MessageResponse",
            "MessageListResponse",
        }.issubset(vars(workspace_chat))
        assert {
            "WorkspaceMessageService",
            "WorkspaceMessage",
            "MessageSenderType",
            "get_message_service",
            "get_db",
            "require_workspace_access",
            "_publish_pending_chat_events_after_failure",
            "_map_error",
            "_to_response",
            "_fire_mention_routing",
        }.isdisjoint(vars(workspace_chat))

    async def test_send_message_fails_closed_without_local_di(self) -> None:
        from src.infrastructure.adapters.primary.web.routers import workspace_chat

        with pytest.raises(HTTPException) as exc_info:
            await workspace_chat.send_message(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                payload=workspace_chat.SendMessageRequest(content="Hello"),
                current_user=_AccessTrap(),
            )

        _assert_workspace_core_unavailable(exc_info.value)

    async def test_list_messages_fails_closed_without_local_di(self) -> None:
        from src.infrastructure.adapters.primary.web.routers import workspace_chat

        with pytest.raises(HTTPException) as exc_info:
            await workspace_chat.list_messages(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                limit=50,
                before=None,
                current_user=_AccessTrap(),
            )

        _assert_workspace_core_unavailable(exc_info.value)

    async def test_get_mentions_fails_closed_without_local_di(self) -> None:
        from src.infrastructure.adapters.primary.web.routers import workspace_chat

        with pytest.raises(HTTPException) as exc_info:
            await workspace_chat.get_mentions(
                tenant_id="tenant-1",
                project_id="project-1",
                workspace_id="workspace-1",
                target_id="agent-1",
                limit=50,
                current_user=_AccessTrap(),
            )

        _assert_workspace_core_unavailable(exc_info.value)


@pytest.mark.unit
def test_workspace_chat_contract_models_remain_stable() -> None:
    from src.infrastructure.adapters.primary.web.routers import workspace_chat

    assert set(workspace_chat.SendMessageRequest.model_fields) == {
        "content",
        "sender_type",
        "parent_message_id",
        "mentions",
    }
    assert set(workspace_chat.MessageResponse.model_fields) == {
        "id",
        "workspace_id",
        "sender_id",
        "sender_type",
        "content",
        "mentions",
        "parent_message_id",
        "metadata",
        "created_at",
    }
    assert set(workspace_chat.MessageListResponse.model_fields) == {"items"}
