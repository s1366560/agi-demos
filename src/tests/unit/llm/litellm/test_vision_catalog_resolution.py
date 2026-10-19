"""Provider transport prefixes must preserve the exact model's vision contract."""

import json
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.domain.llm_providers.llm_types import LLMConfig
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient
from src.infrastructure.llm.model_catalog import ModelCatalogService

pytestmark = pytest.mark.unit


@pytest.fixture
def image_messages():
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe the test fixture."},
                {"type": "image_url", "image_url": {"url": "https://example.com/fixture.png"}},
            ],
        }
    ]


@pytest.fixture
def client():
    config = ProviderConfig(
        id=uuid4(),
        name="Configured MiniMax Coding",
        provider_type=ProviderType.MINIMAX_CODING,
        api_key_encrypted="unused-unit-test-ciphertext",
        llm_model="MiniMax-M3",
        config={},
        is_active=True,
        is_default=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    with patch.object(LiteLLMClient, "_configure_litellm"):
        return LiteLLMClient(
            config=LLMConfig(api_key="unit-test-placeholder", model="MiniMax-M3"),
            provider_config=config,
            cache=False,
            catalog=ModelCatalogService(),
        )


def test_configured_minimax_coding_m3_keeps_image_blocks_after_transport_prefix(
    client, image_messages
):
    model = client._qualify_model_for_provider(client.provider_config.llm_model)
    assert model == "minimax/MiniMax-M3"
    kwargs = client._build_completion_kwargs(model=model, messages=image_messages, max_tokens=1024)
    assert kwargs["model"] == model
    assert kwargs["messages"] == image_messages


@pytest.mark.parametrize("model", ["MiniMax-M2.5", "MiniMax-M2.7", "unknown-model"])
def test_prefixed_text_only_and_unknown_models_still_reject_images(client, image_messages, model):
    model = client._qualify_model_for_provider(model)
    with pytest.raises(ValueError, match="does not support vision/image inputs"):
        client._build_completion_kwargs(model=model, messages=image_messages, max_tokens=1024)


def test_exact_provider_entry_overrides_bare_model_vision_metadata(
    tmp_path, client, image_messages
):
    common = {"context_length": 128000, "max_output_tokens": 4096, "provider": "fixture"}
    snapshot = tmp_path / "models.json"
    snapshot.write_text(
        json.dumps(
            {
                "models": {
                    "same-model": {
                        **common,
                        "name": "same-model",
                        "capabilities": ["vision"],
                        "modalities": ["image"],
                    },
                    "provider/same-model": {
                        **common,
                        "name": "provider/same-model",
                        "capabilities": ["chat"],
                        "modalities": ["text"],
                    },
                }
            }
        )
    )
    client._catalog = ModelCatalogService(snapshot_path=snapshot)
    assert client._catalog.supports_vision("same-model")
    assert not client._catalog.supports_vision("provider/same-model")
    with pytest.raises(ValueError, match="does not support vision/image inputs"):
        client._build_completion_kwargs(
            model="provider/same-model", messages=image_messages, max_tokens=1024
        )
