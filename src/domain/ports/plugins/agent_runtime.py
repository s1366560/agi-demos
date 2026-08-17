"""Agent loop and system prompt capability contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from src.domain.model.plugins import PluginScopeContext


@dataclass(frozen=True)
class AgentInvocation:
    """One immutable request to an agent loop."""

    run_id: str
    scope: PluginScopeContext
    objective: str
    history: Sequence[Mapping[str, Any]] = ()
    tool_ids: tuple[str, ...] = ()
    configuration: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentEvent:
    """Provider-neutral event yielded by an agent loop."""

    type: str
    run_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class AgentLoopCapability(Protocol):
    """Service Definition for a trusted agent loop driver."""

    async def run(self, invocation: AgentInvocation) -> AsyncIterator[AgentEvent]: ...

    async def cancel(self, run_id: str) -> None: ...


@dataclass(frozen=True)
class PromptSection:
    """One ordered, model-visible prompt contribution."""

    id: str
    source_plugin: str
    content: str
    priority: int = 100


@runtime_checkable
class SystemPromptContributor(Protocol):
    """Contributor that can expose only a bounded prompt section."""

    async def sections(self, scope: PluginScopeContext) -> tuple[PromptSection, ...]: ...
