from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any, cast

from pydantic import BaseModel

from src.application.use_cases.agent.execute_step import ExecuteStepUseCase
from src.domain.llm_providers.llm_types import (
    LLMClient,
    LLMConfig,
    Message,
    ModelSize,
)
from src.domain.ports.agent.agent_tool_port import AgentToolBase
from src.infrastructure.adapters.secondary.persistence.json_types import PlanStep


class FakeLLM(LLMClient):
    def __init__(self, content: str = "step result") -> None:
        super().__init__(LLMConfig(model="fake"))
        self.content = content
        self.messages: list[Message] = []

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = 4096,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, Any]:
        del response_model, max_tokens, model_size
        self.messages = messages
        return {"content": self.content}

    async def generate(
        self,
        messages: list[Message] | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
        model_size: ModelSize = ModelSize.medium,
        langfuse_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del tools, temperature, langfuse_context, kwargs
        normalized = [
            message if isinstance(message, Message) else Message.user(str(message))
            for message in messages
        ]
        return await self._generate_response(
            normalized,
            max_tokens=max_tokens,
            model_size=model_size,
        )

    async def generate_stream(
        self,
        messages: list[Message],
        max_tokens: int = 4096,
        model_size: ModelSize = ModelSize.medium,
        langfuse_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        del messages, max_tokens, model_size, langfuse_context, kwargs
        if self.content == "__stream__":
            yield {"content": self.content}


class FakeTool:
    def __init__(self, result: str = "tool result") -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def safe_execute(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return self.result


async def test_execute_runs_llm_step_without_tool() -> None:
    llm = FakeLLM("summarized answer")
    step = PlanStep(index=0, description="Summarize the conversation")
    work_plan = SimpleNamespace(name="Research plan", steps=[step])
    use_case = ExecuteStepUseCase(llm=llm, tools={})

    result = await use_case.execute(
        work_plan,
        [{"role": "user", "content": "What changed?"}],
    )

    assert result["success"] is True
    assert result["result"] == "summarized answer"
    assert result["tool_results"] == []
    assert llm.messages[0].role == "system"
    assert "Summarize the conversation" in llm.messages[0].text


async def test_execute_runs_tool_step_with_tool_input() -> None:
    llm = FakeLLM()
    tool = FakeTool("found data")
    step = PlanStep(
        index=0,
        description="Search memory",
        tool_name="memory_search",
        tool_input={"query": "agent memory"},
    )
    tools = cast(dict[str, AgentToolBase], {"memory_search": tool})
    use_case = ExecuteStepUseCase(llm=llm, tools=tools)

    result = await use_case.execute({"steps": [step]}, [])

    assert result["success"] is True
    assert result["result"] == "found data"
    assert result["tool_results"] == [{"tool_name": "memory_search", "result": "found data"}]
    assert tool.calls == [{"query": "agent memory"}]


async def test_execute_returns_failure_for_missing_tool() -> None:
    use_case = ExecuteStepUseCase(llm=FakeLLM(), tools={})
    step = PlanStep(index=0, description="Search memory", tool_name="missing_tool")

    result = await use_case.execute({"steps": [step]}, [])

    assert result["success"] is False
    assert result["error"] == "Tool not available: missing_tool"
    assert result["tool_results"] == [
        {"tool_name": "missing_tool", "error": "Tool not available: missing_tool"}
    ]


async def test_execute_uses_current_step_index_when_available() -> None:
    llm = FakeLLM("second step")
    work_plan = {
        "name": "Indexed plan",
        "current_step_index": 1,
        "steps": [
            {"description": "First step", "status": "pending"},
            {"description": "Second step", "status": "pending"},
        ],
    }
    use_case = ExecuteStepUseCase(llm=llm, tools={})

    result = await use_case.execute(work_plan, [])

    assert result["success"] is True
    assert result["step"]["description"] == "Second step"
