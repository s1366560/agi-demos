"""Unit tests for tool selection/policy pipeline."""

import time
from types import SimpleNamespace

import pytest

from src.infrastructure.agent.core.tool_selector import (
    ToolRankingAuditV2,
    ToolRankingDecisionV2,
)
from src.infrastructure.agent.plugins.selection_pipeline import (
    ToolSelectionContext,
    ToolSelectionPipeline,
    build_default_tool_selection_pipeline,
)


@pytest.mark.unit
def test_default_pipeline_preserves_tools_without_agent_ranker_and_emits_trace() -> None:
    """Semantic stage must not prune user MCP tools without an Agent verdict.

    System built-in tools (non mcp__* prefix) are always included.
    User MCP tools may exceed the optimization budget when no judge is available.
    """
    pipeline = build_default_tool_selection_pipeline()
    tools = {
        f"mcp__srv__tool_{idx}": SimpleNamespace(name=f"mcp__srv__tool_{idx}", description="desc")
        for idx in range(30)
    }
    tools["read"] = SimpleNamespace(name="read", description="Read files")
    tools["write"] = SimpleNamespace(name="write", description="Write files")

    result = pipeline.select_with_trace(
        tools,
        ToolSelectionContext(
            tenant_id="tenant-1",
            project_id="project-1",
            metadata={
                "user_message": "read file",
                "conversation_history": [{"role": "user", "content": "read file"}],
                "max_tools": 5,
            },
        ),
    )

    mcp_tools = [n for n in result.tools if n.startswith("mcp__")]
    assert len(mcp_tools) == 30
    assert "read" in result.tools
    assert "write" in result.tools
    assert any(step.stage == "semantic_ranker_stage" for step in result.trace)
    assert all(step.duration_ms >= 0 for step in result.trace)
    semantic = next(step for step in result.trace if step.stage == "semantic_ranker_stage")
    assert semantic.explain.get("max_tools") == 5


@pytest.mark.unit
def test_policy_stage_respects_deny_list() -> None:
    """Policy stage should remove tools present in deny list."""
    pipeline = build_default_tool_selection_pipeline()
    tools = {
        "read": SimpleNamespace(name="read", description="Read files"),
        "register_mcp_server": SimpleNamespace(name="register_mcp_server", description="register"),
    }

    result = pipeline.select_with_trace(
        tools,
        ToolSelectionContext(
            metadata={
                "deny_tools": ["register_mcp_server"],
                "max_tools": 10,
            }
        ),
    )

    assert "read" in result.tools
    assert "register_mcp_server" not in result.tools
    policy = next(step for step in result.trace if step.stage == "policy_stage")
    assert policy.explain.get("deny_tools_count") == 1


@pytest.mark.unit
def test_policy_stage_merges_layered_allow_and_deny() -> None:
    """Policy stage should merge layered policy metadata and honor deny over allow."""
    pipeline = build_default_tool_selection_pipeline()
    tools = {
        "read": SimpleNamespace(name="read", description="Read files"),
        "web_search": SimpleNamespace(name="web_search", description="Search web"),
        "memory_search": SimpleNamespace(name="memory_search", description="Search memory"),
    }

    result = pipeline.select_with_trace(
        tools,
        ToolSelectionContext(
            metadata={
                "policy_layers": {
                    "tenant": {"allow_tools": ["web_search", "memory_search"]},
                    "agent": {"deny_tools": ["memory_search"]},
                }
            }
        ),
    )

    assert "web_search" in result.tools
    assert "memory_search" not in result.tools
    policy = next(step for step in result.trace if step.stage == "policy_stage")
    assert "tenant" in policy.explain.get("policy_layers_applied", [])
    assert "agent" in policy.explain.get("policy_layers_applied", [])
    assert policy.explain.get("conflicting_tools_count") == 1
    assert "memory_search" in policy.explain.get("conflicting_tools_sample", [])


