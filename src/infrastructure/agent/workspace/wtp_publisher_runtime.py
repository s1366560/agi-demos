"""Invocation-local binding for the generation-selected WTP publisher."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Protocol, runtime_checkable

from src.domain.model.workspace.wtp_envelope import WtpEnvelope


@runtime_checkable
class WorkspaceWtpPublisherProtocolV2(Protocol):
    """Publish one typed Workspace Task Protocol envelope."""

    async def publish(self, envelope: WtpEnvelope) -> str | None: ...


_publisher_context_v2: ContextVar[WorkspaceWtpPublisherProtocolV2 | None] = ContextVar(
    f"{__name__}.publisher",
    default=None,
)


@contextmanager
def bind_workspace_wtp_publisher_v2(
    publisher: object,
) -> Iterator[None]:
    """Bind one Profile-injected publisher for a single tool invocation."""
    if not isinstance(publisher, WorkspaceWtpPublisherProtocolV2):
        from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

        raise RuntimeV2Error(
            "invalid_workspace_wtp_publisher",
            "Workspace WTP publisher binding has an invalid implementation",
        )
    token = _publisher_context_v2.set(publisher)
    try:
        yield
    finally:
        _publisher_context_v2.reset(token)


def current_workspace_wtp_publisher_v2() -> WorkspaceWtpPublisherProtocolV2:
    """Resolve only the publisher explicitly bound by the active V2 contribution."""
    publisher = _publisher_context_v2.get()
    if publisher is None:
        from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

        raise RuntimeV2Error(
            "workspace_wtp_publisher_not_bound",
            "Workspace WTP publishing requires the active V2 tool contribution",
        )
    return publisher


__all__ = [
    "WorkspaceWtpPublisherProtocolV2",
    "bind_workspace_wtp_publisher_v2",
    "current_workspace_wtp_publisher_v2",
]
