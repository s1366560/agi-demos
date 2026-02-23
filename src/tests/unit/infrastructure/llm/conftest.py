"""Shared fixtures for LLM provider tests."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.domain.llm_providers.llm_types import LLMClient
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.tests.unit.infrastructure.llm.test_helper import _generate_response_noop

# Ensure the patch is applied
LLMClient._generate_response = _generate_response_noop
LLMClient.__abstractmethods__ = set()

# Patch encryption service at module level (before tests run)
import src.infrastructure.security.encryption_service as enc_service_module

_original_get_encryption_service = enc_service_module.get_encryption_service
_mock_enc_service = MagicMock()
_mock_enc_service.encrypt = MagicMock(side_effect=lambda x: f"encrypted_{x}" if x else x)
_mock_enc_service.decrypt = MagicMock(side_effect=lambda x: x.replace("encrypted_", "") if x else x)
# NOTE: Do NOT patch at module level - it leaks to other test directories


@pytest.fixture(autouse=True)
def auto_mock_encryption_service():
    """Automatically mock encryption service for all tests in this directory."""
    # Ensure the mock is active for this directory's tests
    enc_service_module.get_encryption_service = lambda: _mock_enc_service
    yield _mock_enc_service
    # Restore original so tests outside this directory get real encryption
    enc_service_module.get_encryption_service = _original_get_encryption_service


@pytest.fixture
def provider_config():
    """Create a test ProviderConfig."""
    now = datetime.now(timezone.utc)
    return ProviderConfig(
        id=uuid4(),
        name="Test Provider",
        provider_type=ProviderType.OPENAI,
        is_active=True,
        is_default=True,
        llm_model="test-model",
        llm_small_model="test-small-model",
        embedding_model="test-embedding",
        api_key_encrypted="encrypted_test-key",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def openai_provider_config():
    """Create a test ProviderConfig for OpenAI."""
    now = datetime.now(timezone.utc)
    return ProviderConfig(
        id=uuid4(),
        name="OpenAI Test",
        provider_type=ProviderType.OPENAI,
        is_active=True,
        is_default=True,
        llm_model="gpt-4o",
        llm_small_model="gpt-4o-mini",
        embedding_model="text-embedding-3-small",
        api_key_encrypted="encrypted_sk-test-key",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def gemini_provider_config():
    """Create a test ProviderConfig for Gemini."""
    now = datetime.now(timezone.utc)
    return ProviderConfig(
        id=uuid4(),
        name="Gemini Test",
        provider_type=ProviderType.GEMINI,
        is_active=True,
        is_default=True,
        llm_model="gemini-2.5-flash",
        llm_small_model="gemini-2.0-flash-lite",
        embedding_model="text-embedding-004",
        api_key_encrypted="encrypted_test-key",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def deepseek_provider_config():
    """Create a test ProviderConfig for Deepseek."""
    now = datetime.now(timezone.utc)
    return ProviderConfig(
        id=uuid4(),
        name="Deepseek Test",
        provider_type=ProviderType.DEEPSEEK,
        is_active=True,
        is_default=True,
        llm_model="deepseek-chat",
        llm_small_model="deepseek-coder",
        embedding_model="text-embedding-v3",
        api_key_encrypted="encrypted_sk-test-key",
        base_url="https://api.deepseek.com/v1",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def zai_provider_config():
    """Create a test ProviderConfig for Z.AI."""
    now = datetime.now(timezone.utc)
    return ProviderConfig(
        id=uuid4(),
        name="Z.AI Test",
        provider_type=ProviderType.ZAI,
        is_active=True,
        is_default=True,
        llm_model="glm-4-plus",
        llm_small_model="glm-4-flash",
        embedding_model="embedding-3",
        api_key_encrypted="encrypted_test-key",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        created_at=now,
        updated_at=now,
    )
