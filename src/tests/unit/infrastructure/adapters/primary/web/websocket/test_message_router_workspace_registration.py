from src.infrastructure.adapters.primary.web.websocket.message_router import get_message_router


def test_message_router_registers_workspace_handlers() -> None:
    router = get_message_router()
    assert "subscribe_workspace" in router.registered_types
    assert "unsubscribe_workspace" in router.registered_types