@pytest.mark.unit
def test_policy_stage_normalizes_ui_style_tool_names() -> None:
    """Agent allowlists may use UI names while runtime tools are snake_case."""
    pipeline = build_default_tool_selection_pipeline()
    tools = {
        "read": SimpleNamespace(name="read", description="Read files"),
        "grep": SimpleNamespace(name="grep", description="Search files"),
        "web_search": SimpleNamespace(name="web_search", description="Search web"),
        "web_scrape": SimpleNamespace(name="web_scrape", description="Fetch web page"),
        "memory_search": SimpleNamespace(name="memory_search", description="Search memory"),
    }

    result = pipeline.select_with_trace(
        tools,
        ToolSelectionContext(
            metadata={
                "allow_tools": ["Read", "Grep", "WebSearch", "WebFetch"],
            }
        ),
    )

    assert {"read", "grep", "web_search", "web_scrape"}.issubset(result.tools)
    assert "memory_search" not in result.tools
    policy = next(step for step in result.trace if step.stage == "policy_stage")
    assert policy.explain.get("unknown_allow_tools_count") == 0


@pytest.mark.unit
def test_semantic_stage_layered_budget_does_not_replace_agent_judgment() -> None:
    """Layered budgets are triggers, not subjective pruning verdicts."""
    pipeline = build_default_tool_selection_pipeline()
    tools = {
        f"mcp__srv__tool_{idx}": SimpleNamespace(name=f"mcp__srv__tool_{idx}", description="desc")
        for idx in range(20)
    }
    tools["read"] = SimpleNamespace(name="read", description="Read files")
    tools["write"] = SimpleNamespace(name="write", description="Write files")

    result = pipeline.select_with_trace(
        tools,
        ToolSelectionContext(
            metadata={
                "policy_layers": {
                    "global": {"max_tools": 6},
                    "tenant": {"max_tools": 4},
                },
            }
        ),
    )

    mcp_tools = [n for n in result.tools if n.startswith("mcp__")]
    assert len(mcp_tools) == 20
    assert "read" in result.tools
    assert "write" in result.tools
    semantic = next(step for step in result.trace if step.stage == "semantic_ranker_stage")
    assert semantic.explain.get("max_tools") == 4


@pytest.mark.unit
def test_stage_budget_reverts_when_stage_exceeds_latency_budget() -> None:
    """Pipeline should revert stage output when stage latency budget is exceeded."""

    def slow_remove_stage(
        tools: dict[str, object],
        _context: ToolSelectionContext,
    ) -> dict[str, object]:
        time.sleep(0.01)
        return {}

    pipeline = ToolSelectionPipeline(stages=[slow_remove_stage])
    tools = {
        "read": SimpleNamespace(name="read", description="Read files"),
        "write": SimpleNamespace(name="write", description="Write files"),
    }

    result = pipeline.select_with_trace(
        tools,
        ToolSelectionContext(
            metadata={
                "max_stage_latency_ms": 1,
                "stage_budget_fallback": "revert",
            }
        ),
    )

    assert set(result.tools.keys()) == {"read", "write"}
    trace = result.trace[0]
    assert trace.explain.get("budget_exceeded") is True
    assert trace.explain.get("budget_fallback") == "revert"


@pytest.mark.unit
def test_semantic_stage_supports_custom_ranker_backend() -> None:
    """Semantic stage should honor injected custom semantic ranker callable."""
    pipeline = build_default_tool_selection_pipeline()
    tools = {
        "read": SimpleNamespace(name="read", description="Read files"),
        "mcp__srv__alpha": SimpleNamespace(name="mcp__srv__alpha", description="alpha tool"),
        "mcp__srv__beta": SimpleNamespace(name="mcp__srv__beta", description="beta tool"),
        "mcp__srv__gamma": SimpleNamespace(name="mcp__srv__gamma", description="gamma tool"),
        "mcp__srv__delta": SimpleNamespace(name="mcp__srv__delta", description="delta tool"),
    }

    class CustomAgentRanker:
        name = "custom-agent-ranker"
        decision_mode = "structured_tool_call"
        audit_enabled = True

        def rank_tools(self, tool_map, _context):
            ordered = (
                "mcp__srv__gamma",
                "mcp__srv__beta",
                "mcp__srv__alpha",
                "mcp__srv__delta",
            )
            return ToolRankingDecisionV2(
                ordered_tool_names=ordered,
                audit=ToolRankingAuditV2(
                    agent_id="judge:model-a",
                    tool_name="rank_agent_tools_v2",
                    input_json={"candidate_tool_names": list(tool_map)},
                    output_json={"ordered_tool_names": list(ordered)},
                    rationale="Structured Agent ranking for the supplied MCP candidates.",
                    latency_ms=3,
                ),
            )

    result = pipeline.select_with_trace(
        tools,
        ToolSelectionContext(
            metadata={
                "max_tools": 3,
                "semantic_backend": "agent_decision",
                "semantic_ranker": CustomAgentRanker(),
            }
        ),
    )

    # read is built-in (always included), budget=3, 1 built-in, so 2 mcp slots
    assert "read" in result.tools
    assert "mcp__srv__gamma" in result.tools
    semantic = next(step for step in result.trace if step.stage == "semantic_ranker_stage")
    assert semantic.explain.get("semantic_backend") == "agent_decision"
    assert semantic.explain.get("semantic_backend_effective") == "agent_decision"


