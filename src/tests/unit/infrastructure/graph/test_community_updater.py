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
    """LLM client exposing the public generate_response() surface."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate_response(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"content": '{"name": "Memory Graph", "summary": "Graph operations."}'}


class InvalidJsonGenerateLLMClient:
    """LLM client returning malformed JSON with sensitive response content."""

    async def generate(self, **_kwargs: Any) -> dict[str, Any]:
        return {"content": "not-json community-summary-secret-97531"}


class FailingGenerateLLMClient:
    """LLM client raising a provider-style error during summary generation."""

    async def generate(self, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("provider echoed community-generate-secret-8642")


class FailingStructuredLLM:
    """Structured-output adapter that raises a provider-style error."""

    async def ainvoke(self, _messages: list[Any]) -> object:
        raise RuntimeError("structured provider echoed community-structured-secret-2468")


class StructuredFallbackGenerateLLMClient(GenerateOnlyLLMClient):
    """LLM client whose structured path fails before generate() fallback succeeds."""

    def with_structured_output(self, _schema: type[object]) -> FailingStructuredLLM:
        return FailingStructuredLLM()


class CommunityQueryNeo4jClient:
    """Neo4j client returning a single community record."""

    async def execute_query(self, *_args: Any, **_kwargs: Any) -> object:
        class Result:
            def __init__(self) -> None:
                self.records = [
                    {
                        "c": {
                            "name": "Existing Community",
                            "project_id": "project-1",
                            "tenant_id": "tenant-1",
                        }
                    }
                ]

        return Result()


class CommunityMemberDetector:
    """Louvain detector returning one community member."""

    async def get_community_members(self, _community_uuid: str) -> list[dict[str, Any]]:
        return [{"name": "Ada", "summary": "Research lead"}]


class PrivateGenerateResponseOnlyLLMClient:
    """LLM client exposing the Graphiti-compatible private response surface."""

    async def _generate_response(self, **_kwargs: Any) -> dict[str, Any]:
        return {"content": '{"name": "Legacy Graph", "summary": "Legacy graph operations."}'}


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
        llm_client = GenerateResponseOnlyLLMClient()
        updater = build_updater(llm_client)

        result = await updater._call_llm_with_json_extraction(
            [Message.system("Summarize"), Message.user("Members")]
        )

        assert result.name == "Memory Graph"
        assert result.summary == "Graph operations."
        assert llm_client.calls[0]["response_model"] is None

    async def test_call_llm_with_json_extraction_redacts_invalid_response(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        updater = build_updater(InvalidJsonGenerateLLMClient())

        with (
            caplog.at_level(
                "DEBUG",
                logger="src.infrastructure.graph.community.community_updater",
            ),
            pytest.raises(ValueError),
        ):
            await updater._call_llm_with_json_extraction(
                [Message.system("Summarize"), Message.user("Members")]
            )

        assert "community-summary-secret-97531" not in caplog.text
        assert "error_type=JSONDecodeError" in caplog.text
        assert "response_length=" in caplog.text

    async def test_call_llm_structured_redacts_structured_output_error(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        llm_client = StructuredFallbackGenerateLLMClient()
        updater = build_updater(llm_client)

        with caplog.at_level(
            "DEBUG",
            logger="src.infrastructure.graph.community.community_updater",
        ):
            result = await updater._call_llm_structured("Summarize", "Members")

        assert result.name == "Core Platform"
        assert result.summary == "Platform services."
        assert llm_client.calls[0]["response_format"] == "json"
        assert "community-structured-secret-2468" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    async def test_generate_community_summary_redacts_fallback_error(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        updater = build_updater(FailingGenerateLLMClient())

        with caplog.at_level(
            "WARNING",
            logger="src.infrastructure.graph.community.community_updater",
        ):
            result = await updater._generate_community_summary(
                [{"name": "Ada", "summary": "Research lead"}]
            )

        assert result == {"name": "Unnamed Community", "summary": ""}
        assert "community-generate-secret-8642" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    async def test_update_single_community_redacts_summary_error(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        updater = CommunityUpdater(
            neo4j_client=CommunityQueryNeo4jClient(),  # type: ignore[arg-type]
            llm_client=GenerateOnlyLLMClient(),  # type: ignore[arg-type]
            louvain_detector=CommunityMemberDetector(),  # type: ignore[arg-type]
        )

        async def fail_summary(_member_entities: list[dict[str, Any]]) -> dict[str, str]:
            raise RuntimeError("provider echoed community-update-secret-1357")

        monkeypatch.setattr(updater, "_generate_community_summary", fail_summary)

        with caplog.at_level(
            "ERROR",
            logger="src.infrastructure.graph.community.community_updater",
        ):
            result = await updater.update_single_community("community-1")

        assert result is None
        assert "community-update-secret-1357" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    async def test_call_llm_with_json_extraction_supports_private_generate_response_client(
        self,
    ) -> None:
        updater = build_updater(PrivateGenerateResponseOnlyLLMClient())

        result = await updater._call_llm_with_json_extraction(
            [Message.system("Summarize"), Message.user("Members")]
        )

        assert result.name == "Legacy Graph"
        assert result.summary == "Legacy graph operations."
