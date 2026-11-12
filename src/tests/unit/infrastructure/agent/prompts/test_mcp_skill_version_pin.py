"""MCP skill docs must match the repository pin, not an unverified 2.3.0 claim."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REQUIREMENTS = (
    Path(__file__).resolve().parents[6]
    / ".memstack"
    / "skills"
    / "mcp-builder"
    / "scripts"
    / "requirements.txt"
)


def test_mcp_builder_requires_the_1_x_sdk_line() -> None:
    text = _REQUIREMENTS.read_text(encoding="utf-8")
    assert "mcp>=1.1.0" in text
    assert "mcp==2.3.0" not in text
