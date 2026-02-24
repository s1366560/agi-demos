"""
Unit tests for LiteLLM Client adapter.

Tests the LiteLLMClient implementation of the LLMClient interface.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel

from src.domain.llm_providers.llm_types import LLMConfig, Message, ModelSize, RateLimitError
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient
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
        """Should use explicit Qwen input limits when defined."""
        assert get_model_max_input_tokens("qwen-max", max_output_tokens=8192) == 30720
        assert get_model_max_input_tokens("dashscope/qwen-max", max_output_tokens=8192) == 30720

    def test_get_model_input_budget_qwen_specific(self):
        """Should apply conservative default budget ratio for Qwen models."""
        assert get_model_input_budget("qwen-max", max_output_tokens=8192) == 26112

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
