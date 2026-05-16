"""Unit tests for CommunityUpdater LLM response handling."""

from typing import Any

import pytest

from src.domain.llm_providers.llm_types import Message
from src.infrastructure.graph.community.community_updater import CommunityUpdater


class GenerateOnlyLLMClient:
    """LLM client exposing the default project generate() surface."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "content": '```json\n{"name": "Core Platform", "summary": "Platform services."}\n```'
        }


class GenerateResponseOnlyLLMClient:
    """LLM client exposing the Graphiti-compatible private response surface."""

    async def _generate_response(self, **_kwargs: Any) -> dict[str, Any]:
        return {"content": '{"name": "Memory Graph", "summary": "Graph operations."}'}


def build_updater(llm_client: Any) -> CommunityUpdater:
    return CommunityUpdater(
        neo4j_client=object(),  # type: ignore[arg-type]
        llm_client=llm_client,
        louvain_detector=object(),  # type: ignore[arg-type]
    )


@pytest.mark.unit
class TestCommunityUpdaterLLMResponseHandling:
    async def test_call_llm_with_json_extraction_supports_generate_client(self) -> None:
        llm_client = GenerateOnlyLLMClient()
        updater = build_updater(llm_client)

        result = await updater._call_llm_with_json_extraction(
            [Message.system("Summarize"), Message.user("Members")]
        )

        assert result.name == "Core Platform"
        assert result.summary == "Platform services."
        assert llm_client.calls[0]["temperature"] == 0.3
        assert llm_client.calls[0]["response_format"] == "json"

    async def test_call_llm_with_json_extraction_supports_generate_response_client(self) -> None:
        updater = build_updater(GenerateResponseOnlyLLMClient())

        result = await updater._call_llm_with_json_extraction(
            [Message.system("Summarize"), Message.user("Members")]
        )

        assert result.name == "Memory Graph"
        assert result.summary == "Graph operations."
