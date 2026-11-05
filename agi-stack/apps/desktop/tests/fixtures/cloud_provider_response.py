"""Emit the real cloud response projection for the desktop contract integration test."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from src.application.services.provider_service import ProviderService
from src.domain.llm_providers.audio_input import validate_audio_input_declaration
from src.domain.llm_providers.models import ProviderConfig


async def main() -> None:
    now = datetime(2026, 10, 29, tzinfo=UTC)
    provider = ProviderConfig(
        id=UUID("00000000-0000-4000-8000-000000000123"),
        name="Ark contract fixture",
        provider_type="volcengine",
        api_key_encrypted="",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_model="ep-primary",
        llm_small_model="ep-fast",
        secondary_models=["ep-secondary"],
        allowed_models=["ep-"],
        config={
            "temperature": 0.25,
            "retries": {"max_attempts": 2},
            "audio_input_models": ["ep-fast", "ep-secondary"],
        },
        created_at=now,
        updated_at=now,
    )
    configured = [provider.llm_model, provider.llm_small_model, *provider.secondary_models]
    validate_audio_input_declaration(provider.provider_type.value, provider.config, configured)
    rejected = []
    for model in ["ep-", "ep-not-configured"]:
        try:
            validate_audio_input_declaration(
                provider.provider_type.value, {"audio_input_models": [model]}, configured
            )
        except ValueError:
            rejected.append(model)
    service = object.__new__(ProviderService)
    service.repository = SimpleNamespace(get_latest_health=AsyncMock(return_value=None))
    service._credential_is_configured = lambda _value: False
    service._mask_api_key = lambda _value: ""
    service._get_resilience_status = lambda _provider: None
    response = await service._provider_to_response(provider)
    print(json.dumps({"response": response.model_dump(mode="json"), "rejected": rejected}))


if __name__ == "__main__":
    asyncio.run(main())
