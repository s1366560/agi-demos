"""Tests for SpawnPolicy and SpawnValidationResult value objects."""

import dataclasses
from types import SimpleNamespace

import pytest

from src.domain.model.agent.spawn_policy import (
    SpawnPolicy,
    SpawnRejectionCode,
    SpawnValidationResult,
)


@pytest.mark.unit
class TestSpawnPolicy:
    def test_default_values(self) -> None:
        policy = SpawnPolicy()

        assert policy.max_depth == 2
        assert policy.max_active_runs == 16
        assert policy.max_children_per_requester == 8
        assert policy.allowed_subagents is None

    def test_frozen_immutability(self) -> None:
        policy = SpawnPolicy()

        with pytest.raises(dataclasses.FrozenInstanceError):
            policy.max_depth = 5  # type: ignore[misc]

    def test_from_settings_reads_attributes(self) -> None:
        settings = SimpleNamespace(
            AGENT_SUBAGENT_MAX_DELEGATION_DEPTH=4,
            AGENT_SUBAGENT_MAX_ACTIVE_RUNS=32,
            AGENT_SUBAGENT_MAX_CHILDREN_PER_REQUESTER=12,
            AGENT_SUBAGENT_ALLOWED_SUBAGENTS=["researcher", "coder"],
        )

        policy = SpawnPolicy.from_settings(settings)

        assert policy.max_depth == 4
        assert policy.max_active_runs == 32
        assert policy.max_children_per_requester == 12
        assert policy.allowed_subagents == frozenset({"researcher", "coder"})

    def test_from_settings_uses_defaults_for_missing(self) -> None:
        settings = SimpleNamespace()

        policy = SpawnPolicy.from_settings(settings)

        assert policy.max_depth == 2
        assert policy.max_active_runs == 16
        assert policy.max_children_per_requester == 8
        assert policy.allowed_subagents is None

    def test_allowed_subagents_frozenset(self) -> None:
        policy = SpawnPolicy(allowed_subagents=frozenset(["a", "b"]))

        assert isinstance(policy.allowed_subagents, frozenset)
        assert policy.allowed_subagents == frozenset({"a", "b"})

    def test_post_init_rejects_invalid_depth(self) -> None:
        with pytest.raises(ValueError, match="max_depth must be >= 0"):
            SpawnPolicy(max_depth=-1)

    def test_post_init_rejects_invalid_active_runs(self) -> None:
        with pytest.raises(ValueError, match="max_active_runs must be >= 1"):
            SpawnPolicy(max_active_runs=0)

    def test_post_init_rejects_invalid_children(self) -> None:
        with pytest.raises(ValueError, match="max_children_per_requester must be >= 1"):
            SpawnPolicy(max_children_per_requester=0)


@pytest.mark.unit
class TestSpawnValidationResult:
    def test_ok_factory(self) -> None:
        result = SpawnValidationResult.ok()

        assert result.allowed is True
        assert result.rejection_reason is None
        assert result.rejection_code is None
        assert result.context == {}

    def test_rejected_factory(self) -> None:
        result = SpawnValidationResult.rejected(
            reason="Too deep",
            code=SpawnRejectionCode.DEPTH_EXCEEDED,
        )

        assert result.allowed is False
        assert result.rejection_reason == "Too deep"
        assert result.rejection_code is SpawnRejectionCode.DEPTH_EXCEEDED
        assert result.context == {}

    def test_rejected_context_forwarded(self) -> None:
        result = SpawnValidationResult.rejected(
            reason="Limit hit",
            code=SpawnRejectionCode.CONCURRENCY_EXCEEDED,
            context={"current": 10, "limit": 16},
        )

        assert result.context == {"current": 10, "limit": 16}
