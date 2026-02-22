"""Composable tool selection and policy pipeline primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from src.infrastructure.agent.core.tool_selector import (
    CORE_TOOLS,
    ToolSelectionContext as CoreToolSelectionContext,
    get_tool_selector,
)


@dataclass(frozen=True)
class ToolSelectionContext:
    """Context passed to tool selection pipeline stages."""

    tenant_id: Optional[str] = None
    project_id: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


SelectionStage = Callable[[Dict[str, Any], ToolSelectionContext], Dict[str, Any]]


@dataclass(frozen=True)
class ToolSelectionTraceStep:
    """Trace record for a single selection stage."""

    stage: str
    before_count: int
    after_count: int
    removed_tools: tuple[str, ...] = ()
    added_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolSelectionResult:
    """Selected tools and per-stage trace."""

    tools: Dict[str, Any]
    trace: tuple[ToolSelectionTraceStep, ...] = ()


class ToolSelectionPipeline:
    """Apply ordered tool-selection stages and expose stage-level traces."""

    def __init__(self, stages: Optional[list[SelectionStage]] = None) -> None:
        self._stages = list(stages or [])

    def select_with_trace(
        self,
        tools: Dict[str, Any],
        context: Optional[ToolSelectionContext] = None,
    ) -> ToolSelectionResult:
        """Run stages and return selected tools plus trace metadata."""
        current_tools = dict(tools)
        stage_context = context or ToolSelectionContext()
        trace_steps: list[ToolSelectionTraceStep] = []

        for stage in self._stages:
            before_names = set(current_tools.keys())
            next_tools = stage(current_tools, stage_context)
            if not isinstance(next_tools, dict):
                raise TypeError(f"Selection stage {stage.__name__} must return Dict[str, Any]")

            after_names = set(next_tools.keys())
            trace_steps.append(
                ToolSelectionTraceStep(
                    stage=stage.__name__,
                    before_count=len(before_names),
                    after_count=len(after_names),
                    removed_tools=tuple(sorted(before_names - after_names)),
                    added_tools=tuple(sorted(after_names - before_names)),
                )
            )
            current_tools = next_tools

        return ToolSelectionResult(tools=current_tools, trace=tuple(trace_steps))

    def select(
        self,
        tools: Dict[str, Any],
        context: Optional[ToolSelectionContext] = None,
    ) -> Dict[str, Any]:
        """Run all stages in order and return the filtered tool set."""
        return self.select_with_trace(tools, context).tools


def context_filter_stage(
    tools: Dict[str, Any],
    context: ToolSelectionContext,
) -> Dict[str, Any]:
    """Filter tools by explicit allowlists provided in metadata."""
    allow_names = set(_read_str_list(context.metadata, "tool_names_allowlist"))
    allow_prefixes = tuple(_read_str_list(context.metadata, "tool_prefix_allowlist"))
    if not allow_names and not allow_prefixes:
        return dict(tools)

    filtered: Dict[str, Any] = {}
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
    tools: Dict[str, Any],
    context: ToolSelectionContext,
) -> Dict[str, Any]:
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
    filtered: Dict[str, Any] = {}
    for name, tool in tools.items():
        if name in CORE_TOOLS:
            filtered[name] = tool
            continue
        if any(name.startswith(prefix) or prefix in name for prefix in matched_prefixes):
            filtered[name] = tool
    return filtered or dict(tools)


def semantic_ranker_stage(
    tools: Dict[str, Any],
    context: ToolSelectionContext,
) -> Dict[str, Any]:
    """Rank tools by conversation relevance and enforce max_tools budget."""
    max_tools_raw = context.metadata.get("max_tools")
    try:
        max_tools = int(max_tools_raw) if max_tools_raw is not None else 40
    except (TypeError, ValueError):
        max_tools = 40
    if max_tools <= 0:
        max_tools = 40
    if len(tools) <= max_tools:
        return dict(tools)

    history = list(context.metadata.get("conversation_history") or [])
    user_message = context.metadata.get("user_message")
    if user_message:
        history.append({"role": "user", "content": str(user_message)})

    selector = get_tool_selector()
    selected_names = selector.select_tools(
        tools,
        CoreToolSelectionContext(
            conversation_history=history,
            project_id=context.project_id,
            max_tools=max_tools,
        ),
    )
    return {name: tools[name] for name in selected_names if name in tools}


def policy_stage(
    tools: Dict[str, Any],
    context: ToolSelectionContext,
) -> Dict[str, Any]:
    """Apply allow/deny policy lists provided by upstream policy engines."""
    allow_tools = set(_read_str_list(context.metadata, "allow_tools"))
    deny_tools = set(_read_str_list(context.metadata, "deny_tools"))

    filtered: Dict[str, Any] = {}
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


def _detect_intent(query: str) -> Optional[str]:
    if any(token in query for token in ("search", "web", "scrape", "crawl")):
        return "web"
    if any(token in query for token in ("memory", "recall", "knowledge", "entity")):
        return "memory"
    if any(token in query for token in ("skill", "install skill", "sync skill")):
        return "skill"
    if any(token in query for token in ("mcp", "tool server", "register server")):
        return "mcp"
    return None
