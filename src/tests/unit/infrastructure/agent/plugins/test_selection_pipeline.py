"""Unit tests for tool selection/policy pipeline."""

import time
from types import SimpleNamespace

import pytest

from src.infrastructure.agent.plugins.selection_pipeline import (
    ToolSelectionContext,
    ToolSelectionPipeline,
    build_default_tool_selection_pipeline,
)


@pytest.mark.unit
def test_default_pipeline_limits_tools_and_emits_trace() -> None:
    """Semantic stage should cap user MCP tools and emit stage traces.

    System built-in tools (non mcp__* prefix) are always included.
    Only user MCP tools (mcp__* prefix) are subject to budget pruning.
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

    # Budget is 5 total, 2 built-in (read, write) always included,
    # so at most 3 user MCP tools should survive
    mcp_tools = [n for n in result.tools if n.startswith("mcp__")]
    assert len(mcp_tools) <= 3
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
def test_semantic_stage_uses_layered_max_tools_budget() -> None:
    """Layered max_tools budget should cap user MCP tool selection."""
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

    # Budget is 4, 2 built-in always included, so at most 2 user MCP tools
    mcp_tools = [n for n in result.tools if n.startswith("mcp__")]
    assert len(mcp_tools) <= 2
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

    def _custom_ranker(tool_map, _context):
        return [
            "mcp__srv__gamma",
            "mcp__srv__beta",
            "mcp__srv__alpha",
            "mcp__srv__delta",
            "read",
        ]

    result = pipeline.select_with_trace(
        tools,
        ToolSelectionContext(
            metadata={
                "max_tools": 3,
                "semantic_ranker": _custom_ranker,
            }
        ),
    )

    # read is built-in (always included), budget=3, 1 built-in, so 2 mcp slots
    assert "read" in result.tools
    assert "mcp__srv__gamma" in result.tools
    semantic = next(step for step in result.trace if step.stage == "semantic_ranker_stage")
    assert semantic.explain.get("semantic_backend") == "embedding_vector"
    assert semantic.explain.get("semantic_backend_effective") == "token_vector"


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
def test_semantic_stage_uses_embedding_ranker_when_configured() -> None:
    """Embedding backend should honor embedding_ranker callable when provided."""
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

    # read is built-in (always included), budget=2, 1 built-in, 1 mcp slot
    assert "read" in result.tools
    assert "mcp__srv__beta" in result.tools
    semantic = next(step for step in result.trace if step.stage == "semantic_ranker_stage")
    assert semantic.explain.get("semantic_backend") == "embedding_vector"
    assert semantic.explain.get("semantic_backend_effective") == "embedding_vector"


@pytest.mark.unit
def test_semantic_stage_applies_tool_quality_scores() -> None:
    """Quality scores should bias semantic selection when tools are otherwise similar."""
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

    assert "read" in result.tools
    assert "mcp__srv__tool_b" in result.tools
