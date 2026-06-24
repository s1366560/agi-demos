"""Tests for result synthesis use case."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.use_cases.agent.synthesize_results import SynthesizeResultsUseCase


@pytest.mark.unit
async def test_execute_llm_failure_log_omits_exception_content(caplog) -> None:
    exception_detail = "synthesis provider leaked result synthesis-secret-1357"
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(side_effect=RuntimeError(exception_detail))
    use_case = SynthesizeResultsUseCase(llm=llm)
    work_plan = SimpleNamespace(
        id="plan-1",
        steps=[SimpleNamespace(description="Collect evidence")],
    )

    with caplog.at_level("ERROR", logger="src.application.use_cases.agent.synthesize_results"):
        result = await use_case.execute(
            work_plan=work_plan,
            original_query="Summarize synthesis-secret-1357",
            step_results=[{"success": True, "tool_results": [{"result": "public evidence"}]}],
            conversation_context=[],
        )

    assert "Based on the analysis completed:" in result
    assert "Collect evidence" in result
    assert exception_detail not in caplog.text
    assert "synthesis-secret-1357" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
