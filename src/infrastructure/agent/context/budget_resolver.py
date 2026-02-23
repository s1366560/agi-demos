"""Context budget resolver for model-aware context window governance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.infrastructure.llm.model_registry import clamp_max_tokens, get_model_context_window


@dataclass(frozen=True)
class ContextBudgetProfile:
    """Resolved context/output/input token budgets for a model."""

    model: str
    context_window_tokens: int
    output_tokens: int
    input_budget_tokens: int
    source: str
    warn_below_tokens: int
    hard_min_tokens: int
    should_warn: bool
    should_block: bool
    metadata: dict[str, Any] = field(default_factory=dict)


class ContextBudgetResolver:
    """Resolve runtime context budgets with warn/block thresholds."""

    def __init__(
        self,
        *,
        warn_below_tokens: int = 32_000,
        hard_min_tokens: int = 16_000,
    ) -> None:
        self._warn_below_tokens = max(1, int(warn_below_tokens))
        self._hard_min_tokens = max(1, int(hard_min_tokens))

    def resolve(
        self,
        *,
        model: str,
        requested_output_tokens: int,
        requested_context_tokens: Optional[int] = None,
    ) -> ContextBudgetProfile:
        """Resolve context window and output budget for a model."""
        normalized_model = model.strip() if isinstance(model, str) and model.strip() else "unknown"
        model_context_tokens = int(get_model_context_window(normalized_model))
        source = "model_registry"

        if isinstance(requested_context_tokens, int) and requested_context_tokens > 0:
            if requested_context_tokens < model_context_tokens:
                model_context_tokens = requested_context_tokens
                source = "configured_cap"

        output_tokens = max(1, int(requested_output_tokens))
        output_tokens = int(clamp_max_tokens(normalized_model, output_tokens))
        if output_tokens >= model_context_tokens:
            output_tokens = max(1, model_context_tokens // 4)

        input_budget_tokens = max(1, model_context_tokens - output_tokens)
        should_warn = 0 < model_context_tokens < self._warn_below_tokens
        should_block = 0 < model_context_tokens < self._hard_min_tokens

        return ContextBudgetProfile(
            model=normalized_model,
            context_window_tokens=model_context_tokens,
            output_tokens=output_tokens,
            input_budget_tokens=input_budget_tokens,
            source=source,
            warn_below_tokens=self._warn_below_tokens,
            hard_min_tokens=self._hard_min_tokens,
            should_warn=should_warn,
            should_block=should_block,
            metadata={
                "requested_output_tokens": int(requested_output_tokens),
                "requested_context_tokens": requested_context_tokens,
            },
        )