@pytest.mark.unit
def test_policy_stage_normalizes_extended_layer_order() -> None:
    """Policy explain should include normalized layer order with provider/sandbox/subagent."""
    pipeline = build_default_tool_selection_pipeline()
    tools = {
        "read": SimpleNamespace(name="read", description="Read files"),
        "web_search": SimpleNamespace(name="web_search", description="Search web"),
    }

    result = pipeline.select_with_trace(
        tools,
        ToolSelectionContext(
            metadata={
                "policy_layers": {
                    "provider": {"allow_tools": ["web_search"]},
                    "subagent": {"deny_tools": ["web_search"]},
                }
            }
        ),
    )

    policy = next(step for step in result.trace if step.stage == "policy_stage")
    assert "provider" in policy.explain.get("policy_layer_order", [])
    assert "subagent" in policy.explain.get("policy_layer_order", [])


@pytest.mark.unit
def test_semantic_stage_embedding_backend_cannot_issue_subjective_verdict() -> None:
    """Embedding similarity alone cannot prune model-visible tools."""
    pipeline = build_default_tool_selection_pipeline()
    tools = {
        "read": SimpleNamespace(name="read", description="Read files"),
        "mcp__srv__alpha": SimpleNamespace(name="mcp__srv__alpha", description="alpha"),
        "mcp__srv__beta": SimpleNamespace(name="mcp__srv__beta", description="beta"),
        "mcp__srv__gamma": SimpleNamespace(name="mcp__srv__gamma", description="gamma"),
    }

    def _embedding_ranker(tool_map, _context):
        return ["mcp__srv__beta", "mcp__srv__gamma", "mcp__srv__alpha", "read"]

    result = pipeline.select_with_trace(
        tools,
        ToolSelectionContext(
            metadata={
                "max_tools": 2,
                "semantic_backend": "embedding_vector",
                "embedding_ranker": _embedding_ranker,
            }
        ),
    )

    assert set(result.tools) == set(tools)
    semantic = next(step for step in result.trace if step.stage == "semantic_ranker_stage")
    assert semantic.explain.get("semantic_backend") == "embedding_vector"
    assert semantic.explain.get("semantic_backend_effective") == "unfiltered"


@pytest.mark.unit
def test_semantic_stage_quality_scores_cannot_issue_subjective_verdict() -> None:
    """Arithmetic quality metrics cannot decide which tools are relevant."""
    pipeline = build_default_tool_selection_pipeline()
    tools = {
        "read": SimpleNamespace(name="read", description="Read files"),
        "mcp__srv__tool_a": SimpleNamespace(name="mcp__srv__tool_a", description="general helper"),
        "mcp__srv__tool_b": SimpleNamespace(name="mcp__srv__tool_b", description="general helper"),
        "mcp__srv__tool_c": SimpleNamespace(name="mcp__srv__tool_c", description="general helper"),
    }

    result = pipeline.select_with_trace(
        tools,
        ToolSelectionContext(
            metadata={
                "max_tools": 2,
                "semantic_backend": "token_vector",
                "tool_quality_scores": {
                    "mcp__srv__tool_a": 0.1,
                    "mcp__srv__tool_b": 0.95,
                    "mcp__srv__tool_c": 0.2,
                },
            }
        ),
    )

    assert set(result.tools) == set(tools)
