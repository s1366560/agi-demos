"""Regression tests for the agent package import boundary."""

import importlib


def test_session_event_log_import_does_not_enter_react_agent_cycle() -> None:
    module = importlib.import_module("src.infrastructure.plugins.v2.session_event_log")

    assert module.SessionEventLogServiceV2.__name__ == "SessionEventLogServiceV2"


def test_v2_builtin_catalog_import_does_not_enter_skill_model_cycle() -> None:
    module = importlib.import_module("src.infrastructure.plugins.v2.builtin_modules")

    assert callable(module.builtin_runtime_definitions_v2)


def test_historical_agent_package_exports_are_lazy() -> None:
    package = importlib.import_module("src.infrastructure.agent")
    core_package = importlib.import_module("src.infrastructure.agent.core")

    assert package.AgentTool.__name__ == "AgentTool"
    assert package.ReActAgent.__name__ == "ReActAgent"
    assert core_package.ProjectReActAgent.__name__ == "ProjectReActAgent"
