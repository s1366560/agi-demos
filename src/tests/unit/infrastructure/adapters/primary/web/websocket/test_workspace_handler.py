from src.infrastructure.adapters.primary.web.websocket.handlers.project_events_handler import (
    SubscribeProjectEventsHandler,
    UnsubscribeProjectEventsHandler,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.workspace_handler import (
    SubscribeWorkspaceHandler,
    UnsubscribeWorkspaceHandler,
)


def test_workspace_handlers_message_types() -> None:
    assert SubscribeWorkspaceHandler().message_type == "subscribe_workspace"
    assert UnsubscribeWorkspaceHandler().message_type == "unsubscribe_workspace"


def test_project_event_handlers_message_types() -> None:
    assert SubscribeProjectEventsHandler().message_type == "subscribe_project_events"
    assert UnsubscribeProjectEventsHandler().message_type == "unsubscribe_project_events"
