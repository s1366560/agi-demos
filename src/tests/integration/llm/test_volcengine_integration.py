"""Integration tests for Volcengine (Doubao) LLM provider via LiteLLM adapters.

Tests cover chat completion, streaming, embedding, vision/multimodal,
tool calling, reasoning (thinking), and reranking.

Requires one of: ARK_API_KEY, VOLCENGINE_API_KEY environment variables.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.domain.llm_providers.llm_types import LLMConfig, Message
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient
from src.infrastructure.llm.litellm.litellm_embedder import (
    LiteLLMEmbedder,
    LiteLLMEmbedderConfig,
)
from src.infrastructure.llm.litellm.litellm_reranker import (
    LiteLLMReranker,
    LiteLLMRerankerConfig,
)

# ---------------------------------------------------------------------------
# Volcengine model identifiers (WITHOUT provider prefix).
# The LiteLLMClient._get_model_for_size() auto-prepends "volcengine/".
# ---------------------------------------------------------------------------
_CHAT_MODEL = "doubao-1.5-pro-32k"
_VISION_MODEL = "doubao-1.5-vision-pro-32k"
_REASONING_MODEL = "doubao-seed-2.0-lite"
_EMBEDDING_MODEL = "doubao-embedding"
_RERANKER_MODEL = "doubao-reranker-large"

_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
_API_KEY_ENVS = ("ARK_API_KEY", "VOLCENGINE_API_KEY")

EXTERNAL_ISSUE_KEYWORDS = (
    "invalid authentication",
    "authenticationerror",
    "unauthorized",
    "insufficient",
    "quota",
    "rate limit",
    "429",
    "connection error",
    "timed out",
    "invalid response object",
    "notfounderror",
    "invalidendpointormodel.notfound",
    "does not exist or you do not have access",
    "404",
)


# ---------------------------------------------------------------------------
# Helpers (adapted from test_provider_embedding_rerank_smoke.py)
# ---------------------------------------------------------------------------
def _resolve_env_value(env_names: tuple[str, ...]) -> str | None:
    for env_name in env_names:
        value = os.getenv(env_name)
        if value:
            return value
    return None


def _skip_or_raise_external_issue(error: Exception) -> None:
    message = str(error).lower()
    if any(kw in message for kw in EXTERNAL_ISSUE_KEYWORDS):
        pytest.skip(f"volcengine external issue: {error}")
    raise error


def _ensure_real_litellm_loaded() -> None:
    """Skip when unit-test litellm stub shadows real SDK."""
    import litellm

    module_path = str(getattr(litellm, "__file__", "")).replace("\\", "/")
    if "/src/tests/unit/llm/litellm/" in module_path:
        pytest.skip(
            "litellm unit-test stub loaded; run integration tests in separate pytest process"
        )


def _require_api_key() -> str:
    """Return the API key or skip the test."""
    api_key = _resolve_env_value(_API_KEY_ENVS)
    if not api_key:
        pytest.skip("volcengine api key not configured (set ARK_API_KEY or VOLCENGINE_API_KEY)")
    return api_key


def _make_provider_config(
    llm_model: str,
    provider_type: ProviderType = ProviderType.VOLCENGINE,
) -> ProviderConfig:
    """Build a minimal ProviderConfig for testing."""
    now = datetime.now(tz=UTC)
    return ProviderConfig(
        id=uuid4(),
        name="volcengine-integration-test",
        provider_type=provider_type,
        api_key_encrypted="not-used",
        llm_model=llm_model,
        base_url=_BASE_URL,
        config={},
        is_active=True,
        is_default=False,
        created_at=now,
        updated_at=now,
    )


def _make_client(
    api_key: str,
    llm_model: str,
    provider_type: ProviderType = ProviderType.VOLCENGINE,
) -> LiteLLMClient:
    """Instantiate a LiteLLMClient patching the encryption service."""
    provider_config = _make_provider_config(
        llm_model,
        provider_type=provider_type,
    )
    llm_config = LLMConfig(
        api_key=api_key,
        model=f"volcengine/{llm_model}",
        temperature=0,
    )
    with patch(
        "src.infrastructure.llm.litellm.litellm_client.get_encryption_service",
    ):
        return LiteLLMClient(
            config=llm_config,
            provider_config=provider_config,
            cache=False,
        )


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.slow
class TestVolcengineIntegration:
    """Integration tests for Volcengine (Doubao) provider."""

    async def test_chat_completion(self) -> None:
        """Basic chat completion returns non-empty content."""
        _ensure_real_litellm_loaded()
        api_key = _require_api_key()
        client = _make_client(api_key, _CHAT_MODEL)

        messages = [
            Message.system("You are a helpful assistant."),
            Message.user("Say 'hello world' in exactly two words."),
        ]

        try:
            result = await client.generate(messages=messages)
        except Exception as e:
            _skip_or_raise_external_issue(e)
            return

        assert isinstance(result, dict)
        assert "content" in result
        content: str = result["content"]
        assert len(content.strip()) > 0

    async def test_chat_completion_streaming(self) -> None:
        """Streaming chat completion yields chunks with content."""
        _ensure_real_litellm_loaded()
        api_key = _require_api_key()
        client = _make_client(api_key, _CHAT_MODEL)

        messages = [
            Message.system("You are a helpful assistant."),
            Message.user("Count from 1 to 5."),
        ]

        collected: list[str] = []
        try:
            async for chunk in client.generate_stream(
                messages=messages,
            ):
                delta = _extract_stream_delta(chunk)
                if delta:
                    collected.append(delta)
        except Exception as e:
            _skip_or_raise_external_issue(e)
            return

        full_text = "".join(collected)
        assert len(full_text.strip()) > 0

    async def test_embedding(self) -> None:
        """Embedding returns a non-empty float vector."""
        _ensure_real_litellm_loaded()
        api_key = _require_api_key()

        embedder = LiteLLMEmbedder(
            config=LiteLLMEmbedderConfig(
                provider_type=ProviderType.VOLCENGINE_EMBEDDING,
                embedding_model=f"volcengine/{_EMBEDDING_MODEL}",
                api_key=api_key,
                base_url=_BASE_URL,
            )
        )

        try:
            vector = await embedder.create("Volcengine embedding integration test")
        except Exception as e:
            _skip_or_raise_external_issue(e)
            return

        assert vector is not None
        assert len(vector) > 0

    async def test_vision_multimodal(self) -> None:
        """Vision model can describe an image from a URL."""
        _ensure_real_litellm_loaded()
        api_key = _require_api_key()
        client = _make_client(api_key, _VISION_MODEL)

        image_url = (
            "https://upload.wikimedia.org/wikipedia/commons/"
            "thumb/4/47/PNG_transparency_demonstration_1.png/"
            "280px-PNG_transparency_demonstration_1.png"
        )
        messages = [
            Message.system("You are a vision assistant."),
            Message.user_multimodal(
                [
                    {"type": "text", "text": "Describe this image briefly."},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    },
                ]
            ),
        ]

        try:
            result = await client.generate(messages=messages)
        except Exception as e:
            _skip_or_raise_external_issue(e)
            return

        assert isinstance(result, dict)
        content: str = result.get("content", "")
        assert len(content.strip()) > 0

    async def test_tool_calling(self) -> None:
        """Tool calling returns a function call in the response."""
        _ensure_real_litellm_loaded()
        api_key = _require_api_key()
        client = _make_client(api_key, _CHAT_MODEL)

        tools: list[dict[str, Any]] = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "City name",
                            },
                        },
                        "required": ["location"],
                    },
                },
            },
        ]

        messages = [
            Message.user("What is the weather like in Beijing today?"),
        ]

        try:
            result = await client.generate(
                messages=messages,
                tools=tools,
            )
        except Exception as e:
            _skip_or_raise_external_issue(e)
            return

        assert isinstance(result, dict)
        tool_calls = result.get("tool_calls", [])
        assert len(tool_calls) > 0, (
            f"Expected at least one tool call; got content={result.get('content', '')!r}"
        )

    async def test_reasoning_thinking(self) -> None:
        """Reasoning model returns content for a logic puzzle."""
        _ensure_real_litellm_loaded()
        api_key = _require_api_key()
        client = _make_client(api_key, _REASONING_MODEL)

        messages = [
            Message.user("If a train travels 60 km in 30 minutes, what is its speed in km/h?"),
        ]

        try:
            result = await client.generate(messages=messages)
        except Exception as e:
            _skip_or_raise_external_issue(e)
            return

        assert isinstance(result, dict)
        content: str = result.get("content", "")
        assert len(content.strip()) > 0
        assert "120" in content, f"Expected '120' in answer, got: {content!r}"

    async def test_reranker(self) -> None:
        """Reranker produces ordered scores for documents."""
        _ensure_real_litellm_loaded()
        api_key = _require_api_key()

        reranker = LiteLLMReranker(
            config=LiteLLMRerankerConfig(
                provider_type=ProviderType.VOLCENGINE_RERANKER,
                model=f"volcengine/{_RERANKER_MODEL}",
                api_key=api_key,
                base_url=_BASE_URL,
            )
        )

        docs = [
            "The sky is blue on a clear day.",
            "Paris is the capital of France.",
            "Machine learning uses statistical methods.",
        ]

        try:
            ranked = await reranker._llm_rerank(
                "Where is Paris?",
                docs,
                top_n=2,
            )
        except Exception as e:
            _skip_or_raise_external_issue(e)
            return

        assert len(ranked) == 2
        assert all(0.0 <= score <= 1.0 for _, score in ranked)
        # The most relevant document should mention Paris.
        assert "Paris" in ranked[0][0]


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------
def _extract_stream_delta(chunk: Any) -> str | None:
    """Pull text delta from a streaming chunk, if present."""
    try:
        choices = getattr(chunk, "choices", None)
        if choices and len(choices) > 0:
            delta = getattr(choices[0], "delta", None)
            if delta is not None:
                return getattr(delta, "content", None)
    except (AttributeError, IndexError):
        pass
    return None
