"""Persisted provider routing settings must survive public response projection."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.application.services.provider_service import ProviderService
from src.domain.llm_providers.models import (
    ProviderConfigCreate,
    ProviderType,
)
from src.infrastructure.adapters.primary.web.routers.llm_providers import (
    get_current_user_with_roles,
    get_provider_service_with_session,
    router,
)
from src.infrastructure.persistence.llm_providers_repository import SQLAlchemyProviderRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def provider_app(db_session, monkeypatch):
    repository = SQLAlchemyProviderRepository(session=db_session)
    service = ProviderService(repository)
    service.resolution_service = MagicMock()
    monkeypatch.setattr(service, "_sync_health_checker_provider_type", AsyncMock())
    monkeypatch.setattr(service, "_get_resilience_status", lambda _provider: None)
    monkeypatch.setattr(service, "_invalidate_model_pool_cache", lambda: None)
    app = FastAPI()
    app.include_router(router)
    admin = SimpleNamespace(
        id="fixture-admin", roles=[SimpleNamespace(role=SimpleNamespace(name="admin"))]
    )
    app.dependency_overrides[get_current_user_with_roles] = lambda: admin
    app.dependency_overrides[get_provider_service_with_session] = lambda: service
    return app


async def test_create_read_and_update_preserve_disabled_pool_and_other_provider_fields(
    provider_app,
):
    config = ProviderConfigCreate(
        name="ark-response-pool-disabled",
        provider_type=ProviderType.VOLCENGINE,
        api_key="fixture-local-unused",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_model="ep-exact-audio",
        secondary_models=["ep-exact-secondary"],
        pool_enabled=False,
        pool_weight=2.25,
        model_tier="small",
        allowed_models=["ep-exact-audio", "ep-exact-secondary"],
        config={"temperature": 0.4, "audio_input_models": ["ep-exact-audio"]},
    )
    async with AsyncClient(
        transport=ASGITransport(app=provider_app), base_url="http://fixture"
    ) as client:
        created = await client.post("/api/v1/llm-providers/", json=config.model_dump(mode="json"))
        assert created.status_code == 201
        path = "/api/v1/llm-providers/" + created.json()["id"]
        response = await client.get(path)
        assert response.status_code == 200
        before = response.json()
        assert before["pool_enabled"] is False
        assert before["pool_weight"] == 2.25
        assert before["model_tier"] == "small"
        assert before["secondary_models"] == ["ep-exact-secondary"]
        changed = await client.put(
            path,
            json={
                "name": "ark-response-renamed",
                "model_tier": "medium",
                "expected_revision": before["revision"],
            },
        )
        assert changed.status_code == 200
        response = await client.get(path)
        assert response.status_code == 200
        updated = response.json()
        assert updated["name"] == "ark-response-renamed"
        assert updated["pool_enabled"] is False
        assert updated["pool_weight"] == 2.25
        assert updated["model_tier"] == "medium"
        assert updated["secondary_models"] == before["secondary_models"]
        assert updated["config"] == before["config"] == config.config
        assert updated["allowed_models"] == before["allowed_models"] == config.allowed_models
        assert updated["base_url"] == before["base_url"] == config.base_url
        assert updated["llm_model"] == before["llm_model"] == config.llm_model
        assert updated["is_active"] is True
        assert updated["is_enabled"] is True
        assert updated["is_default"] is False


async def test_small_model_omission_preserves_and_explicit_null_clears_audio_roster(provider_app):
    config = {
        "name": "ark-small-model-null",
        "provider_type": "volcengine",
        "api_key": "fixture-local-unused",
        "llm_model": "ep-exact-audio",
        "llm_small_model": "ep-small-audio",
        "config": {
            "temperature": 0.4,
            "audio_input_models": ["ep-exact-audio", "ep-small-audio"],
        },
    }
    async with AsyncClient(
        transport=ASGITransport(app=provider_app), base_url="http://fixture"
    ) as client:
        created = await client.post("/api/v1/llm-providers/", json=config)
        assert created.status_code == 201
        path = "/api/v1/llm-providers/" + created.json()["id"]
        omitted = await client.put(
            path,
            json={"name": "ark-small-omitted", "expected_revision": created.json()["revision"]},
        )
        assert omitted.status_code == 200
        response = await client.get(path)
        assert response.status_code == 200
        retained = response.json()
        assert retained["llm_small_model"] == "ep-small-audio"
        assert retained["config"] == config["config"]

        cleared_config = {"temperature": 0.4, "audio_input_models": ["ep-exact-audio"]}
        cleared = await client.put(
            path,
            json={
                "expected_revision": retained["revision"],
                "llm_small_model": None,
                "config": cleared_config,
            },
        )
        assert cleared.status_code == 200
        response = await client.get(path)
        assert response.status_code == 200
        stored = response.json()
        assert stored["llm_small_model"] is None
        assert stored["config"] == cleared_config
        omitted_again = await client.put(
            path, json={"pool_weight": 0.5, "expected_revision": stored["revision"]}
        )
        assert omitted_again.status_code == 200
        response = await client.get(path)
        assert response.status_code == 200
        assert response.json()["llm_small_model"] is None
        assert response.json()["llm_model"] == "ep-exact-audio"
        assert response.json()["config"] == cleared_config
