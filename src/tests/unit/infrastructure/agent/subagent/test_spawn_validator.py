"""Tests for SpawnValidator."""

import pytest

from src.domain.model.agent.spawn_policy import (
    SpawnPolicy,
    SpawnRejectionCode,
)
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.subagent.spawn_validator import SpawnValidator


@pytest.mark.unit
class TestSpawnValidator:
    def test_validate_allows_valid_spawn(self):
        policy = SpawnPolicy(max_depth=3, max_active_runs=10, max_children_per_requester=5)
        registry = SubAgentRunRegistry()
        validator = SpawnValidator(policy=policy, run_registry=registry)

        result = validator.validate(
            subagent_name="researcher",
            current_depth=1,
            conversation_id="conv-1",
        )

        assert result.allowed is True
        assert result.rejection_code is None
        assert result.rejection_reason is None

    def test_validate_rejects_depth_exceeded(self):
        policy = SpawnPolicy(max_depth=2, max_active_runs=10, max_children_per_requester=5)
        registry = SubAgentRunRegistry()
        validator = SpawnValidator(policy=policy, run_registry=registry)

        result = validator.validate(
            subagent_name="researcher",
            current_depth=2,
            conversation_id="conv-1",
        )

        assert result.allowed is False
        assert result.rejection_code == SpawnRejectionCode.DEPTH_EXCEEDED
        assert result.context["current_depth"] == 2
        assert result.context["max_depth"] == 2

    def test_validate_rejects_not_in_allowlist(self):
        policy = SpawnPolicy(
            max_depth=3,
            max_active_runs=10,
            max_children_per_requester=5,
            allowed_subagents=frozenset({"coder", "writer"}),
        )
        registry = SubAgentRunRegistry()
        validator = SpawnValidator(policy=policy, run_registry=registry)

        result = validator.validate(
            subagent_name="researcher",
            current_depth=0,
            conversation_id="conv-1",
        )

        assert result.allowed is False
        assert result.rejection_code == SpawnRejectionCode.SUBAGENT_NOT_ALLOWED
        assert result.context["subagent_name"] == "researcher"
        assert result.context["allowed"] == ["coder", "writer"]

    def test_validate_allows_when_no_allowlist(self):
        policy = SpawnPolicy(
            max_depth=3,
            max_active_runs=10,
            max_children_per_requester=5,
            allowed_subagents=None,
        )
        registry = SubAgentRunRegistry()
        validator = SpawnValidator(policy=policy, run_registry=registry)

        result = validator.validate(
            subagent_name="any-agent",
            current_depth=0,
            conversation_id="conv-1",
        )

        assert result.allowed is True

    def test_validate_rejects_children_exceeded(self):
        policy = SpawnPolicy(max_depth=3, max_active_runs=10, max_children_per_requester=2)
        registry = SubAgentRunRegistry()
        run1 = registry.create_run("conv-1", "a", "task-a")
        registry.mark_running("conv-1", run1.run_id)
        run2 = registry.create_run("conv-1", "b", "task-b")
        registry.mark_running("conv-1", run2.run_id)

        validator = SpawnValidator(policy=policy, run_registry=registry)

        result = validator.validate(
            subagent_name="researcher",
            current_depth=0,
            conversation_id="conv-1",
        )

        assert result.allowed is False
        assert result.rejection_code == SpawnRejectionCode.CHILDREN_EXCEEDED
        assert result.context["active_children"] == 2
        assert result.context["max_children"] == 2

    def test_validate_rejects_concurrency_exceeded(self):
        policy = SpawnPolicy(max_depth=3, max_active_runs=2, max_children_per_requester=10)
        registry = SubAgentRunRegistry()
        r1 = registry.create_run("conv-1", "a", "task-a")
        registry.mark_running("conv-1", r1.run_id)
        r2 = registry.create_run("conv-2", "b", "task-b")
        registry.mark_running("conv-2", r2.run_id)

        validator = SpawnValidator(policy=policy, run_registry=registry)

        result = validator.validate(
            subagent_name="researcher",
            current_depth=0,
            conversation_id="conv-3",
        )

        assert result.allowed is False
        assert result.rejection_code == SpawnRejectionCode.CONCURRENCY_EXCEEDED
        assert result.context["total_active"] == 2
        assert result.context["max_active"] == 2

    def test_validate_short_circuits_on_depth(self):
        policy = SpawnPolicy(max_depth=1, max_active_runs=1, max_children_per_requester=1)
        registry = SubAgentRunRegistry()
        r1 = registry.create_run("conv-1", "a", "task-a")
        registry.mark_running("conv-1", r1.run_id)

        validator = SpawnValidator(policy=policy, run_registry=registry)

        result = validator.validate(
            subagent_name="researcher",
            current_depth=5,
            conversation_id="conv-1",
        )

        assert result.allowed is False
        assert result.rejection_code == SpawnRejectionCode.DEPTH_EXCEEDED

    def test_validate_pipeline_order(self):
        policy = SpawnPolicy(
            max_depth=1,
            max_active_runs=1,
            max_children_per_requester=1,
            allowed_subagents=frozenset({"coder"}),
        )
        registry = SubAgentRunRegistry()
        r1 = registry.create_run("conv-1", "a", "task-a")
        registry.mark_running("conv-1", r1.run_id)

        validator = SpawnValidator(policy=policy, run_registry=registry)

        depth_result = validator.validate(
            subagent_name="researcher",
            current_depth=5,
            conversation_id="conv-1",
        )
        assert depth_result.rejection_code == SpawnRejectionCode.DEPTH_EXCEEDED

        allowlist_result = validator.validate(
            subagent_name="researcher",
            current_depth=0,
            conversation_id="conv-1",
        )
        assert allowlist_result.rejection_code == SpawnRejectionCode.SUBAGENT_NOT_ALLOWED

        children_result = validator.validate(
            subagent_name="coder",
            current_depth=0,
            conversation_id="conv-1",
        )
        assert children_result.rejection_code == SpawnRejectionCode.CHILDREN_EXCEEDED

        concurrency_result = validator.validate(
            subagent_name="coder",
            current_depth=0,
            conversation_id="conv-other",
        )
        assert concurrency_result.rejection_code == SpawnRejectionCode.CONCURRENCY_EXCEEDED
