"""Zero-reference gates for retired top-level agent repository facades."""

from __future__ import annotations

import pytest

from src.configuration.di_container import DIContainer

pytestmark = pytest.mark.unit


def test_unused_agent_repository_facades_are_retired_from_top_level_di() -> None:
    retired_facades = {
        "agent_execution_repository",
        "execution_checkpoint_repository",
        "skill_version_repository",
        "tool_composition_repository",
        "tool_environment_variable_repository",
    }

    assert retired_facades.isdisjoint(vars(DIContainer))
