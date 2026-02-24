"""Composable tool selection and policy pipeline primitives."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from src.infrastructure.agent.core.tool_selector import (
    CORE_TOOLS,
    ToolSelectionContext as CoreToolSelectionContext,
    get_tool_selector,
)
from src.infrastructure.agent.plugins.policy_context import (
    DEFAULT_POLICY_LAYER_ORDER,
    PolicyContext,
)


@dataclass(frozen=True)
class ToolSelectionContext:
    """Context passed to tool selection pipeline stages."""

    tenant_id: str | None = None
    project_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    policy_context: PolicyContext | None = None


SelectionStage = Callable[[dict[str, Any], ToolSelectionContext], dict[str, Any]]


@dataclass(frozen=True)
class ToolSelectionTraceStep:
    """Trace record for a single selection stage."""

    stage: str
    before_count: int
    after_count: int
    removed_tools: tuple[str, ...] = ()
    added_tools: tuple[str, ...] = ()
    duration_ms: float = 0.0
    explain: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolSelectionResult:
    """Selected tools and per-stage trace."""

    tools: dict[str, Any]
    trace: tuple[ToolSelectionTraceStep, ...] = ()


class ToolSelectionPipeline:
    """Apply ordered tool-selection stages and expose stage-level traces."""

    def __init__(self, stages: list[SelectionStage] | None = None) -> None:
        self._stages = list(stages or [])

    def select_with_trace(
        self,
        tools: dict[str, Any],
        context: ToolSelectionContext | None = None,
    ) -> ToolSelectionResult:
        """Run stages and return selected tools plus trace metadata."""
        current_tools = dict(tools)
        stage_context = context or ToolSelectionContext()
        trace_steps: list[ToolSelectionTraceStep] = []

        for stage in self._stages:
            stage_name = stage.__name__
            before_names = set(current_tools.keys())
            started_at = perf_counter()
            next_tools = stage(current_tools, stage_context)
            duration_ms = (perf_counter() - started_at) * 1000.0
            if not isinstance(next_tools, dict):
                raise TypeError(f"Selection stage {stage.__name__} must return Dict[str, Any]")

            budget_ms = _resolve_stage_latency_budget_ms(
                stage_name,
                metadata=stage_context.metadata,
            )
            budget_exceeded = bool(budget_ms is not None and duration_ms > budget_ms)
            budget_fallback = None
            if budget_exceeded:
                budget_fallback = _resolve_stage_budget_fallback(stage_context.metadata)
                if budget_fallback == "revert":
                    next_tools = dict(current_tools)
                elif budget_fallback == "empty":
                    next_tools = {}

            after_names = set(next_tools.keys())
            removed_tools = tuple(sorted(before_names - after_names))
            added_tools = tuple(sorted(after_names - before_names))
            explain = dict(
                _build_stage_explain(
                    stage_name,
                    before_names=before_names,
                    after_names=after_names,
                    context=stage_context,
                )
            )
            if budget_ms is not None:
                explain["stage_budget_ms"] = budget_ms
            if budget_exceeded:
                explain["budget_exceeded"] = True
                explain["budget_fallback"] = budget_fallback
            trace_steps.append(
                ToolSelectionTraceStep(
                    stage=stage_name,
                    before_count=len(before_names),
                    after_count=len(after_names),
                    removed_tools=removed_tools,
                    added_tools=added_tools,
                    duration_ms=round(duration_ms, 3),
                    explain=explain,
                )
            )
            current_tools = next_tools

        return ToolSelectionResult(tools=current_tools, trace=tuple(trace_steps))

    def select(
        self,
        tools: dict[str, Any],
        context: ToolSelectionContext | None = None,
    ) -> dict[str, Any]:
        """Run all stages in order and return the filtered tool set."""
        return self.select_with_trace(tools, context).tools


def context_filter_stage(
    tools: dict[str, Any],
    context: ToolSelectionContext,
) -> dict[str, Any]:
    """Filter tools by explicit allowlists provided in metadata."""
    allow_names = set(_read_str_list(context.metadata, "tool_names_allowlist"))
    allow_prefixes = tuple(_read_str_list(context.metadata, "tool_prefix_allowlist"))
    if not allow_names and not allow_prefixes:
        return dict(tools)

    filtered: dict[str, Any] = {}
    for name, tool in tools.items():
        if name in CORE_TOOLS:
            filtered[name] = tool
            continue
        if allow_names and name in allow_names:
            filtered[name] = tool
            continue
        if allow_prefixes and name.startswith(allow_prefixes):
            filtered[name] = tool
            continue
    return filtered


def intent_router_stage(
    tools: dict[str, Any],
    context: ToolSelectionContext,
) -> dict[str, Any]:
    """Optional rule-based intent filter (disabled unless explicitly enabled)."""
    if not bool(context.metadata.get("enable_intent_filter", False)):
        return dict(tools)

    query = str(context.metadata.get("user_message", "")).lower()
    if not query:
        return dict(tools)

    intent = _detect_intent(query)
    if intent is None:
        return dict(tools)

    prefixes_map = {
        "web": ("web_", "search", "scrape"),
        "memory": ("memory_",),
        "skill": ("skill_",),
        "mcp": ("mcp__", "register_mcp_server", "sandbox_"),
    }
    matched_prefixes = prefixes_map.get(intent, ())
    filtered: dict[str, Any] = {}
    for name, tool in tools.items():
        if name in CORE_TOOLS:
            filtered[name] = tool
            continue
        if any(name.startswith(prefix) or prefix in name for prefix in matched_prefixes):
            filtered[name] = tool
    return filtered or dict(tools)


def semantic_ranker_stage(
    tools: dict[str, Any],
    context: ToolSelectionContext,
) -> dict[str, Any]:
    """Rank tools by conversation relevance and enforce max_tools budget."""
    max_tools = _resolve_max_tools_budget(
        context.metadata,
        default=40,
        policy_context=_resolve_policy_context(context.metadata, explicit=context.policy_context),
    )
    if len(tools) <= max_tools:
        return dict(tools)

    history = list(context.metadata.get("conversation_history") or [])
    user_message = context.metadata.get("user_message")
    if user_message:
        history.append({"role": "user", "content": str(user_message)})

    selector = get_tool_selector()
    semantic_backend = (
        str(context.metadata.get("semantic_backend", "embedding_vector")).strip().lower()
    )
    selected_names = selector.select_tools(
        tools,
        CoreToolSelectionContext(
            conversation_history=history,
            project_id=context.project_id,
            max_tools=max_tools,
            metadata={
                "user_message": str(user_message or ""),
                "semantic_backend": semantic_backend,
                "semantic_ranker": context.metadata.get("semantic_ranker"),
                "embedding_ranker": context.metadata.get("embedding_ranker"),
                "tool_quality_scores": context.metadata.get("tool_quality_scores"),
                "tool_quality_stats": context.metadata.get("tool_quality_stats"),
            },
        ),
    )
    return {name: tools[name] for name in selected_names if name in tools}


def policy_stage(
    tools: dict[str, Any],
    context: ToolSelectionContext,
) -> dict[str, Any]:
    """Apply allow/deny policy lists provided by upstream policy engines."""
    policy_context = _resolve_policy_context(
        context.metadata,
        explicit=context.policy_context,
    )
    allow_tools, deny_tools, _policy_info = _resolve_policy_lists(
        context.metadata,
        known_tool_names=set(tools.keys()),
        policy_context=policy_context,
    )

    filtered: dict[str, Any] = {}
    for name, tool in tools.items():
        if name in CORE_TOOLS:
            filtered[name] = tool
            continue
        if allow_tools and name not in allow_tools:
            continue
        if name in deny_tools:
            continue
        filtered[name] = tool
    return filtered


def build_default_tool_selection_pipeline() -> ToolSelectionPipeline:
    """Build the default context/intent/semantic/policy pipeline."""
    return ToolSelectionPipeline(
        stages=[
            context_filter_stage,
            intent_router_stage,
            semantic_ranker_stage,
            policy_stage,
        ]
    )


def _read_str_list(metadata: Mapping[str, Any], key: str) -> Sequence[str]:
    value = metadata.get(key)
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)


def _build_stage_explain(
    stage_name: str,
    *,
    before_names: set[str],
    after_names: set[str],
    context: ToolSelectionContext,
) -> Mapping[str, Any]:
    removed = tuple(sorted(before_names - after_names))
    added = tuple(sorted(after_names - before_names))
    explain: dict[str, Any] = {
        "removed_count": len(removed),
        "added_count": len(added),
    }
    if removed:
        explain["removed_sample"] = list(removed[:5])
    if added:
        explain["added_sample"] = list(added[:5])

    metadata = context.metadata
    if stage_name == "context_filter_stage":
        explain["allow_names_count"] = len(_read_str_list(metadata, "tool_names_allowlist"))
        explain["allow_prefixes_count"] = len(_read_str_list(metadata, "tool_prefix_allowlist"))
    elif stage_name == "intent_router_stage":
        enabled = bool(metadata.get("enable_intent_filter", False))
        explain["intent_filter_enabled"] = enabled
        if enabled:
            query = str(metadata.get("user_message", "")).lower()
            if query:
                explain["detected_intent"] = _detect_intent(query)
    elif stage_name == "semantic_ranker_stage":
        policy_context = _resolve_policy_context(metadata, explicit=context.policy_context)
        explain["max_tools"] = _resolve_max_tools_budget(
            metadata,
            default=40,
            policy_context=policy_context,
        )
        history = metadata.get("conversation_history") or ()
        explain["history_messages"] = len(history) if isinstance(history, list) else 0
        semantic_backend = str(metadata.get("semantic_backend", "embedding_vector")).strip().lower()
        explain["semantic_backend"] = semantic_backend
        if semantic_backend == "embedding_vector":
            has_embedding_ranker = bool(
                callable(metadata.get("embedding_ranker"))
                or hasattr(metadata.get("embedding_ranker"), "rank_tools")
            )
            explain["semantic_backend_effective"] = (
                "embedding_vector" if has_embedding_ranker else "token_vector"
            )
    elif stage_name == "policy_stage":
        policy_context = _resolve_policy_context(metadata, explicit=context.policy_context)
        _allow_tools, _deny_tools, policy_info = _resolve_policy_lists(
            metadata,
            known_tool_names=before_names,
            policy_context=policy_context,
        )
        explain["allow_tools_count"] = policy_info.get("allow_tools_count", 0)
        explain["deny_tools_count"] = policy_info.get("deny_tools_count", 0)
        explain["conflicting_tools_count"] = policy_info.get("conflicting_tools_count", 0)
        if policy_info.get("conflicting_tools_sample"):
            explain["conflicting_tools_sample"] = policy_info.get("conflicting_tools_sample", [])
        explain["policy_layers_applied"] = policy_info.get("layers_applied", [])
        explain["policy_layer_order"] = list(policy_context.names)
        explain["unknown_allow_tools_count"] = policy_info.get("unknown_allow_tools_count", 0)
        explain["unknown_deny_tools_count"] = policy_info.get("unknown_deny_tools_count", 0)
    return explain


def _detect_intent(query: str) -> str | None:
    if any(token in query for token in ("search", "web", "scrape", "crawl")):
        return "web"
    if any(token in query for token in ("memory", "recall", "knowledge", "entity")):
        return "memory"
    if any(token in query for token in ("skill", "install skill", "sync skill")):
        return "skill"
    if any(token in query for token in ("mcp", "tool server", "register server")):
        return "mcp"
    return None


def _resolve_max_tools_budget(
    metadata: Mapping[str, Any],
    *,
    default: int,
    policy_context: PolicyContext | None = None,
) -> int:
    budgets: list[int] = []
    top_level_budget = _parse_positive_int(metadata.get("max_tools"))
    if top_level_budget is not None:
        budgets.append(top_level_budget)

    for _layer_name, layer in _iter_policy_layers(
        metadata,
        policy_context=policy_context,
    ):
        layer_budget = _parse_positive_int(layer.get("max_tools"))
        if layer_budget is not None:
            budgets.append(layer_budget)

    if not budgets:
        return default
    return max(1, min(budgets))


def _resolve_policy_lists(
    metadata: Mapping[str, Any],
    *,
    known_tool_names: set[str] | None = None,
    policy_context: PolicyContext | None = None,
) -> tuple[set[str], set[str], Mapping[str, Any]]:
    allow_tools = set(_read_str_list(metadata, "allow_tools"))
    deny_tools = set(_read_str_list(metadata, "deny_tools"))
    layers_applied: list[str] = []

    for layer_name, layer in _iter_policy_layers(metadata, policy_context=policy_context):
        layer_allow = set(_read_str_list(layer, "allow_tools"))
        layer_deny = set(_read_str_list(layer, "deny_tools"))
        if layer_allow or layer_deny:
            layers_applied.append(layer_name)
        allow_tools.update(layer_allow)
        deny_tools.update(layer_deny)

    conflicting_tools = allow_tools & deny_tools
    known_names = set(known_tool_names or set()) | set(CORE_TOOLS)
    unknown_allow_tools = set()
    unknown_deny_tools = set()
    if known_tool_names is not None:
        unknown_allow_tools = {name for name in allow_tools if name not in known_names}
        unknown_deny_tools = {name for name in deny_tools if name not in known_names}

    return (
        allow_tools,
        deny_tools,
        {
            "allow_tools_count": len(allow_tools),
            "deny_tools_count": len(deny_tools),
            "conflicting_tools_count": len(conflicting_tools),
            "conflicting_tools_sample": sorted(conflicting_tools)[:5],
            "layers_applied": layers_applied,
            "unknown_allow_tools_count": len(unknown_allow_tools),
            "unknown_deny_tools_count": len(unknown_deny_tools),
        },
    )


def _iter_policy_layers(
    metadata: Mapping[str, Any],
    *,
    policy_context: PolicyContext | None = None,
) -> Sequence[tuple[str, Mapping[str, Any]]]:
    resolved = _resolve_policy_context(metadata, explicit=policy_context)
    return tuple((layer.name, layer.values) for layer in resolved.layers)


def _resolve_policy_context(
    metadata: Mapping[str, Any],
    *,
    explicit: PolicyContext | None,
) -> PolicyContext:
    if explicit is not None:
        return explicit
    return PolicyContext.from_metadata(metadata, layer_order=DEFAULT_POLICY_LAYER_ORDER)


def _parse_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _resolve_stage_latency_budget_ms(
    stage_name: str,
    *,
    metadata: Mapping[str, Any],
) -> float | None:
    stage_map = metadata.get("stage_latency_budget_ms")
    if isinstance(stage_map, Mapping):
        stage_budget = _parse_positive_float(stage_map.get(stage_name))
        if stage_budget is not None:
            return stage_budget

    return _parse_positive_float(metadata.get("max_stage_latency_ms"))


def _resolve_stage_budget_fallback(metadata: Mapping[str, Any]) -> str:
    fallback = str(metadata.get("stage_budget_fallback", "revert")).strip().lower()
    if fallback not in {"revert", "empty", "keep"}:
        return "revert"
    return fallback


def _parse_positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed
