from unittest.mock import AsyncMock, Mock

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

    @pytest.mark.asyncio
    async def test_extract_memories_log_omits_exception_content(self, caplog) -> None:
        exception_detail = "llm extraction leaked user secret alpha-2468"
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(side_effect=RuntimeError(exception_detail))
        service = MemoryCapturePostprocessor(llm_client=llm_client)

        with caplog.at_level("WARNING", logger="src.infrastructure.agent.memory.capture"):
            items = await service._extract_memories(
                user_message="remember private token alpha-2468",
                assistant_response="noted",
            )

        assert items == []
        assert exception_detail not in caplog.text
        assert "alpha-2468" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_store_chunk_log_omits_exception_content(self, caplog) -> None:
        exception_detail = "chunk save leaked memory content beta-3579"
        chunk_repo = Mock()
        chunk_repo.save = AsyncMock(side_effect=RuntimeError(exception_detail))
        service = MemoryCapturePostprocessor(llm_client=AsyncMock())

        with caplog.at_level("WARNING", logger="src.infrastructure.agent.memory.capture"):
            stored = await service._store_chunk(
                chunk_repo=chunk_repo,
                content="memory content beta-3579",
                category="fact",
                embedding=None,
                project_id="project-secret",
                conversation_id="conversation-secret",
            )

        assert stored is False
        assert exception_detail not in caplog.text
        assert "beta-3579" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_process_and_store_items_log_omits_exception_content(self, caplog) -> None:
        exception_detail = "storage pipeline leaked memory content gamma-4680"
        service = MemoryCapturePostprocessor(llm_client=AsyncMock())
        service._process_capture_item = AsyncMock(side_effect=RuntimeError(exception_detail))  # type: ignore[method-assign]

        with caplog.at_level("WARNING", logger="src.infrastructure.agent.memory.capture"):
            captured, categories = await service._process_and_store_items(
                items=[{"content": "memory content gamma-4680", "category": "fact"}],
                chunk_repo=object(),
                project_id="project-secret",
                conversation_id="conversation-secret",
            )

        assert captured == 0
        assert categories == []
        assert exception_detail not in caplog.text
        assert "gamma-4680" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
