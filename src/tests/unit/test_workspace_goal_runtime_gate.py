"""Unit tests for the relaxed ``should_activate_workspace_authority`` gate (P0)."""

import pytest

from src.infrastructure.agent.workspace.workspace_goal_runtime import (
    should_activate_workspace_authority,
)


@pytest.mark.unit
class TestShouldActivateWorkspaceAuthority:
    def test_english_regex_match_still_activates(self) -> None:
        assert should_activate_workspace_authority(
            "please execute the workspace goal",
        )

    def test_chinese_query_without_flags_does_not_activate(self) -> None:
        # No english keywords, no binding, no open root → stays off (fallback behavior)
        assert not should_activate_workspace_authority("帮我完成这个目标")

    def test_chinese_query_with_binding_activates(self) -> None:
        assert should_activate_workspace_authority(
            "帮我完成这个目标",
            has_workspace_binding=True,
        )

    def test_empty_query_with_open_root_activates(self) -> None:
        assert should_activate_workspace_authority("", has_open_root=True)

    def test_binding_short_circuits_regardless_of_query(self) -> None:
        assert should_activate_workspace_authority(
            "random chatter",
            has_workspace_binding=True,
        )

    def test_no_signals_returns_false(self) -> None:
        assert not should_activate_workspace_authority("just saying hi")
