from src.infrastructure.adapters.primary.web.websocket.handlers.workspace_handler import (
    SubscribeWorkspaceHandler,
    UnsubscribeWorkspaceHandler,
)


def test_workspace_handlers_message_types() -> None:
    assert SubscribeWorkspaceHandler().message_type == "subscribe_workspace"
    assert UnsubscribeWorkspaceHandler().message_type == "unsubscribe_workspace"
