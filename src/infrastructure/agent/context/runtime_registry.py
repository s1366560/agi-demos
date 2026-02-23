"""Runtime registry wiring for context policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from src.infrastructure.agent.context.policy_registry import (
    ContextPolicyRegistry,
    dedupe_cached_summary_messages,
    enrich_summary_with_file_activity,
    enrich_summary_with_tool_failures,
)


@dataclass(frozen=True)
class ContextRuntimeConfig:
    """Flags for built-in context policy registration."""

    enabled: bool = True
    enable_cache_prune_policy: bool = True
    enable_tool_failure_summary_policy: bool = True
    enable_file_activity_summary_policy: bool = True


class ContextRuntimeRegistry:
    """Applies registered context policies during context construction."""

    def __init__(
        self,
        registry: ContextPolicyRegistry | None = None,
    ) -> None:
        self._registry = registry or ContextPolicyRegistry()

    @property
    def registry(self) -> ContextPolicyRegistry:
        return self._registry

    @classmethod
    def with_defaults(
        cls,
        config: ContextRuntimeConfig | None = None,
    ) -> ContextRuntimeRegistry:
        cfg = config or ContextRuntimeConfig()
        registry = ContextPolicyRegistry()
        if cfg.enabled:
            if cfg.enable_cache_prune_policy:
                registry.register_pre_compression(
                    "dedupe_cached_summary_messages",
                    dedupe_cached_summary_messages,
                )
            if cfg.enable_tool_failure_summary_policy:
                registry.register_summary_enrichment(
                    "enrich_summary_with_tool_failures",
                    enrich_summary_with_tool_failures,
                )
            if cfg.enable_file_activity_summary_policy:
                registry.register_summary_enrichment(
                    "enrich_summary_with_file_activity",
                    enrich_summary_with_file_activity,
                )
        return cls(registry=registry)

    def apply_pre_compression(
        self,
        messages: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        return self._registry.apply_pre_compression(messages)

    def apply_summary_enrichment(
        self,
        summary_text: str,
        messages: List[Dict[str, Any]],
    ) -> tuple[str, Dict[str, Any]]:
        return self._registry.apply_summary_enrichment(summary_text, messages)

