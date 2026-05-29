from types import SimpleNamespace

import pytest

from src.infrastructure.agent.sisyphus.prompt_builder import (
    SisyphusPromptBuilder,
    SisyphusPromptContext,
)


@pytest.mark.unit
def test_prompt_builder_renders_subagent_tool_boundaries() -> None:
    builder = SisyphusPromptBuilder()
    prompt = builder.build(
        SisyphusPromptContext(
            model_name="gpt-5.5",
            max_steps=20,
            tools=[],
            skills=[],
            subagents=[
                SimpleNamespace(
                    name="e2e-worker",
                    trigger_description="End-to-end autonomy test worker",
                    system_prompt="Do not use sandbox, filesystem, browser, or network tools.",
                    allowed_tools=[
                        "workspace_report_complete",
                        "workspace_report_progress",
                        "todoread",
                    ],
                )
            ],
        )
    )

    assert "match the subagent's responsibility and allowed tools" in prompt
    assert "`e2e-worker`" in prompt
    assert "End-to-end autonomy test worker" in prompt
    assert "allowed tools: workspace_report_complete, workspace_report_progress, todoread" in prompt
