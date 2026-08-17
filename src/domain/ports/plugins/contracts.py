"""Stable capability ports supplied by platform plugins."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from src.domain.model.plugins import CredentialReference, PluginScopeContext

JsonMapping = Mapping[str, Any]


@dataclass(frozen=True)
class ToolDescriptor:
    """Model-facing description of one tool capability."""

    id: str
    name: str
    description: str
    parameters: JsonMapping = field(default_factory=dict)
    permission: str | None = None
    source_plugin: str = "kernel"
    category: str = "builtin"
    tags: tuple[str, ...] = ()


@runtime_checkable
class ToolImplementation(Protocol):
    """Minimal executable contract used by the tool pipeline."""

    async def __call__(
        self,
        arguments: Mapping[str, Any],
        scope: PluginScopeContext,
    ) -> object: ...


@runtime_checkable
class ToolProvider(Protocol):
    """Service Definition for tool enumeration and construction."""

    async def list_tools(self, scope: PluginScopeContext) -> Sequence[ToolDescriptor]: ...

    async def build_tool(
        self,
        tool_id: str,
        scope: PluginScopeContext,
    ) -> ToolImplementation: ...


@dataclass(frozen=True)
class SkillDescriptor:
    """Metadata used for skill routing and prompt assembly."""

    id: str
    name: str
    source_plugin: str
    scope: str
    content_ref: str
    trigger: JsonMapping = field(default_factory=dict)
    required_tools: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillDefinition:
    """Fully loaded skill content."""

    descriptor: SkillDescriptor
    content: str


@runtime_checkable
class SkillProvider(Protocol):
    """Service Definition for tiered skill loading."""

    async def list_skills(self, scope: PluginScopeContext) -> Sequence[SkillDescriptor]: ...

    async def load_skill(
        self,
        skill_id: str,
        scope: PluginScopeContext,
    ) -> SkillDefinition: ...


@dataclass(frozen=True)
class SubagentDescriptor:
    """Model-facing description of a delegated agent provider."""

    id: str
    name: str
    description: str
    source_plugin: str
    required_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class SubagentStartRequest:
    """Kernel-validated request to start one delegated agent run."""

    provider_id: str
    scope: PluginScopeContext
    objective: str
    parent_run_id: str | None = None
    lineage_depth: int = 0
    input_payload: JsonMapping = field(default_factory=dict)


@dataclass(frozen=True)
class SubagentHandle:
    """Opaque identity of a running delegated agent."""

    run_id: str
    provider_id: str
    lineage_id: str


@dataclass(frozen=True)
class SubagentResult:
    """Terminal outcome returned by a provider."""

    run_id: str
    output: str
    is_error: bool = False
    metadata: JsonMapping = field(default_factory=dict)


@runtime_checkable
class SubagentProvider(Protocol):
    """Service Definition for delegated agent execution."""

    async def list_subagents(
        self,
        scope: PluginScopeContext,
    ) -> Sequence[SubagentDescriptor]: ...

    async def start(self, request: SubagentStartRequest) -> SubagentHandle: ...

    async def continue_(
        self,
        handle: SubagentHandle,
        message: str,
    ) -> SubagentResult: ...


@dataclass(frozen=True)
class RetryPolicyContract:
    """Provider-neutral retry facts resolved per request."""

    max_attempts: int = 3
    initial_delay_ms: int = 200
    max_delay_ms: int = 10_000


@dataclass(frozen=True)
class ResolvedLlmRoute:
    """Complete route facts resolved for one model request.

    The credential is a reference only. Provider implementations receive a
    short-lived lease from the execution boundary, never this persisted route.
    """

    provider_id: str
    model_id: str
    base_url: str
    credential: CredentialReference
    timeout_ms: int
    context_window: int
    max_output_tokens: int
    retry_policy: RetryPolicyContract = field(default_factory=RetryPolicyContract)


@dataclass(frozen=True)
class LlmChunk:
    """Provider-neutral streaming chunk."""

    delta: str = ""
    finish_reason: str | None = None
    usage: JsonMapping = field(default_factory=dict)


@runtime_checkable
class LlmProviderCapability(Protocol):
    """Service Definition for streaming model calls."""

    async def stream(
        self,
        route: ResolvedLlmRoute,
        messages: Sequence[Mapping[str, Any]],
    ) -> AsyncIterator[LlmChunk]: ...


@dataclass(frozen=True)
class EmbeddingResult:
    """One provider-neutral embedding batch."""

    vectors: tuple[tuple[float, ...], ...]
    dimension: int
    model_id: str


@runtime_checkable
class EmbedderCapability(Protocol):
    """Service Definition for embedding generation."""

    async def embed(
        self,
        route: ResolvedLlmRoute,
        inputs: Sequence[str],
    ) -> EmbeddingResult: ...


@dataclass(frozen=True)
class RerankResult:
    """Provider-neutral reranking output."""

    scores: tuple[float, ...]
    model_id: str


@runtime_checkable
class RerankerCapability(Protocol):
    """Service Definition for normalized relevance scoring."""

    async def rerank(
        self,
        route: ResolvedLlmRoute,
        query: str,
        passages: Sequence[str],
    ) -> RerankResult: ...
