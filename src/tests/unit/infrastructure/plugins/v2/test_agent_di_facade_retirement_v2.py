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


def test_unused_cross_domain_facades_are_retired_from_top_level_di() -> None:
    retired_facades = {
        "agent_message_bus",
        "agent_session_registry",
        "ai_service_factory",
        "artifact_extractor",
        "compose_tools_use_case",
        "distributed_lock_adapter",
        "find_similar_pattern_use_case",
        "graph_run_repository",
        "hitl_message_bus",
        "learn_pattern_use_case",
    }

    assert retired_facades.isdisjoint(vars(DIContainer))
