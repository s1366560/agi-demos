"""Actual SubAgent process/factory control identity must match the registry run."""

from unittest.mock import MagicMock

from src.domain.model.agent.subagent import SubAgent
from src.infrastructure.agent.processor import factory as factory_module
from src.infrastructure.agent.processor.factory import ProcessorFactory
from src.infrastructure.agent.subagent.context_bridge import SubAgentContext
from src.infrastructure.agent.subagent.process import SubAgentProcess


def test_process_factory_preserves_child_run_id_and_control_channel(monkeypatch):
    monkeypatch.setattr(factory_module, "_default_loop_resolver", lambda: MagicMock())
    monkeypatch.setattr(factory_module, "_default_runtime_dispatcher", lambda: MagicMock())
    channel = MagicMock()
    factory = ProcessorFactory(
        base_model="gpt-4o", base_provider_id="fixture-provider", control_channel=channel
    )
    subagent = SubAgent.create(
        tenant_id="tenant",
        name="child",
        display_name="Child",
        system_prompt="test",
        trigger_description="test",
        trigger_keywords=[],
        trigger_examples=[],
    )
    process = SubAgentProcess(
        subagent=subagent,
        context=SubAgentContext(task_description="task", system_prompt="test"),
        tools=[],
        factory=factory,
        run_id="exact-child-run",
    )
    processor = process._build_processor()
    assert processor._run_id == "exact-child-run"
    assert processor._control_channel is channel
