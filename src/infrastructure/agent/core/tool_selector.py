"""Agent-backed tool filtering for LLM context optimization.

Structural allowlists remain deterministic. Subjective budget pruning happens
only when an explicit Agent ranker is injected; otherwise the complete tool set
is preserved.
"""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from src.infrastructure.logging_redaction import redact_sensitive_log_text

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("agent_decision_audit")


# Core tools that should always be included
CORE_TOOLS: set[str] = {
    "read",
    "write",
    "edit",
    "bash",
    "glob",
    "grep",
    "todoread",
    "todowrite",
    "skill_loader",
}

# Skill management tools that should survive semantic budget pruning.
# skill_loader is in CORE_TOOLS (always available).
# skill_installer and skill_sync are NOT in CORE_TOOLS so that
# policy deny lists (e.g. plan mode) can still block them.
SKILL_TOOLS: set[str] = {
    "skill_loader",
    "skill_installer",
    "skill_sync",
}


@dataclass
class ToolSelectionContext:
    """Context for tool selection decisions.

    Provides the information needed to make intelligent
    decisions about which tools are most relevant.
    """

    conversation_history: list[dict[str, str]] = field(default_factory=list)
    project_id: str | None = None
    max_tools: int = 30
    always_include: set[str] = field(default_factory=lambda: CORE_TOOLS)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ToolRankingAuditV2:
    """Complete audit envelope for one Agent tool-ranking judgment."""

    agent_id: str
    tool_name: str
    input_json: Mapping[str, Any]
    output_json: Mapping[str, Any]
    rationale: str
    latency_ms: int


@dataclass(frozen=True, kw_only=True)
class ToolRankingDecisionV2:
    """Validated Agent ordering plus its structured tool-call audit."""

    ordered_tool_names: tuple[str, ...]
    audit: ToolRankingAuditV2


@runtime_checkable
class SemanticToolRanker(Protocol):
    """Protocol for an audited structured-tool-call ranking authority."""

    name: str
    decision_mode: str
    audit_enabled: bool

    def rank_tools(
        self,
        tools: dict[str, Any],
        context: ToolSelectionContext,
    ) -> ToolRankingDecisionV2:
        """Return the Agent ordering and complete decision audit."""
        ...


class ToolSelector:
    """Selects the most relevant tools based on context.

    When the number of available tools exceeds a limit,
    this selector ranks and filters tools to reduce LLM
    context consumption while preserving functionality.
    """

    def select_tools(
        self,
        tools: dict[str, Any],
        context: ToolSelectionContext,
    ) -> list[str]:
        """Select the most relevant tools.

        Args:
            tools: Dict of tool name -> tool object
            context: Selection context with history and limits

        Returns:
            List of selected tool names
        """
        # If under limit, return all
        if len(tools) <= context.max_tools:
            return list(tools.keys())

        ranker = self._resolve_semantic_ranker(context)
        if ranker is None:
            logger.debug(
                "Tool budget exceeded without an Agent ranker; preserving all %d tools",
                len(tools),
            )
            return list(tools)
        ranked_names = self._rank_with_backend(
            ranker,
            tools,
            context,
        )
        if ranked_names is None:
            return list(tools)

        # Select top tools
        selected = []
        always_include = context.always_include or CORE_TOOLS

        # First, add all always-include tools
        for name in tools:
            if name in always_include:
                selected.append(name)

        # Then add ranked tools until we hit the limit
        for name in ranked_names:
            if name not in selected:
                selected.append(name)
                if len(selected) >= context.max_tools:
                    break

        logger.debug(
            "Selected %d/%d tools (always_include: %d, semantic_backend: %s)",
            len(selected),
            len(tools),
            len(always_include & set(tools.keys())),
            getattr(ranker, "name", "unknown"),
        )

        return selected

    def _resolve_semantic_ranker(
        self,
        context: ToolSelectionContext,
    ) -> SemanticToolRanker | None:
        metadata = context.metadata if isinstance(context.metadata, Mapping) else {}
        backend = str(metadata.get("semantic_backend", "")).strip().lower()
        if backend != "agent_decision":
            if backend:
                logger.debug("Ignoring non-Agent tool ranking backend: %s", backend)
            return None

        custom_ranker = metadata.get("semantic_ranker")
        if (
            isinstance(custom_ranker, SemanticToolRanker)
            and custom_ranker.decision_mode == "structured_tool_call"
            and custom_ranker.audit_enabled is True
        ):
            return custom_ranker
        if custom_ranker is not None:
            logger.warning(
                "Ignoring tool ranker without the structured decision and audit contract"
            )
        return None

    def _rank_with_backend(
        self,
        ranker: SemanticToolRanker,
        tools: dict[str, Any],
        context: ToolSelectionContext,
    ) -> list[str] | None:
        try:
            decision = ranker.rank_tools(tools, context)
        except Exception:
            logger.exception("Agent tool ranker failed; preserving the complete tool set")
            return None

        if not isinstance(decision, ToolRankingDecisionV2):
            logger.warning("Agent tool ranker returned no structured decision; preserving all")
            return None
        ranked_names = decision.ordered_tool_names
        audit = decision.audit
        if (
            not isinstance(ranked_names, tuple)
            or not all(isinstance(name, str) and name in tools for name in ranked_names)
            or len(ranked_names) != len(set(ranked_names))
            or not _is_valid_tool_ranking_audit_v2(
                audit,
                candidate_tool_names=tuple(tools),
                ordered_tool_names=ranked_names,
            )
        ):
            logger.warning("Agent tool ranker returned an invalid decision; preserving all")
            return None
        _log_tool_ranking_audit_v2(audit)
        return list(ranked_names)


def _is_valid_tool_ranking_audit_v2(
    audit: object,
    *,
    candidate_tool_names: tuple[str, ...],
    ordered_tool_names: tuple[str, ...],
) -> bool:
    if not isinstance(audit, ToolRankingAuditV2):
        return False
    return bool(
        audit.agent_id.strip()
        and audit.tool_name.strip()
        and isinstance(audit.input_json, Mapping)
        and audit.input_json.get("candidate_tool_names") == list(candidate_tool_names)
        and isinstance(audit.output_json, Mapping)
        and audit.output_json.get("ordered_tool_names") == list(ordered_tool_names)
        and audit.rationale.strip()
        and isinstance(audit.latency_ms, int)
        and not isinstance(audit.latency_ms, bool)
        and audit.latency_ms >= 0
    )


def _log_tool_ranking_audit_v2(audit: ToolRankingAuditV2) -> None:
    audit_logger.info(
        "Agent tool ranking judgment completed",
        extra={
            "agent_id": audit.agent_id,
            "tool_name": audit.tool_name,
            "input": _redacted_audit_json_v2(audit.input_json),
            "output": _redacted_audit_json_v2(audit.output_json),
            "rationale": redact_sensitive_log_text(audit.rationale),
            "latency_ms": audit.latency_ms,
        },
    )


def _redacted_audit_json_v2(value: Mapping[str, Any]) -> str:
    return redact_sensitive_log_text(
        json.dumps(dict(value), ensure_ascii=False, sort_keys=True, default=str)
    )


# Global selector instance
_selector: ToolSelector | None = None


def get_tool_selector() -> ToolSelector:
    """Get the global tool selector instance.

    Returns:
        ToolSelector singleton
    """
    global _selector
    if _selector is None:
        _selector = ToolSelector()
    return _selector
