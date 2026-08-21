"""Structural gates for retired construction-time V1 Agent bridges."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from src.infrastructure.agent.core.subagent_runner import SubAgentRunnerDeps
from src.infrastructure.agent.processor.factory import ProcessorFactory

_ROOT = Path(__file__).resolve().parents[6]
_REACT_AGENT_SOURCE = _ROOT / "src/infrastructure/agent/core/react_agent.py"
_SUBAGENT_RUNNER_SOURCE = _ROOT / "src/infrastructure/agent/core/subagent_runner.py"


@pytest.mark.unit
def test_processor_factory_has_no_dormant_v1_plugin_dependencies() -> None:
    field_names = {field.name for field in fields(ProcessorFactory)}

    assert "plugin_registry" not in field_names
    assert "plugin_event_dispatcher" not in field_names


@pytest.mark.unit
def test_subagent_runner_has_no_v1_plugin_registry_bridge() -> None:
    field_names = {field.name for field in fields(SubAgentRunnerDeps)}
    source = _SUBAGENT_RUNNER_SOURCE.read_text(encoding="utf-8")

    assert "plugin_registry" not in field_names
    assert "registry.notify_hook" not in source


@pytest.mark.unit
def test_react_agent_constructor_does_not_resolve_v1_plugin_globals() -> None:
    source = _REACT_AGENT_SOURCE.read_text(encoding="utf-8")

    assert "create_agent_plugin_event_dispatcher" not in source
    assert "get_plugin_registry" not in source
