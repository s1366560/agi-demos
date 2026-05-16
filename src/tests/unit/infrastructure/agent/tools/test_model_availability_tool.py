"""Unit tests for list_available_models tool."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from src.domain.llm_providers.models import ModelMetadata
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.model_availability_tool import (
    list_available_models_tool,
    switch_model_next_turn_tool,
)


@dataclass
class _FakeProviderType:
    value: str


@dataclass
class _FakeProvider:
    name: str
    provider_type: _FakeProviderType
    llm_model: str | None = None
    llm_small_model: str | None = None
    allowed_models: list[str] = field(default_factory=list)
    blocked_models: list[str] = field(default_factory=list)
    is_active: bool = True
    is_enabled: bool = True

    def is_model_allowed(self, model_id: str) -> bool:
        model_lower = model_id.lower()
        for pattern in self.blocked_models:
            if model_lower.startswith(pattern.lower()):
                return False
        if self.allowed_models:
            return any(model_lower.startswith(pattern.lower()) for pattern in self.allowed_models)
        return True


class _FakeCatalog:
    def __init__(self, models: list[ModelMetadata]) -> None:
        self._models = models
        self.last_provider: str | None = None

    def list_models(
        self,
        provider: str | None = None,
        include_deprecated: bool = False,
    ) -> list[ModelMetadata]:
        self.last_provider = provider
        items = list(self._models)
        if provider is not None:
            items = [m for m in items if (m.provider or "").lower() == provider.lower()]
        if not include_deprecated:
            items = [m for m in items if not m.is_deprecated]
        return items

    def get_model_fuzzy(self, model_name: str) -> ModelMetadata | None:
        normalized = model_name.strip().lower()
        for model in self._models:
            if model.name.lower() == normalized:
                return model
        if "/" in normalized:
            bare = normalized.split("/", 1)[1]
            for model in self._models:
                if model.name.lower() == bare:
                    return model
        return None


def _make_model(
    name: str,
    *,
    provider: str,
    deprecated: bool = False,
) -> ModelMetadata:
    return ModelMetadata(
        name=name,
        provider=provider,
        context_length=128000,
        max_output_tokens=16384,
        is_deprecated=deprecated,
    )


def _make_ctx(**overrides: Any) -> ToolContext:
    defaults: dict[str, Any] = {
        "session_id": "session-1",
        "message_id": "message-1",
        "call_id": "call-1",
        "agent_name": "react-agent",
        "conversation_id": "conv-1",
        "project_id": "project-1",
        "tenant_id": "tenant-default",
        "user_id": "user-1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


@pytest.mark.unit
class TestListAvailableModelsTool:
    async def test_returns_models_across_active_providers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        providers = [
            _FakeProvider(
                name="Default OpenAI",
                provider_type=_FakeProviderType("openai"),
                llm_model="gpt-4o",
                llm_small_model="gpt-4o-mini",
            ),
            _FakeProvider(
                name="Volcengine Ark",
                provider_type=_FakeProviderType("volcengine"),
                llm_model="doubao-1.5-pro-32k-250115",
            ),
        ]
        catalog = _FakeCatalog(
            [
                _make_model("gpt-4o", provider="openai"),
                _make_model("gpt-4o-mini", provider="openai"),
                _make_model("doubao-1.5-pro-32k-250115", provider="volcengine"),
            ]
        )

        import src.infrastructure.agent.tools.model_availability_tool as module

        async def _resolve_providers(_tenant_id: str) -> list[_FakeProvider]:
            return providers

        monkeypatch.setattr(module, "_resolve_candidate_providers", _resolve_providers)
        monkeypatch.setattr(module, "get_model_catalog_service", lambda: catalog)

        result = await list_available_models_tool.execute(_make_ctx(tenant_id="tenant-1"))
        payload = json.loads(result.output)

        assert result.is_error is False
        assert payload["provider"]["catalog_provider"] == "openai"
        assert payload["models"] == [
            "auto",
            "doubao-1.5-pro-32k-250115",
            "gpt-4o",
            "gpt-4o-mini",
        ]
        provider_types = {entry["provider_type"] for entry in payload["providers"]}
        assert provider_types == {"openai", "volcengine"}

    async def test_respects_allow_block_query_and_limit(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        provider = _FakeProvider(
            name="Restricted Provider",
            provider_type=_FakeProviderType("openai"),
            llm_model="gpt-4o",
            allowed_models=["gpt-4"],
            blocked_models=["gpt-4-legacy"],
        )
        catalog = _FakeCatalog(
            [
                _make_model("gpt-4o", provider="openai"),
                _make_model("gpt-4-legacy", provider="openai"),
                _make_model("gpt-3.5-turbo", provider="openai"),
            ]
        )

        import src.infrastructure.agent.tools.model_availability_tool as module

        async def _resolve_providers(_tenant_id: str) -> list[_FakeProvider]:
            return [provider]

        monkeypatch.setattr(module, "_resolve_candidate_providers", _resolve_providers)
        monkeypatch.setattr(module, "get_model_catalog_service", lambda: catalog)

        result = await list_available_models_tool.execute(
            _make_ctx(tenant_id="tenant-2"),
            query="gpt",
            limit=1,
        )
        payload = json.loads(result.output)

        assert result.is_error is False
        assert payload["total_available_models"] == 1
        assert payload["returned_models"] == 1
        assert payload["models"] == ["gpt-4o"]

    async def test_supports_metadata_and_provider_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = _FakeProvider(
            name="Azure OpenAI",
            provider_type=_FakeProviderType("azure_openai"),
            llm_model="openai/gpt-4o",
        )
        catalog = _FakeCatalog([_make_model("gpt-4o", provider="openai")])

        import src.infrastructure.agent.tools.model_availability_tool as module

        async def _resolve_providers(_tenant_id: str) -> list[_FakeProvider]:
            return [provider]

        monkeypatch.setattr(module, "_resolve_candidate_providers", _resolve_providers)
        monkeypatch.setattr(module, "get_model_catalog_service", lambda: catalog)

        result = await list_available_models_tool.execute(
            _make_ctx(tenant_id="tenant-3"),
            include_metadata=True,
        )
        payload = json.loads(result.output)

        assert result.is_error is False
        assert catalog.last_provider == "openai"
        assert isinstance(payload["models"], list)
        assert payload["models"][0]["name"] == "auto"
        assert payload["models"][0]["is_virtual"] is True
        assert payload["models"][1]["name"] == "gpt-4o"
        assert payload["models"][1]["provider"] == "openai"

    async def test_returns_error_when_tenant_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        catalog = _FakeCatalog([_make_model("gpt-4o", provider="openai")])

        import src.infrastructure.agent.tools.model_availability_tool as module

        monkeypatch.setattr(module, "get_model_catalog_service", lambda: catalog)

        result = await list_available_models_tool.execute(_make_ctx(tenant_id=""))
        payload = json.loads(result.output)

        assert result.is_error is True
        assert "tenant_id is required" in payload["error"]

    async def test_returns_error_when_no_active_providers(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        catalog = _FakeCatalog([])

        import src.infrastructure.agent.tools.model_availability_tool as module

        async def _resolve_providers(_tenant_id: str) -> list[_FakeProvider]:
            return []

        monkeypatch.setattr(module, "_resolve_candidate_providers", _resolve_providers)
        monkeypatch.setattr(module, "get_model_catalog_service", lambda: catalog)

        result = await list_available_models_tool.execute(_make_ctx(tenant_id="tenant-4"))
        payload = json.loads(result.output)

        assert result.is_error is True
        assert "No active LLM providers configured" in payload["error"]
        assert payload["tenant_id"] == "tenant-4"


@pytest.mark.unit
class TestSwitchModelNextTurnTool:
    async def test_emits_switch_event_for_available_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        providers = [
            _FakeProvider(
                name="Default OpenAI",
                provider_type=_FakeProviderType("openai"),
                llm_model="gpt-4o",
            ),
            _FakeProvider(
                name="Volcengine Ark",
                provider_type=_FakeProviderType("volcengine"),
                llm_model="doubao-1.5-pro-32k-250115",
            ),
        ]
        catalog = _FakeCatalog(
            [
                _make_model("gpt-4o", provider="openai"),
                _make_model("doubao-1.5-pro-32k-250115", provider="volcengine"),
            ]
        )

        import src.infrastructure.agent.tools.model_availability_tool as module

        async def _resolve_providers(_tenant_id: str) -> list[_FakeProvider]:
            return providers

        monkeypatch.setattr(module, "_resolve_candidate_providers", _resolve_providers)
        monkeypatch.setattr(module, "get_model_catalog_service", lambda: catalog)

        ctx = _make_ctx(tenant_id="tenant-1", conversation_id="conv-next-turn")
        result = await switch_model_next_turn_tool.execute(
            ctx,
            model="doubao-1.5-pro-32k-250115",
            reason="user requested",
        )
        payload = json.loads(result.output)
        pending_events = ctx.consume_pending_events()

        assert result.is_error is False
        assert payload["status"] == "scheduled"
        assert payload["model"] == "doubao-1.5-pro-32k-250115"
        assert payload["scope"] == "next_turn"
        assert len(pending_events) == 1
        assert pending_events[0]["type"] == "model_switch_requested"
        assert pending_events[0]["data"]["conversation_id"] == "conv-next-turn"
        assert pending_events[0]["data"]["model"] == "doubao-1.5-pro-32k-250115"

    async def test_returns_error_and_suggestions_when_model_unavailable(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        providers = [
            _FakeProvider(
                name="Default OpenAI",
                provider_type=_FakeProviderType("openai"),
                llm_model="gpt-4o",
            )
        ]
        catalog = _FakeCatalog([_make_model("gpt-4o", provider="openai")])

        import src.infrastructure.agent.tools.model_availability_tool as module

        async def _resolve_providers(_tenant_id: str) -> list[_FakeProvider]:
            return providers

        monkeypatch.setattr(module, "_resolve_candidate_providers", _resolve_providers)
        monkeypatch.setattr(module, "get_model_catalog_service", lambda: catalog)

        ctx = _make_ctx(tenant_id="tenant-2")
        result = await switch_model_next_turn_tool.execute(ctx, model="anthropic/claude-3-5-sonnet")
        payload = json.loads(result.output)

        assert result.is_error is True
        assert payload["status"] == "error"
        assert payload["requested_model"] == "anthropic/claude-3-5-sonnet"
        assert "suggestions" in payload
        assert ctx.consume_pending_events() == []

    async def test_returns_error_when_tenant_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        catalog = _FakeCatalog([_make_model("gpt-4o", provider="openai")])

        import src.infrastructure.agent.tools.model_availability_tool as module

        monkeypatch.setattr(module, "get_model_catalog_service", lambda: catalog)

        ctx = _make_ctx(tenant_id="")
        result = await switch_model_next_turn_tool.execute(ctx, model="gpt-4o")
        payload = json.loads(result.output)

        assert result.is_error is True
        assert payload["status"] == "error"
        assert "tenant_id is required" in payload["error"]
