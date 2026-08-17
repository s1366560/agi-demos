"""Provider contracts for external I/O and replaceable backend capabilities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from src.domain.model.plugins import PluginScopeContext


@dataclass(frozen=True)
class ChannelMessage:
    """Provider-neutral inbound channel message."""

    channel_type: str
    external_id: str
    tenant_id: str
    project_id: str | None
    sender_id: str
    content: str
    attachments: Sequence[Mapping[str, Any]] = ()


@dataclass(frozen=True)
class ChannelSendRequest:
    """Provider-neutral outbound channel request."""

    channel_type: str
    external_conversation_id: str
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class ChannelProviderCapability(Protocol):
    """Service Definition for an IM or external channel adapter."""

    async def receive(self, scope: PluginScopeContext) -> Sequence[ChannelMessage]: ...

    async def send(self, scope: PluginScopeContext, request: ChannelSendRequest) -> None: ...


@runtime_checkable
class GraphBackendCapability(Protocol):
    """Service Definition for a project-scoped knowledge graph backend."""

    async def query(
        self,
        scope: PluginScopeContext,
        query: str,
        parameters: Mapping[str, Any],
    ) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class RetrievalMatch:
    """One normalized retrieval result."""

    id: str
    score: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class RetrievalBackendCapability(Protocol):
    """Service Definition for tenant/project-scoped retrieval."""

    async def search(
        self,
        scope: PluginScopeContext,
        query: str,
        top_k: int,
    ) -> Sequence[RetrievalMatch]: ...


@runtime_checkable
class StorageBackendCapability(Protocol):
    """Service Definition for binary/object storage."""

    async def put(
        self,
        scope: PluginScopeContext,
        key: str,
        content: bytes,
        content_type: str,
    ) -> str: ...

    async def get(
        self,
        scope: PluginScopeContext,
        key: str,
    ) -> bytes: ...


@runtime_checkable
class WorkflowEngineCapability(Protocol):
    """Service Definition for workflow execution."""

    async def execute(
        self,
        scope: PluginScopeContext,
        workflow_id: str,
        input: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


@runtime_checkable
class TelemetryExporterCapability(Protocol):
    """Service Definition for telemetry export."""

    async def export(
        self,
        scope: PluginScopeContext,
        records: Sequence[Mapping[str, Any]],
    ) -> None: ...
