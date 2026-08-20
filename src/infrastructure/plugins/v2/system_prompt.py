"""Generation-scoped system-prompt Provider for the v2 runtime spine."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .runtime import ContextV2, PluginDefinitionV2

SYSTEM_PROMPT_MODULE_V2 = "builtin://memstack/agent/system-prompt"
SYSTEM_PROMPT_BUILDER_SERVICE_V2 = "service:system-prompt-builder"


@dataclass(frozen=True, kw_only=True)
class SystemPromptBuilderV2:
    """Invoke the active prompt manager through a generation-owned service seam."""

    strategy: str

    async def build(
        self,
        *,
        manager: object,
        context: object,
        subagent: object | None,
    ) -> str:
        build = getattr(manager, "build_system_prompt", None)
        if not callable(build):
            raise TypeError("system prompt manager has no callable build_system_prompt")
        result = build(context=context, subagent=subagent)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, str):
            raise TypeError("system prompt manager must return a string")
        return result


def _apply_system_prompt_builder_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "system-prompt-manager":
        raise ValueError("system prompt provider requires strategy system-prompt-manager")
    context.provide(
        SYSTEM_PROMPT_BUILDER_SERVICE_V2,
        SystemPromptBuilderV2(strategy=strategy),
        label="system-prompt-builder",
    )


def builtin_system_prompt_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=SYSTEM_PROMPT_MODULE_V2,
        apply=_apply_system_prompt_builder_v2,
        provides=(SYSTEM_PROMPT_BUILDER_SERVICE_V2,),
    )


__all__ = [
    "SYSTEM_PROMPT_BUILDER_SERVICE_V2",
    "SYSTEM_PROMPT_MODULE_V2",
    "SystemPromptBuilderV2",
    "builtin_system_prompt_definition_v2",
]
