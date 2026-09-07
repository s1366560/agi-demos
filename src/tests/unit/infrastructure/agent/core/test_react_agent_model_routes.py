"""Explicit provider/model identity tests for the v2 agent spine."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.agent.core.react_agent_stream_mixin import (
    _bind_processor_model_route,
    _resolve_exact_provider_config_for_route,
    _resolve_model_route_override,
)
from src.infrastructure.agent.model_route import ModelRouteRef
from src.infrastructure.agent.processor.factory import ProcessorFactory
from src.infrastructure.agent.processor.processor import ProcessorConfig
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error


@pytest.mark.unit
class TestResolveModelRouteOverride:
    def test_bare_model_override_fails_closed(self) -> None:
        with pytest.raises(RuntimeV2Error) as exc_info:
            _resolve_model_route_override(
                model_override="gpt-4.1-mini",
                model_route_override=None,
            )

        assert exc_info.value.code == "model_override_route_missing"

    def test_structured_route_can_be_the_only_override_authority(self) -> None:
        route = ModelRouteRef(provider_id="openai", model_id="gpt-4.1-mini")

        assert (
            _resolve_model_route_override(
                model_override=None,
                model_route_override=route,
            )
            is route
        )

    def test_bare_model_and_route_must_match_exactly(self) -> None:
        with pytest.raises(RuntimeV2Error) as exc_info:
            _resolve_model_route_override(
                model_override="gpt-4.1-mini",
                model_route_override=ModelRouteRef(
                    provider_id="openai",
                    model_id="gpt-4o-mini",
                ),
            )

        assert exc_info.value.code == "model_override_route_mismatch"


@pytest.mark.unit
class TestExactProviderConfigResolution:
    @staticmethod
    def _provider(provider_id: str, *, name: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=name,
            name=name,
            provider_type=SimpleNamespace(value=provider_id),
            operation_type=SimpleNamespace(value="llm"),
            is_active=True,
            is_enabled=True,
            base_url=f"https://{name}.example.test",
            is_model_allowed=lambda _model: True,
        )

    async def test_resolves_only_an_exact_provider_identity_without_catalog_lookup(self) -> None:
        provider = self._provider("openai", name="openai-primary")
        repository = SimpleNamespace(
            find_tenant_provider=AsyncMock(return_value=None),
            find_default_provider=AsyncMock(return_value=None),
            list_active=AsyncMock(return_value=[provider]),
        )
        route = ModelRouteRef(provider_id="openai", model_id="gpt-4.1-mini")

        with (
            patch(
                "src.application.services.provider_resolution_service."
                "get_provider_resolution_service",
                return_value=SimpleNamespace(repository=repository),
            ),
            patch(
                "src.infrastructure.llm.model_catalog.get_model_catalog_service",
                side_effect=AssertionError("catalog inference must not run"),
            ),
        ):
            resolved = await _resolve_exact_provider_config_for_route(
                tenant_id="tenant-1",
                route=route,
            )

        assert resolved is provider

    async def test_rejects_ambiguous_exact_provider_identity(self) -> None:
        repository = SimpleNamespace(
            find_tenant_provider=AsyncMock(return_value=None),
            find_default_provider=AsyncMock(return_value=None),
            list_active=AsyncMock(
                return_value=[
                    self._provider("openai", name="openai-a"),
                    self._provider("openai", name="openai-b"),
                ]
            ),
        )

        with (
            patch(
                "src.application.services.provider_resolution_service."
                "get_provider_resolution_service",
                return_value=SimpleNamespace(repository=repository),
            ),
            pytest.raises(RuntimeV2Error) as exc_info,
        ):
            await _resolve_exact_provider_config_for_route(
                tenant_id="tenant-1",
                route=ModelRouteRef(
                    provider_id="openai",
                    model_id="gpt-4.1-mini",
                ),
            )

        assert exc_info.value.code == "model_route_provider_ambiguous"


@pytest.mark.unit
class TestBindProcessorModelRoute:
    async def test_same_provider_route_sets_exact_loop_resolver_identity(self) -> None:
        config = ProcessorConfig(
            model="gpt-4o",
            provider_id="openai",
            llm_client=MagicMock(),
        )
        route = ModelRouteRef(provider_id="openai", model_id="gpt-4.1-mini")

        with patch(
            "src.infrastructure.llm.model_catalog.get_model_catalog_service",
            side_effect=AssertionError("catalog inference must not run"),
        ):
            await _bind_processor_model_route(
                config=config,
                route=route,
                tenant_id="tenant-1",
            )

        assert config.provider_id == "openai"
        assert config.model == "gpt-4.1-mini"

        loop_resolver = MagicMock()
        loop_resolver.resolve.return_value = SimpleNamespace(
            scope="test",
            loop_id="test-loop",
            plugin_id="test-plugin",
        )
        with patch(
            "src.infrastructure.agent.processor.factory._default_loop_resolver",
            return_value=loop_resolver,
        ):
            processor = ProcessorFactory().create_for_main(config, [])

        processor._resolve_agent_loop()
        loop_resolver.resolve.assert_called_once_with("openai", "gpt-4.1-mini")

    async def test_cross_provider_route_rebinds_from_exact_provider_config(self) -> None:
        old_client = MagicMock()
        new_client = MagicMock()
        config = ProcessorConfig(
            model="gpt-4o",
            provider_id="openai",
            llm_client=old_client,
        )
        route = ModelRouteRef(provider_id="anthropic", model_id="claude-3-7-sonnet")
        provider_config = SimpleNamespace(base_url="https://anthropic.example.test")
        service_factory = SimpleNamespace(create_llm_client=MagicMock(return_value=new_client))

        with (
            patch(
                "src.infrastructure.agent.core.react_agent_stream_mixin."
                "_resolve_exact_provider_config_for_route",
                new=AsyncMock(return_value=provider_config),
            ) as resolver,
            patch(
                "src.infrastructure.llm.provider_factory.get_ai_service_factory",
                return_value=service_factory,
            ),
            patch(
                "src.infrastructure.llm.model_catalog.get_model_catalog_service",
                side_effect=AssertionError("catalog inference must not run"),
            ),
        ):
            await _bind_processor_model_route(
                config=config,
                route=route,
                tenant_id="tenant-1",
            )

        resolver.assert_awaited_once_with(tenant_id="tenant-1", route=route)
        service_factory.create_llm_client.assert_called_once_with(provider_config)
        assert config.provider_id == "anthropic"
        assert config.model == "claude-3-7-sonnet"
        assert config.base_url == "https://anthropic.example.test"
        assert config.llm_client is new_client
