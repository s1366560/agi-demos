"""Tests for the V2 legacy bridge — see ``goal_runtime/v2_bridge.py``."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.infrastructure.agent.workspace.goal_runtime import v2_bridge
from src.infrastructure.agent.workspace.goal_runtime.v2_bridge import (
    kickoff_v2_plan_if_enabled,
    reset_orchestrator_singleton_for_testing,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_orchestrator_singleton_for_testing()
    yield
    reset_orchestrator_singleton_for_testing()


class _FakeSettings:
    def __init__(self, enabled: bool) -> None:
        self.workspace_v2_enabled = enabled


def _patch_settings(enabled: bool):
    return patch("src.configuration.config.get_settings", return_value=_FakeSettings(enabled))


async def test_kickoff_noop_when_flag_disabled() -> None:
    with _patch_settings(False), patch.object(v2_bridge, "_get_orchestrator") as fake_get:
        await kickoff_v2_plan_if_enabled(
            workspace_id="ws-1", title="Goal", description="desc", created_by="user-1"
        )
        fake_get.assert_not_called()


async def test_kickoff_creates_plan_when_flag_enabled() -> None:
    from src.infrastructure.agent.workspace_plan import build_default_orchestrator

    orchestrator = build_default_orchestrator()

    with (
        _patch_settings(True),
        patch.object(v2_bridge, "_get_orchestrator", return_value=orchestrator),
    ):
        await kickoff_v2_plan_if_enabled(
            workspace_id="ws-abc",
            title="Build a CRUD blog",
            description="Ship the first vertical slice",
            created_by="user-42",
        )

    plan = await orchestrator._repo.get_by_workspace("ws-abc")
    assert plan is not None
    goal_node = plan.nodes[plan.goal_id]
    assert goal_node.title == "Build a CRUD blog"


async def test_kickoff_swallows_orchestrator_failures() -> None:
    class _ExplodingOrchestrator:
        enabled = True

        async def start_goal(self, **_: object) -> None:
            raise RuntimeError("boom")

    with (
        _patch_settings(True),
        patch.object(v2_bridge, "_get_orchestrator", return_value=_ExplodingOrchestrator()),
    ):
        # Must not raise — legacy path must remain unaffected.
        await kickoff_v2_plan_if_enabled(
            workspace_id="ws-x", title="T", description="", created_by=""
        )


async def test_kickoff_noop_when_orchestrator_disabled() -> None:
    class _DisabledOrchestrator:
        enabled = False

        async def start_goal(self, **_: object) -> None:  # pragma: no cover
            raise AssertionError("start_goal must not be called when disabled")

    with (
        _patch_settings(True),
        patch.object(v2_bridge, "_get_orchestrator", return_value=_DisabledOrchestrator()),
    ):
        await kickoff_v2_plan_if_enabled(
            workspace_id="ws-y", title="T", description="", created_by=""
        )
