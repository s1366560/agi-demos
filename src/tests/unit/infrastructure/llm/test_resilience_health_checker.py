"""Unit tests for resilience health checker endpoint resolution."""

from types import SimpleNamespace

import pytest

from src.domain.llm_providers.models import ProviderType
from src.infrastructure.llm.resilience.health_checker import _resolve_endpoint_factory

pytestmark = pytest.mark.unit


def test_resolve_endpoint_factory_supports_volcengine_base_provider() -> None:
    """Volcengine base provider should resolve to Ark models endpoint."""
    endpoint_factory = _resolve_endpoint_factory(ProviderType.VOLCENGINE)

    assert endpoint_factory is not None
    endpoint = endpoint_factory(SimpleNamespace(base_url=None, llm_model="doubao"), "ark-key")
    assert endpoint.url == "https://ark.cn-beijing.volces.com/api/v3/models"
    assert endpoint.headers == {"Authorization": "Bearer ark-key"}


def test_resolve_endpoint_factory_supports_volcengine_variants() -> None:
    """Volcengine specialized variants should reuse the base provider endpoint."""
    endpoint_factory = _resolve_endpoint_factory(ProviderType.VOLCENGINE_CODING)

    assert endpoint_factory is not None
    endpoint = endpoint_factory(
        SimpleNamespace(base_url="https://custom.volcengine.example/api/v3", llm_model="doubao"),
        "ark-key",
    )
    assert endpoint.url == "https://custom.volcengine.example/api/v3/models"


def test_resolve_endpoint_factory_normalizes_other_variants() -> None:
    """Other *_coding variants should map to their base provider endpoints."""
    endpoint_factory = _resolve_endpoint_factory(ProviderType.MINIMAX_CODING)

    assert endpoint_factory is not None
    endpoint = endpoint_factory(SimpleNamespace(base_url=None, llm_model="abab"), "mm-key")
    assert endpoint.url == "https://api.minimax.io/v1/models"


class TestOpenaiEndpointCustomBaseUrl:
    """Tests for OpenAI endpoint with custom base_url support."""

    def test_openai_default_url_when_base_url_is_none(self) -> None:
        """OpenAI should use default URL when base_url is None."""
        endpoint_factory = _resolve_endpoint_factory(ProviderType.OPENAI)
        assert endpoint_factory is not None
        endpoint = endpoint_factory(
            SimpleNamespace(base_url=None, llm_model="gpt-4"),
            "sk-key",
        )
        assert endpoint.url == "https://api.openai.com/v1/models"

    def test_openai_custom_url_when_base_url_is_set(self) -> None:
        """OpenAI should use custom base_url when provided."""
        endpoint_factory = _resolve_endpoint_factory(ProviderType.OPENAI)
        assert endpoint_factory is not None
        endpoint = endpoint_factory(
            SimpleNamespace(
                base_url="https://my-proxy.example.com/v1",
                llm_model="gpt-4",
            ),
            "sk-key",
        )
        assert endpoint.url == "https://my-proxy.example.com/v1/models"


class TestGeminiEndpointCustomBaseUrl:
    """Tests for Gemini endpoint with custom base_url support."""

    def test_gemini_default_url_when_base_url_is_none(self) -> None:
        """Gemini should use default URL when base_url is None."""
        endpoint_factory = _resolve_endpoint_factory(ProviderType.GEMINI)
        assert endpoint_factory is not None
        endpoint = endpoint_factory(
            SimpleNamespace(base_url=None, llm_model="gemini-pro"),
            "goog-key",
        )
        assert endpoint.url == (
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro"
        )

    def test_gemini_custom_url_when_base_url_is_set(self) -> None:
        """Gemini should use custom base_url when provided."""
        endpoint_factory = _resolve_endpoint_factory(ProviderType.GEMINI)
        assert endpoint_factory is not None
        endpoint = endpoint_factory(
            SimpleNamespace(
                base_url="https://gemini-proxy.example.com/v1beta",
                llm_model="gemini-2.0-flash",
            ),
            "goog-key",
        )
        assert endpoint.url == ("https://gemini-proxy.example.com/v1beta/models/gemini-2.0-flash")


class TestAnthropicEndpointCustomBaseUrl:
    """Tests for Anthropic endpoint with custom base_url support."""

    def test_anthropic_default_url_when_base_url_is_none(self) -> None:
        """Anthropic should use default URL when base_url is None."""
        endpoint_factory = _resolve_endpoint_factory(ProviderType.ANTHROPIC)
        assert endpoint_factory is not None
        endpoint = endpoint_factory(
            SimpleNamespace(base_url=None, llm_model="claude-3"),
            "ant-key",
        )
        assert endpoint.url == "https://api.anthropic.com/v1/models"

    def test_anthropic_custom_url_when_base_url_is_set(self) -> None:
        """Anthropic should use custom base_url when provided."""
        endpoint_factory = _resolve_endpoint_factory(ProviderType.ANTHROPIC)
        assert endpoint_factory is not None
        endpoint = endpoint_factory(
            SimpleNamespace(
                base_url="https://anthropic-proxy.example.com/v1",
                llm_model="claude-3",
            ),
            "ant-key",
        )
        assert endpoint.url == "https://anthropic-proxy.example.com/v1/models"
