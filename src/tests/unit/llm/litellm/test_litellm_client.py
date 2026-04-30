"""
Unit tests for LiteLLM Client adapter.

Tests the LiteLLMClient implementation of the LLMClient interface.
"""

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel

from src.domain.llm_providers.llm_types import LLMConfig, Message, ModelSize, RateLimitError
from src.domain.llm_providers.models import ModelMetadata, ProviderConfig, ProviderType
from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient
from src.infrastructure.llm.model_catalog import ModelCatalogService
from src.infrastructure.llm.model_registry import get_model_input_budget, get_model_max_input_tokens
from src.infrastructure.llm.provider_credentials import NO_API_KEY_SENTINEL


class DummyResponseModel(BaseModel):
    """Dummy response model for testing."""

    name: str
    value: int


class TestLiteLLMClient:
    """Test suite for LiteLLMClient."""

    @pytest.fixture
    def provider_config(self):
        """Create a test provider configuration."""
        return ProviderConfig(
            id=uuid4(),
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted_key",
            llm_model="gpt-4o",
            llm_small_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    @pytest.fixture
    def llm_config(self):
        """Create a test LLM config."""
        return LLMConfig(
            api_key="test_key",
            model="gpt-4o",
            small_model="gpt-4o-mini",
            temperature=0,
        )

    @pytest.fixture
    def client(self, provider_config, llm_config):
        """Create a LiteLLMClient instance."""
        with patch("src.infrastructure.llm.litellm.litellm_client.get_encryption_service"):
            return LiteLLMClient(
                config=llm_config,
                provider_config=provider_config,
                cache=False,
            )

    @pytest.mark.asyncio
    async def test_generate_response_basic(self, client):
        """Test basic response generation without structured output."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = {"content": "Test response"}

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = mock_response

            messages = [
                Message(role="system", content="You are a helpful assistant."),
                Message(role="user", content="Hello!"),
            ]

            response = await client._generate_response(messages)

            assert response == {"content": "Test response"}
            mock_acompletion.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_response_with_structured_output(self, client):
        """Test response generation with structured output."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = {"content": '{"name": "test", "value": 42}'}

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = mock_response

            messages = [
                Message(role="user", content="Generate a response"),
            ]

            response = await client._generate_response(messages, response_model=DummyResponseModel)

            assert response == {"name": "test", "value": 42}

    @pytest.mark.asyncio
    async def test_generate_response_handles_json_with_code_blocks(self, client):
        """Test that JSON response with markdown code blocks is handled correctly."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = {
            "content": '```json\n{"name": "test", "value": 42}\n```'
        }

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = mock_response

            messages = [Message(role="user", content="Generate a response")]

            response = await client._generate_response(messages, response_model=DummyResponseModel)

            assert response == {"name": "test", "value": 42}

    @pytest.mark.asyncio
    async def test_generate_response_rate_limit_error(self, client):
        """Test that rate limit errors are properly raised."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.side_effect = Exception("Rate limit exceeded: 429")

            messages = [Message(role="user", content="Test")]

            with pytest.raises(RateLimitError):
                await client._generate_response(messages)

    @pytest.mark.asyncio
    async def test_get_model_for_size_small(self, client):
        """Test model selection for small size."""
        model = client._get_model_for_size(ModelSize.small)
        assert model == "gpt-4o-mini"  # small_model

    @pytest.mark.asyncio
    async def test_get_model_for_size_medium(self, client):
        """Test model selection for medium size."""
        model = client._get_model_for_size(ModelSize.medium)
        assert model == "gpt-4o"  # default model

    @pytest.mark.asyncio
    async def test_get_provider_type(self, client):
        """Test provider type identification."""
        provider_type = client._get_provider_type()
        assert provider_type == "litellm-openai"

    @pytest.mark.asyncio
    async def test_generate_response_error_handling(self, client):
        """Test error handling in response generation."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.side_effect = Exception("API error")

            messages = [Message(role="user", content="Test")]

            with pytest.raises(Exception):
                await client._generate_response(messages)

    def test_get_model_max_input_tokens_default(self):
        """Should derive default input budget from context window and max output."""
        assert get_model_max_input_tokens("gpt-4o", max_output_tokens=16384) == 111616

    def test_get_model_max_input_tokens_qwen_specific(self):
        """qwen-max is now served by the catalog (context=32768, max_out=8192)."""
        # catalog: context_length=32768, no explicit max_input_tokens
        # derived: 32768 - 8192 = 24576
        assert get_model_max_input_tokens("qwen-max", max_output_tokens=8192) == 24576
        assert get_model_max_input_tokens("dashscope/qwen-max", max_output_tokens=8192) == 24576

    def test_get_model_input_budget_qwen_specific(self):
        """Should apply catalog-sourced budget ratio (0.85) for qwen-max."""
        # 24576 * 0.85 = 20889.6 -> int = 20889
        assert get_model_input_budget("qwen-max", max_output_tokens=8192) == 20889

    def test_build_completion_kwargs_trims_oversized_prompt(self, client):
        """Should trim oldest context to stay within model input budget."""
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "assistant", "content": "old context"},
            {"role": "user", "content": "latest request"},
        ]

        with (
            patch(
                "src.infrastructure.llm.litellm.litellm_client.get_model_input_budget",
                return_value=120,
            ),
            patch.object(client, "_estimate_input_tokens", side_effect=[400, 80]),
        ):
            kwargs = client._build_completion_kwargs(
                model="qwen-max",
                messages=messages,
                max_tokens=4096,
            )

        assert len(kwargs["messages"]) == 2
        assert kwargs["messages"][0]["role"] == "system"
        assert kwargs["messages"][1]["role"] == "user"

    def test_build_completion_kwargs_drops_orphan_tool_result_after_trim(self, client):
        """Should not send a tool result whose assistant tool call was trimmed away."""
        messages = [
            {"role": "system", "content": "system prompt"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "bash", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "large tool output"},
            {"role": "user", "content": "continue"},
        ]

        with (
            patch(
                "src.infrastructure.llm.litellm.litellm_client.get_model_input_budget",
                return_value=120,
            ),
            patch.object(client, "_estimate_input_tokens", side_effect=[400, 300, 80]),
        ):
            kwargs = client._build_completion_kwargs(
                model="qwen-max",
                messages=messages,
                max_tokens=4096,
            )

        assert [message["role"] for message in kwargs["messages"]] == ["system", "user"]
        assert all(message.get("tool_call_id") != "call-1" for message in kwargs["messages"])

    def test_build_completion_kwargs_prefers_max_completion_tokens(self, client):
        """Should avoid sending max_tokens when max_completion_tokens is requested."""
        kwargs = client._build_completion_kwargs(
            model="openai/o3",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=2048,
            max_completion_tokens=1024,
        )

        assert kwargs["max_completion_tokens"] == 1024
        assert "max_tokens" not in kwargs

    @pytest.mark.asyncio
    async def test_generate_stream_accepts_model_override_kwarg(self, client):
        """Should allow per-call model override without duplicate kwargs errors."""

        class _NoopLimiter:
            class _Ctx:
                async def __aenter__(self):
                    return None

                async def __aexit__(self, exc_type, exc, tb):
                    return False

            async def acquire(self, _provider_type):
                return self._Ctx()

        class _NoopCircuitBreaker:
            @staticmethod
            def can_execute() -> bool:
                return True

            @staticmethod
            def record_success() -> None:
                return None

            @staticmethod
            def record_failure() -> None:
                return None

        class _NoopRegistry:
            @staticmethod
            def get(_provider_type):
                return _NoopCircuitBreaker()

        async def _empty_stream():
            if False:
                yield None

        with (
            patch(
                "src.infrastructure.llm.litellm.litellm_client.get_provider_rate_limiter",
                return_value=_NoopLimiter(),
            ),
            patch(
                "src.infrastructure.llm.litellm.litellm_client.get_circuit_breaker_registry",
                return_value=_NoopRegistry(),
            ),
            patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion,
        ):
            mock_acompletion.return_value = _empty_stream()

            chunks = [
                chunk
                async for chunk in client.generate_stream(
                    messages=[Message(role="user", content="hello")],
                    model="volcengine/doubao-1.5-pro-32k-250115",
                )
            ]

        assert chunks == []
        assert mock_acompletion.call_count == 1
        called_kwargs = mock_acompletion.call_args.kwargs
        assert called_kwargs["model"] == "volcengine/doubao-1.5-pro-32k-250115"

    @pytest.mark.asyncio
    async def test_generate_stream_qualifies_unqualified_minimax_override(self):
        """Should qualify unqualified MiniMax override model before LiteLLM call."""

        class _NoopLimiter:
            class _Ctx:
                async def __aenter__(self):
                    return None

                async def __aexit__(self, exc_type, exc, tb):
                    return False

            async def acquire(self, _provider_type):
                return self._Ctx()

        class _NoopCircuitBreaker:
            @staticmethod
            def can_execute() -> bool:
                return True

            @staticmethod
            def record_success() -> None:
                return None

            @staticmethod
            def record_failure() -> None:
                return None

        class _NoopRegistry:
            @staticmethod
            def get(_provider_type):
                return _NoopCircuitBreaker()

        async def _empty_stream():
            if False:
                yield None

        provider_config = ProviderConfig(
            id=uuid4(),
            name="minimax-provider",
            provider_type=ProviderType.MINIMAX,
            api_key_encrypted="encrypted_key",
            llm_model="MiniMax-M2.5",
            llm_small_model="MiniMax-M2.5-highspeed",
            embedding_model="text-embedding-3-small",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        llm_config = LLMConfig(
            api_key="test_key",
            model="MiniMax-M2.5",
            small_model="MiniMax-M2.5-highspeed",
            temperature=0,
        )

        with patch("src.infrastructure.llm.litellm.litellm_client.get_encryption_service"):
            minimax_client = LiteLLMClient(
                config=llm_config,
                provider_config=provider_config,
                cache=False,
            )

        with (
            patch(
                "src.infrastructure.llm.litellm.litellm_client.get_provider_rate_limiter",
                return_value=_NoopLimiter(),
            ),
            patch(
                "src.infrastructure.llm.litellm.litellm_client.get_circuit_breaker_registry",
                return_value=_NoopRegistry(),
            ),
            patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion,
        ):
            mock_acompletion.return_value = _empty_stream()

            chunks = [
                chunk
                async for chunk in minimax_client.generate_stream(
                    messages=[Message(role="user", content="hello")],
                    model="MiniMax-M2.5-highspeed",
                )
            ]

        assert chunks == []
        assert mock_acompletion.call_count == 1
        called_kwargs = mock_acompletion.call_args.kwargs
        assert called_kwargs["model"] == "minimax/MiniMax-M2.5-highspeed"

    @pytest.mark.asyncio
    async def test_generate_accepts_model_override_kwarg(self, client):
        """Should use per-call model override in non-streaming generate path."""
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message = {"content": "Test response"}
        mock_choice.finish_reason = "stop"
        mock_response.choices = [mock_choice]

        with (
            patch.object(client, "_build_completion_kwargs", wraps=client._build_completion_kwargs) as mock_build,
            patch.object(client, "_execute_with_resilience", new_callable=AsyncMock) as mock_execute,
        ):
            mock_execute.return_value = mock_response
            await client.generate(
                messages=[Message(role="user", content="hello")],
                model="volcengine/doubao-1.5-pro-32k-250115",
            )

        called_model = mock_build.call_args.kwargs["model"]
        assert called_model == "volcengine/doubao-1.5-pro-32k-250115"

    @pytest.mark.asyncio
    async def test_generate_qualifies_unqualified_minimax_override(self):
        """Should qualify unqualified MiniMax override in non-streaming generate path."""
        provider_config = ProviderConfig(
            id=uuid4(),
            name="minimax-provider",
            provider_type=ProviderType.MINIMAX,
            api_key_encrypted="encrypted_key",
            llm_model="MiniMax-M2.5",
            llm_small_model="MiniMax-M2.5-highspeed",
            embedding_model="text-embedding-3-small",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        llm_config = LLMConfig(
            api_key="test_key",
            model="MiniMax-M2.5",
            small_model="MiniMax-M2.5-highspeed",
            temperature=0,
        )

        with patch("src.infrastructure.llm.litellm.litellm_client.get_encryption_service"):
            minimax_client = LiteLLMClient(
                config=llm_config,
                provider_config=provider_config,
                cache=False,
            )

        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message = {"content": "Test response"}
        mock_choice.finish_reason = "stop"
        mock_response.choices = [mock_choice]

        with (
            patch.object(
                minimax_client,
                "_build_completion_kwargs",
                wraps=minimax_client._build_completion_kwargs,
            ) as mock_build,
            patch.object(minimax_client, "_execute_with_resilience", new_callable=AsyncMock) as mock_execute,
        ):
            mock_execute.return_value = mock_response
            await minimax_client.generate(
                messages=[Message(role="user", content="hello")],
                model="MiniMax-M2.5-highspeed",
            )

        called_model = mock_build.call_args.kwargs["model"]
        assert called_model == "minimax/MiniMax-M2.5-highspeed"

    def test_trim_messages_truncates_when_tokenizer_underestimates(self, client):
        """Should truncate oversized prompts even when token counter underestimates."""
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "你" * 40000},
        ]
        model = "dashscope/qwen-max"

        with patch.object(client, "_estimate_input_tokens", return_value=100):
            trimmed = client._trim_messages_to_input_limit(
                model=model,
                messages=messages,
                max_tokens=4096,
            )

        assert len(trimmed) == 1
        assert trimmed[0]["role"] == "user"
        assert len(trimmed[0]["content"]) < len(messages[1]["content"])
        assert client._estimate_effective_input_tokens(
            model, trimmed
        ) < client._estimate_effective_input_tokens(model, messages)

    def test_ollama_without_api_key_uses_default_base_url(self):
        """Ollama should allow missing API key and apply local default api_base."""
        provider_config = ProviderConfig(
            id=uuid4(),
            name="ollama-provider",
            provider_type=ProviderType.OLLAMA,
            api_key_encrypted="encrypted_key",
            llm_model="llama3.1:8b",
            llm_small_model="llama3.1:8b",
            embedding_model="nomic-embed-text",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        llm_config = LLMConfig(
            api_key="",
            model="llama3.1:8b",
            small_model="llama3.1:8b",
            temperature=0,
        )

        with patch(
            "src.infrastructure.llm.litellm.litellm_client.get_encryption_service"
        ) as mock_get:
            mock_encryption = MagicMock()
            mock_encryption.decrypt.return_value = NO_API_KEY_SENTINEL
            mock_get.return_value = mock_encryption
            client = LiteLLMClient(
                config=llm_config,
                provider_config=provider_config,
                cache=False,
            )

        kwargs = client._build_completion_kwargs(
            model=client._get_model_for_size(ModelSize.medium),
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=256,
        )
        assert kwargs["model"] == "ollama/llama3.1:8b"
        assert kwargs["api_base"] == "http://localhost:11434"
        assert "api_key" not in kwargs

    def test_openrouter_uses_openai_prefix_and_default_base_url(self):
        """OpenRouter should use OpenAI-compatible model prefix and default base URL."""
        provider_config = ProviderConfig(
            id=uuid4(),
            name="openrouter-provider",
            provider_type=ProviderType.OPENROUTER,
            api_key_encrypted="encrypted_key",
            llm_model="gpt-4o",
            llm_small_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        llm_config = LLMConfig(
            api_key="sk-or-test",
            model="gpt-4o",
            small_model="gpt-4o-mini",
            temperature=0,
        )
        with patch("src.infrastructure.llm.litellm.litellm_client.get_encryption_service"):
            client = LiteLLMClient(
                config=llm_config,
                provider_config=provider_config,
                cache=False,
            )

        kwargs = client._build_completion_kwargs(
            model=client._get_model_for_size(ModelSize.medium),
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=256,
        )
        assert kwargs["model"] == "openai/gpt-4o"
        assert kwargs["api_base"] == "https://openrouter.ai/api/v1"
        assert kwargs["api_key"] == "sk-or-test"


class TestLiteLLMClientDeepseek:
    """Test suite for LiteLLMClient with Deepseek provider."""

    @pytest.fixture
    def deepseek_provider_config(self):
        """Create a test Deepseek provider configuration."""
        return ProviderConfig(
            id=uuid4(),
            name="test-deepseek-provider",
            provider_type=ProviderType.DEEPSEEK,
            api_key_encrypted="encrypted_key",
            llm_model="deepseek-chat",
            llm_small_model="deepseek-coder",
            embedding_model=None,
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    @pytest.fixture
    def deepseek_llm_config(self):
        """Create a test Deepseek LLM config."""
        return LLMConfig(
            api_key="test_key",
            model="deepseek-chat",
            small_model="deepseek-coder",
            temperature=0,
        )

    @pytest.fixture
    def deepseek_client(self, deepseek_provider_config, deepseek_llm_config):
        """Create a LiteLLMClient instance for Deepseek."""
        with patch("src.infrastructure.llm.litellm.litellm_client.get_encryption_service"):
            return LiteLLMClient(
                config=deepseek_llm_config,
                provider_config=deepseek_provider_config,
                cache=False,
            )

    @pytest.mark.asyncio
    async def test_deepseek_generate_response_basic(self, deepseek_client):
        """Test basic response generation with Deepseek."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = {"content": "Deepseek response"}

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = mock_response

            messages = [
                Message(role="system", content="You are a helpful assistant."),
                Message(role="user", content="Hello!"),
            ]

            response = await deepseek_client._generate_response(messages)

            assert response == {"content": "Deepseek response"}
            mock_acompletion.assert_called_once()
            # Check that the model has the deepseek prefix
            call_kwargs = mock_acompletion.call_args.kwargs
            assert "deepseek/" in call_kwargs["model"]

    @pytest.mark.asyncio
    async def test_deepseek_get_model_for_size_small(self, deepseek_client):
        """Test model selection for small size with Deepseek."""
        model = deepseek_client._get_model_for_size(ModelSize.small)
        assert model == "deepseek/deepseek-coder"

    @pytest.mark.asyncio
    async def test_deepseek_get_model_for_size_medium(self, deepseek_client):
        """Test model selection for medium size with Deepseek."""
        model = deepseek_client._get_model_for_size(ModelSize.medium)
        assert model == "deepseek/deepseek-chat"

    @pytest.mark.asyncio
    async def test_deepseek_get_provider_type(self, deepseek_client):
        """Test provider type identification for Deepseek."""
        provider_type = deepseek_client._get_provider_type()
        assert provider_type == "litellm-deepseek"


class TestLiteLLMClientZhipu:
    """Test suite for LiteLLMClient with ZhipuAI provider."""

    @pytest.fixture
    def zhipu_provider_config(self):
        """Create a test ZhipuAI provider configuration."""
        return ProviderConfig(
            id=uuid4(),
            name="test-zhipu-provider",
            provider_type=ProviderType.ZAI,  # ZAI is the provider type for ZhipuAI
            api_key_encrypted="encrypted_key",
            llm_model="glm-4-plus",
            llm_small_model="glm-4-flash",
            embedding_model="embedding-3",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    @pytest.fixture
    def zhipu_llm_config(self):
        """Create a test ZhipuAI LLM config."""
        return LLMConfig(
            api_key="test_key",
            model="glm-4-plus",
            small_model="glm-4-flash",
            temperature=0,
        )

    @pytest.fixture
    def zhipu_client(self, zhipu_provider_config, zhipu_llm_config):
        """Create a LiteLLMClient instance for ZhipuAI."""
        with patch("src.infrastructure.llm.litellm.litellm_client.get_encryption_service"):
            return LiteLLMClient(
                config=zhipu_llm_config,
                provider_config=zhipu_provider_config,
                cache=False,
            )

    @pytest.mark.asyncio
    async def test_zhipu_generate_response_basic(self, zhipu_client):
        """Test basic response generation with ZhipuAI."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = {"content": "ZhipuAI response"}

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = mock_response

            messages = [
                Message(role="system", content="You are a helpful assistant."),
                Message(role="user", content="Hello!"),
            ]

            response = await zhipu_client._generate_response(messages)

            assert response == {"content": "ZhipuAI response"}
            mock_acompletion.assert_called_once()
            # Check that the model has the zai prefix (LiteLLM official prefix for ZhipuAI)
            call_kwargs = mock_acompletion.call_args.kwargs
            assert "zai/" in call_kwargs["model"]

    @pytest.mark.asyncio
    async def test_zhipu_get_model_for_size_small(self, zhipu_client):
        """Test model selection for small size with ZhipuAI."""
        model = zhipu_client._get_model_for_size(ModelSize.small)
        # ZAI uses zai/ prefix for LiteLLM
        assert model == "zai/glm-4-flash"

    @pytest.mark.asyncio
    async def test_zhipu_get_model_for_size_medium(self, zhipu_client):
        """Test model selection for medium size with ZhipuAI."""
        model = zhipu_client._get_model_for_size(ModelSize.medium)
        # ZAI uses zai/ prefix for LiteLLM
        assert model == "zai/glm-4-plus"

    @pytest.mark.asyncio
    async def test_zhipu_get_provider_type(self, zhipu_client):
        """Test provider type identification for ZhipuAI."""
        provider_type = zhipu_client._get_provider_type()
        assert provider_type == "litellm-zai"


@pytest.mark.unit
class TestLiteLLMClientMandatorySkillProtection:
    """Test suite for mandatory-skill system prompt protection in LiteLLMClient."""

    @pytest.fixture
    def provider_config(self):
        """Create a test provider configuration."""
        return ProviderConfig(
            id=uuid4(),
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted_key",
            llm_model="gpt-4o",
            llm_small_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    @pytest.fixture
    def llm_config(self):
        """Create a test LLM config."""
        return LLMConfig(
            api_key="test_key",
            model="gpt-4o",
            small_model="gpt-4o-mini",
            temperature=0,
        )

    @pytest.fixture
    def client(self, provider_config, llm_config):
        """Create a LiteLLMClient instance."""
        with patch("src.infrastructure.llm.litellm.litellm_client.get_encryption_service"):
            return LiteLLMClient(
                config=llm_config,
                provider_config=provider_config,
                cache=False,
            )

    def _make_system_content_with_skill(self) -> str:
        """Build a system prompt containing a mandatory-skill block."""
        return (
            "You are helpful.\n\n"
            "## Available SubAgents (Specialized Autonomous Agents)\n"
            "Some subagent descriptions here\n\n"
            "## Workspace Guidelines\n"
            "Some workspace content\n\n"
            '<mandatory-skill name="test-skill">\n'
            "Follow these skill instructions precisely.\n"
            "</mandatory-skill>"
        )

    def test_trim_messages_preserves_system_with_mandatory_skill(self, client):
        """System message with mandatory-skill must NOT be deleted even when over limit."""
        # Arrange
        system_content = self._make_system_content_with_skill()
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": "user request"},
        ]

        with (
            patch(
                "src.infrastructure.llm.litellm.litellm_client.get_model_input_budget",
                return_value=50,
            ),
            patch(
                "src.infrastructure.llm.litellm.litellm_client.get_model_max_input_tokens",
                return_value=100,
            ),
            patch.object(
                client,
                "_estimate_effective_input_tokens",
                return_value=999,
            ),
        ):
            # Act
            trimmed = client._trim_messages_to_input_limit(
                model="gpt-4o",
                messages=messages,
                max_tokens=4096,
            )

        # Assert -- system message must survive
        system_msgs = [m for m in trimmed if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert "<mandatory-skill" in system_msgs[0]["content"]

    def test_trim_messages_deletes_system_without_mandatory_skill(self, client):
        """System message without mandatory-skill IS deleted when over limit."""
        # Arrange
        messages = [
            {"role": "system", "content": "Plain system prompt without skills"},
            {"role": "user", "content": "user request"},
        ]

        # Return high token count so we stay over budget after removing middle msgs
        with (
            patch(
                "src.infrastructure.llm.litellm.litellm_client.get_model_input_budget",
                return_value=50,
            ),
            patch(
                "src.infrastructure.llm.litellm.litellm_client.get_model_max_input_tokens",
                return_value=100,
            ),
            patch.object(
                client,
                "_estimate_effective_input_tokens",
                return_value=999,
            ),
        ):
            # Act
            trimmed = client._trim_messages_to_input_limit(
                model="gpt-4o",
                messages=messages,
                max_tokens=4096,
            )

        # Assert -- system message should be removed
        system_msgs = [m for m in trimmed if m["role"] == "system"]
        assert len(system_msgs) == 0

    def test_trim_system_prompt_preserve_skill_extracts_block(self):
        """_trim_system_prompt_preserve_skill removes SubAgent/Workspace but keeps skill."""
        # Arrange
        content = (
            "You are helpful.\n\n"
            "## Available SubAgents (Specialized Autonomous Agents)\n"
            "Some subagent descriptions here\n\n"
            "## Workspace Guidelines\n"
            "Some workspace content\n\n"
            '<mandatory-skill name="test-skill">\n'
            "Follow these skill instructions precisely.\n"
            "</mandatory-skill>"
        )

        # Act
        result = LiteLLMClient._trim_system_prompt_preserve_skill(content)

        # Assert -- mandatory-skill block preserved
        assert '<mandatory-skill name="test-skill">' in result
        assert "Follow these skill instructions precisely." in result
        assert "</mandatory-skill>" in result
        # Assert -- removable sections stripped
        assert "## Available SubAgents" not in result
        assert "Some subagent descriptions here" not in result
        assert "## Workspace Guidelines" not in result
        assert "Some workspace content" not in result
        # Assert -- core intro preserved
        assert "You are helpful." in result

    def test_trim_system_prompt_preserve_skill_noop_without_block(self):
        """_trim_system_prompt_preserve_skill returns content unchanged when no skill block."""
        # Arrange
        content = (
            "You are helpful.\n\n"
            "## Available SubAgents (Specialized Autonomous Agents)\n"
            "Some subagent descriptions here"
        )

        # Act
        result = LiteLLMClient._trim_system_prompt_preserve_skill(content)

        # Assert -- returned unchanged
        assert result == content

    def test_trim_system_prompt_preserve_skill_restores_if_accidentally_removed(self):
        """If regex removal accidentally deletes skill block, it gets restored."""
        # Arrange -- skill block nested inside a SubAgent section header boundary
        # The regex `## Available SubAgents.*?(?=\n## |\n<|\Z)` uses lookahead for `\n<`
        # so the skill block after a section should survive. But the safety net in the code
        # re-prepends it if lost. We test the safety net directly.
        content = (
            "## Available SubAgents (Specialized Autonomous Agents)\n"
            "Subagent content\n"
            "## Workspace Guidelines\n"
            "Workspace content\n"
            '<mandatory-skill name="rescue">\n'
            "Important instructions\n"
            "</mandatory-skill>"
        )

        # Act
        result = LiteLLMClient._trim_system_prompt_preserve_skill(content)

        # Assert -- mandatory-skill block must be present regardless
        assert '<mandatory-skill name="rescue">' in result
        assert "Important instructions" in result
        assert "</mandatory-skill>" in result



@pytest.mark.unit
class TestBuildCompletionKwargsParamResolver:
    """Test _build_completion_kwargs with param_resolver integration."""

    @pytest.fixture
    def provider_config(self):
        """Create a test provider configuration."""
        return ProviderConfig(
            id=uuid4(),
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted_key",
            llm_model="gpt-4o",
            llm_small_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    @pytest.fixture
    def provider_config_with_overrides(self):
        """Create a provider config with temperature override."""
        return ProviderConfig(
            id=uuid4(),
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted_key",
            llm_model="gpt-4o",
            llm_small_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            config={"temperature": 0.5},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    @pytest.fixture
    def llm_config(self):
        """Create a test LLM config with temperature=0."""
        return LLMConfig(
            api_key="test_key",
            model="gpt-4o",
            small_model="gpt-4o-mini",
            temperature=0,
        )

    @pytest.fixture
    def llm_config_no_temp(self):
        """Create a test LLM config with temperature=None."""
        return LLMConfig(
            api_key="test_key",
            model="gpt-4o",
            small_model="gpt-4o-mini",
            temperature=None,
        )

    @pytest.fixture
    def client(self, provider_config, llm_config):
        """Create a LiteLLMClient instance."""
        with patch(
            "src.infrastructure.llm.litellm.litellm_client.get_encryption_service"
        ):
            return LiteLLMClient(
                config=llm_config,
                provider_config=provider_config,
                cache=False,
            )

    @pytest.fixture
    def client_with_config_overrides(
        self, provider_config_with_overrides, llm_config
    ):
        """Create a LiteLLMClient with provider config overrides."""
        with patch(
            "src.infrastructure.llm.litellm.litellm_client.get_encryption_service"
        ):
            return LiteLLMClient(
                config=llm_config,
                provider_config=provider_config_with_overrides,
                cache=False,
            )

    @pytest.fixture
    def client_no_temp(
        self, provider_config, llm_config_no_temp
    ):
        """Create a LiteLLMClient with temperature=None in LLMConfig."""
        with patch(
            "src.infrastructure.llm.litellm.litellm_client.get_encryption_service"
        ):
            return LiteLLMClient(
                config=llm_config_no_temp,
                provider_config=provider_config,
                cache=False,
            )

    @pytest.fixture
    def client_with_provider_override_temp(
        self, provider_config_with_overrides, llm_config_no_temp
    ):
        """Create a client with provider config temp override."""
        with patch(
            "src.infrastructure.llm.litellm.litellm_client.get_encryption_service"
        ):
            return LiteLLMClient(
                config=llm_config_no_temp,
                provider_config=provider_config_with_overrides,
                cache=False,
            )

    def test_temperature_from_explicit_param(self, client):
        """Test that explicit temperature param is in kwargs."""
        # Arrange
        messages = [{"role": "user", "content": "hello"}]
        model = "gpt-4o"
        max_tokens = 4096

        # Act
        kwargs = client._build_completion_kwargs(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
        )

        # Assert
        assert "temperature" in kwargs
        assert kwargs["temperature"] == 0.7

    def test_temperature_from_llm_config_fallback(self, client):
        """Test temperature fallback from LLMConfig."""
        # Arrange
        messages = [{"role": "user", "content": "hello"}]
        model = "gpt-4o"
        max_tokens = 4096

        # Act
        # Don't pass explicit temperature, should fallback to LLMConfig
        kwargs = client._build_completion_kwargs(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        )

        # Assert
        # LLMConfig has temperature=0, which should be in kwargs
        assert "temperature" in kwargs
        assert kwargs["temperature"] == 0

    def test_top_p_flows_through_extra_to_resolver(self, client):
        """Test that top_p passed via extra flows to kwargs."""
        # Arrange
        messages = [{"role": "user", "content": "hello"}]
        model = "gpt-4o"
        max_tokens = 4096

        # Act
        kwargs = client._build_completion_kwargs(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            top_p=0.9,
        )

        # Assert
        assert "top_p" in kwargs
        assert kwargs["top_p"] == 0.9

    def test_seed_flows_through_extra_to_resolver(self, client):
        """Test that seed passed via extra flows to kwargs."""
        # Arrange
        messages = [{"role": "user", "content": "hello"}]
        model = "gpt-4o"
        max_tokens = 4096

        # Act
        kwargs = client._build_completion_kwargs(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            seed=42,
        )

        # Assert
        assert "seed" in kwargs
        assert kwargs["seed"] == 42

    def test_provider_config_overrides_temperature(
        self, client_with_provider_override_temp
    ):
        """Test that provider_config.config temperature is used."""
        # Arrange
        messages = [{"role": "user", "content": "hello"}]
        model = "gpt-4o"
        max_tokens = 4096

        # Act
        # No explicit temp, LLMConfig temp is None, but provider config
        # has temperature=0.5
        kwargs = client_with_provider_override_temp._build_completion_kwargs(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        )

        # Assert
        # Should get 0.5 from provider_config.config
        assert "temperature" in kwargs
        assert kwargs["temperature"] == 0.5

    def test_passthrough_keys_bypass_resolver(self, client):
        """Test stream and tools pass through without resolver."""
        # Arrange
        messages = [{"role": "user", "content": "hello"}]
        model = "gpt-4o"
        max_tokens = 4096
        tools = [{"type": "function"}]

        # Act
        kwargs = client._build_completion_kwargs(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
            tools=tools,
        )

        # Assert
        assert "stream" in kwargs
        assert kwargs["stream"] is True
        assert "tools" in kwargs
        assert kwargs["tools"] == tools

    def test_drop_params_always_present(self, client):
        """Test that drop_params=True is always in kwargs."""
        # Arrange
        messages = [{"role": "user", "content": "hello"}]
        model = "gpt-4o"
        max_tokens = 4096

        # Act
        kwargs = client._build_completion_kwargs(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        )

        # Assert
        assert "drop_params" in kwargs
        assert kwargs["drop_params"] is True

    def test_max_tokens_from_clamp_not_resolver(self, client):
        """Test max_tokens is clamped, not from resolver."""
        # Arrange
        messages = [{"role": "user", "content": "hello"}]
        model = "gpt-4o"
        max_tokens = 4096

        # Act
        kwargs = client._build_completion_kwargs(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            seed=42,  # Pass via extra but not max_tokens
        )

        # Assert
        # max_tokens should be present from clamping, not from resolver
        assert "max_tokens" in kwargs
        assert isinstance(kwargs["max_tokens"], int)
        assert kwargs["max_tokens"] > 0

    def test_mixed_resolver_and_passthrough(self, client):
        """Test resolver params and passthrough both present."""
        # Arrange
        messages = [{"role": "user", "content": "hello"}]
        model = "gpt-4o"
        max_tokens = 4096

        # Act
        kwargs = client._build_completion_kwargs(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            top_p=0.9,  # resolver param
            stream=True,  # passthrough param
        )

        # Assert
        assert "top_p" in kwargs
        assert kwargs["top_p"] == 0.9
        assert "stream" in kwargs
        assert kwargs["stream"] is True

    def test_explicit_temperature_overrides_provider_config(
        self, client_with_config_overrides
    ):
        """Test explicit temp overrides provider_config temp."""
        # Arrange
        messages = [{"role": "user", "content": "hello"}]
        model = "gpt-4o"
        max_tokens = 4096

        # Act
        # Provider config has temp=0.5, but we pass explicit temp=0.9
        kwargs = client_with_config_overrides._build_completion_kwargs(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.9,
        )

        # Assert
        # Explicit param should win
        assert "temperature" in kwargs
        assert kwargs["temperature"] == 0.9


@pytest.mark.unit
class TestBuildCompletionKwargsCatalogIntegration:
    """Tests for catalog-based parameter defaults in _build_completion_kwargs."""

    @pytest.fixture
    def catalog_metadata(self):
        """Create a ModelMetadata with known defaults for testing."""
        return ModelMetadata(
            name="gpt-4o",
            context_length=128000,
            max_output_tokens=4096,
            default_temperature=0.7,
            default_top_p=0.9,
            default_frequency_penalty=0.1,
            supports_temperature=True,
            supports_top_p=True,
            supports_frequency_penalty=True,
            supports_presence_penalty=True,
            supports_seed=True,
            temperature_range=[0.0, 1.0],
        )

    @pytest.fixture
    def mock_catalog(self, catalog_metadata):
        """Create a mock ModelCatalogService returning catalog_metadata."""
        catalog = MagicMock(spec=ModelCatalogService)
        catalog.get_model_fuzzy.return_value = catalog_metadata
        return catalog

    @pytest.fixture
    def provider_config(self):
        """Create a test provider configuration."""
        return ProviderConfig(
            id=uuid4(),
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted_key",
            llm_model="gpt-4o",
            llm_small_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    @pytest.fixture
    def llm_config_no_temp(self):
        """LLMConfig with temperature=None so catalog default wins."""
        return LLMConfig(
            api_key="test_key",
            model="gpt-4o",
            small_model="gpt-4o-mini",
            temperature=None,
        )

    @pytest.fixture
    def client_with_catalog(
        self, provider_config, llm_config_no_temp, mock_catalog
    ):
        """LiteLLMClient with a mock catalog injected."""
        with patch(
            "src.infrastructure.llm.litellm.litellm_client.get_encryption_service"
        ):
            return LiteLLMClient(
                config=llm_config_no_temp,
                provider_config=provider_config,
                cache=False,
                catalog=mock_catalog,
            )

    @pytest.fixture
    def client_no_catalog(self, provider_config, llm_config_no_temp):
        """LiteLLMClient without any catalog."""
        with patch(
            "src.infrastructure.llm.litellm.litellm_client.get_encryption_service"
        ):
            return LiteLLMClient(
                config=llm_config_no_temp,
                provider_config=provider_config,
                cache=False,
                catalog=None,
            )

    def test_catalog_defaults_flow_when_no_override(
        self, client_with_catalog
    ):
        """Catalog defaults appear when no user/provider override is set."""
        # Arrange
        messages = [{"role": "user", "content": "hello"}]

        # Act
        kwargs = client_with_catalog._build_completion_kwargs(
            model="gpt-4o",
            messages=messages,
            max_tokens=4096,
        )

        # Assert — catalog default_temperature=0.7 should be used
        assert "temperature" in kwargs
        assert kwargs["temperature"] == 0.7

    def test_user_override_wins_over_catalog_default(
        self, client_with_catalog
    ):
        """Explicit user param beats catalog default."""
        # Arrange
        messages = [{"role": "user", "content": "hello"}]

        # Act
        kwargs = client_with_catalog._build_completion_kwargs(
            model="gpt-4o",
            messages=messages,
            max_tokens=4096,
            temperature=0.3,
        )

        # Assert — user's 0.3 should win over catalog's 0.7
        assert kwargs["temperature"] == 0.3

    def test_provider_config_wins_over_catalog_default(self, mock_catalog):
        """Provider config (JSONB) override beats catalog default."""
        # Arrange — provider config has top_p=0.8, catalog has 0.9
        provider_config = ProviderConfig(
            id=uuid4(),
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted_key",
            llm_model="gpt-4o",
            llm_small_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            config={"top_p": 0.8},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        llm_config = LLMConfig(
            api_key="test_key",
            model="gpt-4o",
            small_model="gpt-4o-mini",
            temperature=None,
        )
        with patch(
            "src.infrastructure.llm.litellm.litellm_client.get_encryption_service"
        ):
            client = LiteLLMClient(
                config=llm_config,
                provider_config=provider_config,
                cache=False,
                catalog=mock_catalog,
            )

        messages = [{"role": "user", "content": "hello"}]

        # Act
        kwargs = client._build_completion_kwargs(
            model="gpt-4o",
            messages=messages,
            max_tokens=4096,
        )

        # Assert — provider 0.8 should win over catalog 0.9
        assert kwargs["top_p"] == 0.8

    def test_catalog_none_means_no_catalog_defaults(
        self, client_no_catalog
    ):
        """Client without catalog still works; resolver returns no defaults."""
        # Arrange
        messages = [{"role": "user", "content": "hello"}]

        # Act
        kwargs = client_no_catalog._build_completion_kwargs(
            model="gpt-4o",
            messages=messages,
            max_tokens=4096,
        )

        # Assert — no catalog, no LLMConfig temp, no provider temp
        # so temperature should not appear in output
        assert "temperature" not in kwargs

    def test_catalog_unsupported_param_dropped(self):
        """Catalog says supports_frequency_penalty=False; user's value is dropped."""
        # Arrange — catalog says frequency_penalty not supported
        metadata = ModelMetadata(
            name="gpt-4o",
            context_length=128000,
            max_output_tokens=4096,
            supports_frequency_penalty=False,
        )
        catalog = MagicMock(spec=ModelCatalogService)
        catalog.get_model_fuzzy.return_value = metadata

        provider_config = ProviderConfig(
            id=uuid4(),
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted_key",
            llm_model="gpt-4o",
            llm_small_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        llm_config = LLMConfig(
            api_key="test_key",
            model="gpt-4o",
            small_model="gpt-4o-mini",
            temperature=None,
        )
        with patch(
            "src.infrastructure.llm.litellm.litellm_client.get_encryption_service"
        ):
            client = LiteLLMClient(
                config=llm_config,
                provider_config=provider_config,
                cache=False,
                catalog=catalog,
            )

        messages = [{"role": "user", "content": "hello"}]

        # Act — user passes frequency_penalty but catalog says unsupported
        kwargs = client._build_completion_kwargs(
            model="gpt-4o",
            messages=messages,
            max_tokens=4096,
            frequency_penalty=0.5,
        )

        # Assert — should be dropped
        assert "frequency_penalty" not in kwargs

    def test_catalog_temperature_clamped_to_range(self):
        """Temperature exceeding catalog range is clamped."""
        # Arrange — catalog says temperature_range=[0.0, 1.0]
        metadata = ModelMetadata(
            name="gpt-4o",
            context_length=128000,
            max_output_tokens=4096,
            supports_temperature=True,
            temperature_range=[0.0, 1.0],
        )
        catalog = MagicMock(spec=ModelCatalogService)
        catalog.get_model_fuzzy.return_value = metadata

        provider_config = ProviderConfig(
            id=uuid4(),
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted_key",
            llm_model="gpt-4o",
            llm_small_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        llm_config = LLMConfig(
            api_key="test_key",
            model="gpt-4o",
            small_model="gpt-4o-mini",
            temperature=None,
        )
        with patch(
            "src.infrastructure.llm.litellm.litellm_client.get_encryption_service"
        ):
            client = LiteLLMClient(
                config=llm_config,
                provider_config=provider_config,
                cache=False,
                catalog=catalog,
            )

        messages = [{"role": "user", "content": "hello"}]

        # Act — user passes temperature=1.5 which exceeds range
        kwargs = client._build_completion_kwargs(
            model="gpt-4o",
            messages=messages,
            max_tokens=4096,
            temperature=1.5,
        )

        # Assert — should be clamped to 1.0 (max of range)
        assert kwargs["temperature"] == 1.0

    def test_create_litellm_client_forwards_catalog(self):
        """Factory function forwards catalog arg to LiteLLMClient."""
        from src.infrastructure.llm.litellm.litellm_client import (
            create_litellm_client,
        )

        # Arrange
        catalog = MagicMock(spec=ModelCatalogService)
        provider_config = ProviderConfig(
            id=uuid4(),
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted_key",
            llm_model="gpt-4o",
            llm_small_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        # Act
        with patch(
            "src.infrastructure.llm.litellm.litellm_client.get_encryption_service"
        ) as mock_get_enc:
            mock_enc = MagicMock()
            mock_enc.decrypt.return_value = "test_key"
            mock_get_enc.return_value = mock_enc
            client = create_litellm_client(
                provider_config=provider_config,
                cache=False,
                catalog=catalog,
            )

        # Assert — client should have the catalog stored
        assert client._catalog is catalog


@pytest.mark.unit
class TestVisionCapabilityGating:
    """Tests for vision/image capability gating in LiteLLMClient."""

    # -- helpers / fixtures ------------------------------------

    @staticmethod
    def _text_only_messages() -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]

    @staticmethod
    def _image_messages() -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": "You are helpful."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/img.png"},
                    },
                ],
            },
        ]

    @pytest.fixture
    def vision_catalog(self) -> MagicMock:
        """Catalog where model supports vision."""
        catalog = MagicMock(spec=ModelCatalogService)
        catalog.supports_vision.return_value = True
        catalog.get_model_fuzzy.return_value = ModelMetadata(
            name="gpt-4o",
            provider="openai",
            context_length=128000,
            max_output_tokens=4096,
        )
        return catalog

    @pytest.fixture
    def no_vision_catalog(self) -> MagicMock:
        """Catalog where model does NOT support vision."""
        catalog = MagicMock(spec=ModelCatalogService)
        catalog.supports_vision.return_value = False
        catalog.get_model_fuzzy.return_value = ModelMetadata(
            name="gpt-3.5-turbo",
            provider="openai",
            context_length=16385,
            max_output_tokens=4096,
        )
        return catalog

    def _make_client(
        self,
        catalog: ModelCatalogService | None = None,
    ) -> LiteLLMClient:
        config = LLMConfig(api_key="test_key")
        provider_config = ProviderConfig(
            id=uuid4(),
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted_key",
            llm_model="gpt-4o",
            llm_small_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        return LiteLLMClient(
            config=config,
            provider_config=provider_config,
            cache=False,
            catalog=catalog,
        )

    # -- _has_image_content tests --------------------------------

    def test_has_image_content_detects_image_url_parts(self):
        """_has_image_content returns True for messages with image_url parts."""
        assert LiteLLMClient._has_image_content(self._image_messages()) is True

    def test_has_image_content_false_for_text_only(self):
        """_has_image_content returns False for plain text messages."""
        assert LiteLLMClient._has_image_content(self._text_only_messages()) is False

    def test_has_image_content_false_for_empty_messages(self):
        """_has_image_content returns False for empty message list."""
        assert LiteLLMClient._has_image_content([]) is False

    def test_has_image_content_false_for_text_parts_only(self):
        """_has_image_content returns False when content list has only text parts."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Just text"},
                    {"type": "text", "text": "More text"},
                ],
            },
        ]
        assert LiteLLMClient._has_image_content(messages) is False

    def test_has_image_content_detects_nested_in_later_message(self):
        """_has_image_content finds image_url even in non-first messages."""
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "text question"},
            {"role": "assistant", "content": "answer"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Now look at this"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abc"},
                    },
                ],
            },
        ]
        assert LiteLLMClient._has_image_content(messages) is True

    # -- _build_completion_kwargs gating tests --------------------

    def test_non_vision_model_with_image_raises_value_error(
        self, no_vision_catalog: MagicMock
    ):
        """Non-vision model receiving image content raises ValueError."""
        client = self._make_client(catalog=no_vision_catalog)
        with pytest.raises(ValueError, match="Invalid parameter"):
            client._build_completion_kwargs(
                model="gpt-3.5-turbo",
                messages=self._image_messages(),
                max_tokens=1024,
            )

    def test_vision_model_with_image_passes_through(
        self, vision_catalog: MagicMock
    ):
        """Vision-capable model with image content passes without error."""
        client = self._make_client(catalog=vision_catalog)
        kwargs = client._build_completion_kwargs(
            model="gpt-4o",
            messages=self._image_messages(),
            max_tokens=1024,
        )
        # Should return valid kwargs dict without raising
        assert kwargs["model"] == "gpt-4o"
        assert "messages" in kwargs

    def test_no_catalog_with_image_passes_through(self):
        """When catalog is None, image content passes through (graceful)."""
        client = self._make_client(catalog=None)
        kwargs = client._build_completion_kwargs(
            model="some-model",
            messages=self._image_messages(),
            max_tokens=1024,
        )
        assert kwargs["model"] == "some-model"
        assert "messages" in kwargs

    def test_no_image_content_with_non_vision_model_passes(
        self, no_vision_catalog: MagicMock
    ):
        """Text-only messages pass through even for non-vision models."""
        client = self._make_client(catalog=no_vision_catalog)
        kwargs = client._build_completion_kwargs(
            model="gpt-3.5-turbo",
            messages=self._text_only_messages(),
            max_tokens=1024,
        )
        assert kwargs["model"] == "gpt-3.5-turbo"

    def test_vision_gating_error_matches_client_error_detection(
        self, no_vision_catalog: MagicMock
    ):
        """The ValueError message matches _is_client_error() indicators.

        This ensures the circuit breaker is NOT tripped for vision
        gating rejections.
        """
        client = self._make_client(catalog=no_vision_catalog)
        with pytest.raises(ValueError) as exc_info:
            client._build_completion_kwargs(
                model="gpt-3.5-turbo",
                messages=self._image_messages(),
                max_tokens=1024,
            )
        # Verify _is_client_error classifies this correctly
        assert LiteLLMClient._is_client_error(exc_info.value) is True


@pytest.mark.unit
class TestMultimodalFormatTranslation:
    """B3.2 verification: OpenAI-format image_url messages pass through unchanged.

    LiteLLM handles provider-specific translation (Gemini inline_data,
    Anthropic source/base64, etc.) automatically. Our job is to NOT
    mangle the standard format before handing off.
    """

    @staticmethod
    def _vision_catalog() -> MagicMock:
        catalog = MagicMock(spec=ModelCatalogService)
        catalog.supports_vision.return_value = True
        return catalog

    @staticmethod
    def _make_client(catalog: MagicMock | None = None) -> LiteLLMClient:
        config = LLMConfig(api_key="test_key")
        provider_config = ProviderConfig(
            id=uuid4(),
            name="test-gemini",
            provider_type=ProviderType.GEMINI,
            api_key_encrypted="encrypted_key",
            llm_model="gemini-2.0-flash",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        return LiteLLMClient(
            config=config,
            provider_config=provider_config,
            cache=False,
            catalog=catalog,
        )

    def test_openai_image_url_format_preserved_for_litellm(self) -> None:
        """URL-based image_url parts must pass through unchanged."""
        client = self._make_client(catalog=self._vision_catalog())
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "https://example.com/photo.jpg",
                            "detail": "auto",
                        },
                    },
                ],
            }
        ]
        kwargs = client._build_completion_kwargs(
            model="gemini-2.0-flash",
            messages=messages,
            max_tokens=1024,
        )
        content = kwargs["messages"][0]["content"]
        image_part = next(p for p in content if p["type"] == "image_url")
        assert image_part["image_url"]["url"] == "https://example.com/photo.jpg"
        assert image_part["image_url"]["detail"] == "auto"

    def test_base64_image_url_format_preserved_for_litellm(self) -> None:
        """Base64 data-URI image_url parts must pass through unchanged."""
        client = self._make_client(catalog=self._vision_catalog())
        b64_uri = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is in this image?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": b64_uri},
                    },
                ],
            }
        ]
        kwargs = client._build_completion_kwargs(
            model="gemini-2.0-flash",
            messages=messages,
            max_tokens=1024,
        )
        content = kwargs["messages"][0]["content"]
        image_part = next(p for p in content if p["type"] == "image_url")
        assert image_part["image_url"]["url"] == b64_uri

    def test_multiple_images_preserved_for_litellm(self) -> None:
        """Multiple image_url parts in a single message are all preserved."""
        client = self._make_client(catalog=self._vision_catalog())
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Compare these images"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/a.jpg"},
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/b.jpg"},
                    },
                ],
            }
        ]
        kwargs = client._build_completion_kwargs(
            model="gemini-2.0-flash",
            messages=messages,
            max_tokens=1024,
        )
        content = kwargs["messages"][0]["content"]
        image_parts = [p for p in content if p["type"] == "image_url"]
        assert len(image_parts) == 2
        assert image_parts[0]["image_url"]["url"] == "https://example.com/a.jpg"
        assert image_parts[1]["image_url"]["url"] == "https://example.com/b.jpg"


@pytest.mark.unit
class TestVisionGatingErrorPropagation:
    """B3.3 verification: Vision gating errors are user-friendly and SSE-safe.

    The ValueError from _build_completion_kwargs propagates through
    generate_stream -> LLMStream.generate -> StreamEvent.error -> SSE event.
    These tests verify the error message quality at the source.
    """

    @staticmethod
    def _no_vision_catalog() -> MagicMock:
        catalog = MagicMock(spec=ModelCatalogService)
        catalog.supports_vision.return_value = False
        return catalog

    @staticmethod
    def _make_client(catalog: MagicMock) -> LiteLLMClient:
        config = LLMConfig(api_key="test_key")
        provider_config = ProviderConfig(
            id=uuid4(),
            name="test-openai",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted_key",
            llm_model="gpt-3.5-turbo",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        return LiteLLMClient(
            config=config,
            provider_config=provider_config,
            cache=False,
            catalog=catalog,
        )

    @staticmethod
    def _image_messages() -> list[dict[str, object]]:
        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/img.jpg"},
                    },
                ],
            }
        ]

    def test_error_message_is_user_friendly(self) -> None:
        """Error message contains model name and actionable guidance."""
        client = self._make_client(catalog=self._no_vision_catalog())
        with pytest.raises(ValueError, match="gpt-3.5-turbo") as exc_info:
            client._build_completion_kwargs(
                model="gpt-3.5-turbo",
                messages=self._image_messages(),
                max_tokens=1024,
            )
        msg = str(exc_info.value)
        assert "vision" in msg.lower()
        assert "select" in msg.lower() or "remove" in msg.lower()

    def test_error_does_not_trip_circuit_breaker(self) -> None:
        """_is_client_error recognizes the vision gating ValueError."""
        client = self._make_client(catalog=self._no_vision_catalog())
        with pytest.raises(ValueError) as exc_info:
            client._build_completion_kwargs(
                model="gpt-3.5-turbo",
                messages=self._image_messages(),
                max_tokens=1024,
            )
        assert LiteLLMClient._is_client_error(exc_info.value) is True

    def test_error_message_suitable_for_sse_event(self) -> None:
        """Error message is clean enough for SSE: no stack traces, under 200 chars."""
        client = self._make_client(catalog=self._no_vision_catalog())
        with pytest.raises(ValueError) as exc_info:
            client._build_completion_kwargs(
                model="gpt-3.5-turbo",
                messages=self._image_messages(),
                max_tokens=1024,
            )
        msg = str(exc_info.value)
        assert len(msg) < 200
        assert "Traceback" not in msg
        assert "\n" not in msg
