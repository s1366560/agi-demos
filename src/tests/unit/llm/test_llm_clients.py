from unittest.mock import Mock, patch

import pytest

from src.domain.llm_providers.llm_types import LLMConfig
from src.infrastructure.llm.qwen.qwen_client import QwenClient

# TODO: QwenClient now uses DashScope SDK instead of AsyncOpenAI - tests need complete rewrite
pytestmark = pytest.mark.unit


@pytest.fixture
def mock_dashscope_generation():
    with patch("src.infrastructure.llm.qwen.qwen_client.Generation") as mock:
        mock.call = Mock()
        yield mock


@pytest.fixture
def qwen_client():
    config = LLMConfig(api_key="test-key")
    return QwenClient(config=config)


def test_init():
    config = LLMConfig(api_key="test-key")
    client = QwenClient(config=config)
    assert client.model == "qwen-plus"
    assert client.small_model == "qwen-turbo"
