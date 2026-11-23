"""Carry the admitted HTTP actor into a detached asyncio workflow without retaining the request."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

if TYPE_CHECKING:
    from collections.abc import Iterator

    from src.domain.model.plugins.generated_v2 import ScopeV2

    from .scoped_profile_runtime_v2 import ScopedProfileRuntimeV2


@dataclass(frozen=True)
class WorkflowGraphAuthority:
    runtime: ScopedProfileRuntimeV2
    request_scope: ScopeV2
    actor_id: str


_authority: ContextVar[WorkflowGraphAuthority | None] = ContextVar(
    "workflow_graph_authority", default=None
)


@contextmanager
def bind_workflow_graph(
    runtime: ScopedProfileRuntimeV2 | None, request_scope: ScopeV2, actor_id: str
) -> Iterator[None]:
    value = WorkflowGraphAuthority(runtime, request_scope, actor_id) if runtime else None
    token = _authority.set(value)
    try:
        yield
    finally:
        _authority.reset(token)


def current_workflow_graph() -> WorkflowGraphAuthority:
    authority = _authority.get()
    if authority is None:
        raise RuntimeV2Error(
            "workflow_project_authority_required",
            "Workflow graph requires a project scope authority",
        )
    return authority
