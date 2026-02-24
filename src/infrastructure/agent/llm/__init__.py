"""
LLM streaming utilities for ReActAgent.

This package provides unified streaming interface for LLM responses:
- Text generation (streaming deltas)
- Tool calls (function calling)
- Reasoning/thinking tokens
- Token usage tracking
- Provider-specific metadata handling
- High-level LLM invocation with retry (LLMInvoker)
"""

from src.infrastructure.agent.llm.token_sampler import (
    BatchLogBuffer,
    TokenDeltaSampler,
)

__all__ = [
    "BatchLogBuffer",
    "InvocationConfig",
    "InvocationContext",
    "InvocationResult",
    "InvokerState",
    # LLM Invoker - lazy loaded to avoid circular imports
    "LLMInvoker",
    # Token sampling
    "TokenDeltaSampler",
    "TokenUsage",
    "create_llm_invoker",
    "get_llm_invoker",
    "set_llm_invoker",
]


def __getattr__(name: str):
    """Lazy import components to avoid circular imports."""
    # LLM stream components
    if name in (
        "MODEL_PROVIDER_MAP",
        "LLMStream",
        "StreamConfig",
        "StreamEvent",
        "StreamEventType",
        "ToolCallChunk",
        "create_stream",
        "infer_provider_from_model",
    ):
        from src.infrastructure.agent.core import llm_stream

        return getattr(llm_stream, name)

    # LLM Invoker components
    if name in (
        "LLMInvoker",
        "InvocationConfig",
        "InvocationContext",
        "InvocationResult",
        "InvokerState",
        "TokenUsage",
        "get_llm_invoker",
        "set_llm_invoker",
        "create_llm_invoker",
    ):
        from src.infrastructure.agent.llm import invoker

        return getattr(invoker, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
