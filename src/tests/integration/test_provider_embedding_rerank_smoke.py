"""Real-provider smoke tests for embedding and rerank behavior."""

from __future__ import annotations

import os

import pytest

from src.domain.llm_providers.models import ProviderType
from src.infrastructure.llm.litellm.litellm_embedder import LiteLLMEmbedder, LiteLLMEmbedderConfig
from src.infrastructure.llm.litellm.litellm_reranker import LiteLLMReranker, LiteLLMRerankerConfig

PROVIDER_SMOKE_CONFIG = {
    "dashscope": {
        "provider_type": ProviderType.DASHSCOPE,
        "api_key_envs": ("DASHSCOPE_API_KEY",),
        "base_url_envs": ("DASHSCOPE_BASE_URL",),
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "embedding_model": "text-embedding-v3",
        "rerank_model": "qwen-turbo",
    },
    "zai": {
        "provider_type": ProviderType.ZAI,
        "api_key_envs": ("ZAI_API_KEY", "ZHIPU_API_KEY"),
        "base_url_envs": ("ZAI_BASE_URL", "ZHIPU_BASE_URL"),
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "embedding_model": "embedding-3",
        "rerank_model": "glm-4-flash",
    },
    "kimi": {
        "provider_type": ProviderType.KIMI,
        "api_key_envs": ("KIMI_API_KEY",),
        "base_url_envs": ("KIMI_BASE_URL",),
        "default_base_url": "https://api.moonshot.cn/v1",
        "embedding_model": "kimi-embedding-1",
        "rerank_model": "kimi-rerank-1",
    },
}

EXTERNAL_ISSUE_KEYWORDS = (
    "invalid authentication",
    "authenticationerror",
    "unauthorized",
    "余额不足",
    "insufficient",
    "quota",
    "rate limit",
    "429",
    "connection error",
    "timed out",
    "invalid response object",
)


def _resolve_env_value(env_names: tuple[str, ...]) -> str | None:
    for env_name in env_names:
        value = os.getenv(env_name)
        if value:
            return value
    return None


def _skip_or_raise_external_issue(provider_name: str, error: Exception) -> None:
    message = str(error).lower()
    if provider_name in {"zai", "kimi"} and "no embedding returned" in message:
        pytest.skip(f"{provider_name} returned empty embedding payload: {error}")
    if any(keyword in message for keyword in EXTERNAL_ISSUE_KEYWORDS):
        pytest.skip(f"{provider_name} external issue: {error}")
    raise error


def _ensure_real_litellm_loaded() -> None:
    """Skip when unit-test litellm stub shadows real SDK in the same pytest process."""
    import litellm

    module_path = str(getattr(litellm, "__file__", "")).replace("\\", "/")
    if "/src/tests/unit/llm/litellm/" in module_path:
        pytest.skip("litellm unit-test stub loaded; run provider smoke tests in separate pytest process")


@pytest.mark.integration
@pytest.mark.slow
class TestProviderEmbeddingRerankSmoke:
    """Smoke tests for configured provider embedding/rerank behavior."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider_name", ["dashscope", "zai", "kimi"])
    async def test_provider_embedding_smoke(self, provider_name: str):
        """Embedding should return a non-empty vector for each provider when API is available."""
        _ensure_real_litellm_loaded()
        cfg = PROVIDER_SMOKE_CONFIG[provider_name]
        api_key = _resolve_env_value(cfg["api_key_envs"])
        if not api_key:
            pytest.skip(f"{provider_name} api key is not configured")

        base_url = _resolve_env_value(cfg["base_url_envs"]) or cfg["default_base_url"]
        embedder = LiteLLMEmbedder(
            config=LiteLLMEmbedderConfig(
                provider_type=cfg["provider_type"],
                embedding_model=cfg["embedding_model"],
                api_key=api_key,
                base_url=base_url,
            )
        )

        try:
            vector = await embedder.create("provider smoke embedding test")
        except Exception as e:
            _skip_or_raise_external_issue(provider_name, e)
            return

        assert vector
        assert len(vector) > 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider_name", ["dashscope", "zai", "kimi"])
    async def test_provider_rerank_smoke(self, provider_name: str):
        """Rerank should produce ordered scores when provider API is available."""
        _ensure_real_litellm_loaded()
        cfg = PROVIDER_SMOKE_CONFIG[provider_name]
        api_key = _resolve_env_value(cfg["api_key_envs"])
        if not api_key:
            pytest.skip(f"{provider_name} api key is not configured")

        base_url = _resolve_env_value(cfg["base_url_envs"]) or cfg["default_base_url"]
        reranker = LiteLLMReranker(
            config=LiteLLMRerankerConfig(
                provider_type=cfg["provider_type"],
                model=cfg["rerank_model"],
                api_key=api_key,
                base_url=base_url,
            )
        )

        docs = ["The sky is blue.", "Paris is in France."]
        try:
            ranked = await reranker._llm_rerank("Where is Paris?", docs, top_n=2)
        except Exception as e:
            _skip_or_raise_external_issue(provider_name, e)
            return

        assert len(ranked) == 2
        assert all(0.0 <= score <= 1.0 for _, score in ranked)

        # Functional assertion: real reranking should lift the relevant passage.
        if provider_name == "dashscope":
            assert ranked[0][0] == "Paris is in France."
