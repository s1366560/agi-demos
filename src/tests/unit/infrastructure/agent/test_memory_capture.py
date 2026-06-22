from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.memory.builtin_skill_prompts import (
    MEMORY_CAPTURE_SKILL_NAME,
    load_builtin_skill_prompt,
)
from src.infrastructure.agent.memory.capture import MemoryCapturePostprocessor


@pytest.mark.unit
class TestMemoryCapturePostprocessor:
    @pytest.mark.asyncio
    async def test_extract_memories_uses_builtin_skill_prompt(self) -> None:
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(return_value={"content": "[]"})
        service = MemoryCapturePostprocessor(llm_client=llm_client)

        items = await service._extract_memories(
            user_message="Remember that I prefer dark mode.",
            assistant_response="I'll keep that in mind.",
        )

        assert items == []
        messages = llm_client.generate.await_args.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == load_builtin_skill_prompt(MEMORY_CAPTURE_SKILL_NAME)
        assert "<conversation_turn>" in messages[1]["content"]
        assert "<user_message>" in messages[1]["content"]
        assert "Remember that I prefer dark mode." in messages[1]["content"]
        assert "<assistant_response>" in messages[1]["content"]
        assert "I'll keep that in mind." in messages[1]["content"]
