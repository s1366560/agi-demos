"""Tests for tool provider helpers."""

import pytest

from src.infrastructure.agent.tools.tool_provider import create_pipeline_tool_provider


@pytest.mark.unit
def test_create_pipeline_tool_provider_applies_pipeline() -> None:
    """Pipeline wrapper should return pipeline-filtered tools."""
    base_provider = lambda: {"tool_a": object(), "tool_b": object()}

    def _pipeline(tools, _context):
        return {"tool_a": tools["tool_a"]}

    provider = create_pipeline_tool_provider(base_provider, _pipeline)
    tools = provider()

    assert set(tools.keys()) == {"tool_a"}


@pytest.mark.unit
def test_create_pipeline_tool_provider_raises_on_error() -> None:
    """Pipeline wrapper should surface selection pipeline failures."""
    base_provider = lambda: {"tool_a": object()}

    def _pipeline(_tools, _context):
        raise RuntimeError("boom")

    provider = create_pipeline_tool_provider(base_provider, _pipeline)

    with pytest.raises(RuntimeError, match="boom"):
        provider()
