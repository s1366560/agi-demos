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
            # Check that the model has the openai prefix (ZAI uses OpenAI-compatible API)
            call_kwargs = mock_acompletion.call_args.kwargs
            assert "openai/" in call_kwargs["model"]

    @pytest.mark.asyncio
    async def test_zhipu_get_model_for_size_small(self, zhipu_client):
        """Test model selection for small size with ZhipuAI."""
        model = zhipu_client._get_model_for_size(ModelSize.small)
        # ZAI uses OpenAI-compatible API, so model has openai/ prefix
        assert model == "openai/glm-4-flash"

    @pytest.mark.asyncio
    async def test_zhipu_get_model_for_size_medium(self, zhipu_client):
        """Test model selection for medium size with ZhipuAI."""
        model = zhipu_client._get_model_for_size(ModelSize.medium)
        # ZAI uses OpenAI-compatible API, so model has openai/ prefix
        assert model == "openai/glm-4-plus"

    @pytest.mark.asyncio
    async def test_zhipu_get_provider_type(self, zhipu_client):
        """Test provider type identification for ZhipuAI."""
        provider_type = zhipu_client._get_provider_type()
        assert provider_type == "litellm-zai"
