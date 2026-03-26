from src.domain.events.types import AgentEventType
from src.infrastructure.adapters.primary.web.routers.workspace_events import (
    build_workspace_routing_key,
)


def test_build_workspace_routing_key_uses_colon_convention() -> None:
    assert (
        build_workspace_routing_key("ws-1", AgentEventType.TOPOLOGY_UPDATED.value)
        == "workspace:ws-1:topology_updated"
    )
