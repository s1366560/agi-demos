"""Tests for conversation route hardening."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers.agent import (
    conversations as conversations_router,
)
from src.infrastructure.adapters.primary.web.routers.agent.schemas import (
    UpdateConversationConfigRequest,
    UpdateConversationModeRequest,
    UpdateConversationTitleRequest,
)


class FailingListUseCase:
    execute = AsyncMock(side_effect=RuntimeError("internal conversation list secret"))


class FailingGetUseCase:
    execute = AsyncMock(side_effect=RuntimeError("internal conversation get secret"))


class FailingAgentService:
    get_conversation = AsyncMock(side_effect=RuntimeError("internal conversation service secret"))


class FailingDb:
    get = AsyncMock(side_effect=RuntimeError("internal direct db secret"))
    rollback = AsyncMock()


def _request_with_container(container: object) -> MagicMock:
    request = MagicMock()
    request.app.state.container.with_db.return_value = container
    return request


@pytest.fixture(autouse=True)
def _patch_llm_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        conversations_router,
        "create_llm_client",
        AsyncMock(return_value=object()),
    )


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_name", "expected_detail"),
    [
        ("list", "Failed to list conversations"),
        ("get", "Failed to get conversation"),
        ("context_status", "Failed to get context status"),
        ("delete", "Failed to delete conversation"),
        ("title", "Failed to update conversation title"),
        ("config", "Failed to update conversation config"),
        ("mode", "Failed to update conversation mode"),
        ("generate_title", "Failed to generate conversation title"),
        ("summary", "Failed to generate conversation summary"),
    ],
)
async def test_service_backed_conversation_routes_sanitize_internal_errors(
    route_name: str,
    expected_detail: str,
) -> None:
    container = SimpleNamespace(
        list_conversations_use_case=lambda _llm: FailingListUseCase(),
        get_conversation_use_case=lambda _llm: FailingGetUseCase(),
        agent_service=lambda _llm: FailingAgentService(),
    )
    request = _request_with_container(container)
    current_user = SimpleNamespace(id="user-1")

    route_calls: dict[str, Any] = {
        "list": lambda: conversations_router.list_conversations(
            request=request,
            project_id="project-1",
            status=None,
            limit=50,
            offset=0,
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        ),
        "get": lambda: conversations_router.get_conversation(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        ),
        "context_status": lambda: conversations_router.get_context_status(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        ),
        "delete": lambda: conversations_router.delete_conversation(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        ),
        "title": lambda: conversations_router.update_conversation_title(
            conversation_id="conversation-1",
            data=UpdateConversationTitleRequest(title="New title"),
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        ),
        "config": lambda: conversations_router.update_conversation_config(
            conversation_id="conversation-1",
            data=UpdateConversationConfigRequest(llm_model_override="gpt-test"),
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(rollback=AsyncMock()),
        ),
        "mode": lambda: conversations_router.update_conversation_mode(
            conversation_id="conversation-1",
            data=UpdateConversationModeRequest(conversation_mode="single_agent"),
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(rollback=AsyncMock()),
        ),
        "generate_title": lambda: conversations_router.generate_conversation_title(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        ),
        "summary": lambda: conversations_router.generate_summary(
            conversation_id="conversation-1",
            request=request,
            project_id="project-1",
            current_user=current_user,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        ),
    }

    with pytest.raises(HTTPException) as exc_info:
        await route_calls[route_name]()

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == expected_detail
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_name", "expected_detail"),
    [
        ("fork", "Failed to fork conversation"),
        ("edit_message", "Failed to edit message"),
        ("tool_undo", "Failed to request tool undo"),
    ],
)
async def test_db_backed_conversation_routes_sanitize_internal_errors(
    route_name: str,
    expected_detail: str,
) -> None:
    current_user = SimpleNamespace(id="user-1")
    db = FailingDb()
    route_calls: dict[str, Any] = {
        "fork": lambda: conversations_router.fork_conversation(
            conversation_id="conversation-1",
            message_id="message-1",
            current_user=current_user,
            db=db,
        ),
        "edit_message": lambda: conversations_router.edit_message(
            conversation_id="conversation-1",
            message_id="message-1",
            data={"content": "updated"},
            current_user=current_user,
            db=db,
        ),
        "tool_undo": lambda: conversations_router.request_tool_undo(
            conversation_id="conversation-1",
            execution_id="execution-1",
            current_user=current_user,
            db=db,
        ),
    }

    with pytest.raises(HTTPException) as exc_info:
        await route_calls[route_name]()

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == expected_detail
    assert "internal" not in exc_info.value.detail
