"""Unit tests for tool selection/policy pipeline."""

from types import SimpleNamespace

import pytest

from src.infrastructure.agent.plugins.selection_pipeline import (
    ToolSelectionContext,
    build_default_tool_selection_pipeline,
)


@pytest.mark.unit
def test_default_pipeline_limits_tools_and_emits_trace() -> None:
    """Semantic stage should cap tools and emit stage traces."""
    pipeline = build_default_tool_selection_pipeline()
    tools = {f"tool_{idx}": SimpleNamespace(name=f"tool_{idx}", description="desc") for idx in range(30)}
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

    assert len(result.tools) <= 5
    assert any(step.stage == "semantic_ranker_stage" for step in result.trace)


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
