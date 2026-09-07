"""Zero-reference gates for retired top-level agent repository facades."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.containers.agent_container import AgentContainer
from src.configuration.di_container import DIContainer

pytestmark = pytest.mark.unit


def test_unused_agent_repository_facades_are_retired_from_top_level_di() -> None:
    retired_facades = {
        "conversation_repository",
        "agent_execution_event_repository",
        "agent_service",
        "agent_execution_repository",
        "execution_checkpoint_repository",
        "skill_version_repository",
        "subagent_run_registry",
        "tool_composition_repository",
        "tool_environment_variable_repository",
        "workflow_pattern_repository",
    }

    assert retired_facades.isdisjoint(vars(DIContainer))


def test_application_shell_does_not_construct_an_agent_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_agent_container(*args: object, **kwargs: object) -> None:
        raise AssertionError("Application shell must not assemble Agent business services")

    monkeypatch.setattr(AgentContainer, "__init__", reject_agent_container)
    container = DIContainer()
    scoped = container.with_db(AsyncSession())

    assert scoped._infra is container._infra
    assert not hasattr(container, "_agent")
    assert not hasattr(scoped, "_agent")


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


def test_unused_internal_builder_facades_are_retired_from_top_level_di() -> None:
    retired_facades = {
        "api_key_repository",
        "chat_use_case",
        "execute_step_use_case",
        "llm_invoker",
        "react_loop",
        "sequence_service",
        "skill_service",
        "spawn_manager",
        "synthesize_results_use_case",
        "tool_executor",
        "workflow_learner",
        "workspace_manager",
        "workspace_task_session_attempt_service",
    }

    assert retired_facades.isdisjoint(vars(DIContainer))


def test_orphaned_agent_constructors_are_retired_from_agent_container() -> None:
    retired_constructors = {
        "announce_service",
        "artifact_extractor",
        "chat_use_case",
        "compose_tools_use_case",
        "llm_invoker",
        "orphan_sweeper",
        "react_loop",
        "skill_version_repository",
        "tool_composition_repository",
        "tool_environment_variable_repository",
        "tool_executor",
        "workspace_manager",
    }

    assert retired_constructors.isdisjoint(vars(AgentContainer))


def test_unused_runtime_helper_facades_are_retired_from_top_level_di() -> None:
    retired_facades = {
        "_require_db",
        "agent_router_service",
        "attachment_injector",
        "attachment_processor",
        "context_facade",
        "default_context_engine",
        "default_message_router",
        "event_converter",
        "fork_merge_service",
        "layered_tool_policy_service",
        "message_binding_repository",
        "message_builder",
        "redis_agent_credential_scope",
        "redis_agent_namespace",
        "span_service",
        "storage_service",
        "user_repository",
        "workspace_orchestrator",
    }

    assert retired_facades.isdisjoint(vars(DIContainer))
