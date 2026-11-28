"""A release and permission epoch fixed at project operation admission."""

from contextvars import ContextVar
from dataclasses import dataclass

from pydantic import TypeAdapter


@dataclass(frozen=True, kw_only=True)
class AgentPackagePin:
    tenant_id: str
    project_id: str
    plugin_id: str
    version: str
    digest: str
    authorization_epoch: int
    drives_agent_loop: bool = False
    chat_adapter: bool = False
    chat_provider: str | None = None


AGENT_PACKAGE_PINS = TypeAdapter(tuple[AgentPackagePin, ...])

ACTIVE_APPLICATION_PIN: ContextVar[AgentPackagePin | None] = ContextVar(
    "active_application_pin", default=None
)
