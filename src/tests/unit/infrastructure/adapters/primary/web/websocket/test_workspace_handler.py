from types import SimpleNamespace

import pytest

from src.infrastructure.adapters.primary.web.websocket.handlers.project_events_handler import (
    SubscribeProjectEventsHandler,
    UnsubscribeProjectEventsHandler,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.workspace_handler import (
    SubscribeWorkspaceHandler,
    UnsubscribeWorkspaceHandler,
    _has_workspace_member,
    configure_workspace_access_verifier,
)


def test_workspace_handlers_message_types() -> None:
    assert SubscribeWorkspaceHandler().message_type == "subscribe_workspace"
    assert UnsubscribeWorkspaceHandler().message_type == "unsubscribe_workspace"


def test_project_event_handlers_message_types() -> None:
    assert SubscribeProjectEventsHandler().message_type == "subscribe_project_events"
    assert UnsubscribeProjectEventsHandler().message_type == "unsubscribe_project_events"


@pytest.mark.asyncio
async def test_workspace_membership_fails_closed_without_core_verifier() -> None:
    configure_workspace_access_verifier(None)
    context = SimpleNamespace(tenant_id="tenant-1", user_id="user-1")

    assert await _has_workspace_member(context, "workspace-1") is False
