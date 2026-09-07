"""Provider/Consumer coverage for generation-owned channel adapters."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.domain.model.channels.message import ChannelConfig
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.channel_adapters import (
    CHANNEL_ADAPTER_CATALOG_MODULE_V2,
    CHANNEL_ADAPTER_RESOLVER_SERVICE_V2,
    CHANNEL_RUNTIME_RELOAD_EVENT_V2,
    FEISHU_CHANNEL_ADAPTER_MODULE_V2,
    ChannelAdapterBuildContextV2,
    ChannelAdapterCatalogV2,
    ChannelAdapterContributionV2,
    ChannelAdapterMetadataV2,
    ChannelAdapterResolverV2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _Adapter:
    def __init__(self, config: ChannelConfig) -> None:
        self.config = config


def _contribution(
    *,
    channel_type: str = "test",
    source_id: str = "test-adapter",
) -> ChannelAdapterContributionV2:
    return ChannelAdapterContributionV2(
        source_id=source_id,
        metadata=ChannelAdapterMetadataV2(
            channel_type=channel_type,
            config_schema={"type": "object"},
            config_ui_hints={},
            defaults={},
            secret_paths=("app_secret",),
        ),
        factory=lambda context: _Adapter(context.channel_config),
    )


def _build_context(channel_type: str = "test") -> ChannelAdapterBuildContextV2:
    return ChannelAdapterBuildContextV2(
        channel_type=channel_type,
        config_model=object(),
        channel_config=ChannelConfig(app_id="app", app_secret="secret"),
    )


@pytest.mark.unit
async def test_channel_adapter_catalog_builds_registered_contribution() -> None:
    catalog = ChannelAdapterCatalogV2()
    _ = catalog.register_channel(_contribution())
    resolver = ChannelAdapterResolverV2(strategy="explicit-contributions", catalog=catalog)

    adapter = await resolver.build(_build_context())

    assert isinstance(adapter, _Adapter)
    assert adapter.config.app_id == "app"
    metadata = resolver.metadata("TEST")
    assert metadata is not None
    assert metadata.source_id == "test-adapter"
    assert tuple(resolver.list_metadata()) == ("test",)


@pytest.mark.unit
async def test_channel_adapter_contribution_disposer_removes_exact_source() -> None:
    catalog = ChannelAdapterCatalogV2()
    dispose = catalog.register_channel(_contribution())

    await dispose()

    with pytest.raises(RuntimeV2Error) as error:
        await catalog.build(_build_context())
    assert error.value.code == "channel_adapter_not_found"


@pytest.mark.unit
def test_channel_adapter_catalog_rejects_duplicate_channel_type() -> None:
    catalog = ChannelAdapterCatalogV2()
    _ = catalog.register_channel(_contribution(source_id="source-a"))

    with pytest.raises(RuntimeV2Error) as error:
        _ = catalog.register_channel(_contribution(source_id="source-b"))

    assert error.value.code == "channel_adapter_conflict"


@pytest.mark.unit
def test_channel_adapter_catalog_rejects_duplicate_source() -> None:
    catalog = ChannelAdapterCatalogV2()
    _ = catalog.register_channel(_contribution(channel_type="alpha", source_id="source-a"))

    with pytest.raises(RuntimeV2Error) as error:
        _ = catalog.register_channel(_contribution(channel_type="beta", source_id="source-a"))

    assert error.value.code == "channel_adapter_source_conflict"


@pytest.mark.unit
async def test_feishu_adapter_is_resolved_from_pinned_generation() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )
    try:
        generation = host.manager.current
        assert generation is not None
        resolver = generation.resolve(
            CHANNEL_ADAPTER_RESOLVER_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
        assert isinstance(resolver, ChannelAdapterResolverV2)
        metadata = resolver.metadata("feishu")
        assert metadata is not None
        assert metadata.secret_paths == ("app_secret", "encrypt_key", "verification_token")
        assert metadata.defaults["connection_mode"] == "websocket"

        with patch(
            "src.infrastructure.adapters.secondary.channels.channel_plugin_loader.load_channel_module",
            return_value=SimpleNamespace(FeishuAdapter=_Adapter),
        ):
            adapter = await resolver.build(_build_context("feishu"))

        assert isinstance(adapter, _Adapter)
    finally:
        await host.close()


@pytest.mark.unit
async def test_channel_reload_event_contract_rejects_invalid_payload() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )
    assert publication.accepted is True
    try:
        async with pin_operation_context_v2(
            host,
            operation_id="channel-reload:test",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ) as operation:
            payload = {
                "dry_run": False,
                "generation_digest": operation.generation.digest,
                "operation_id": operation.operation_id,
                "plan": {"add": 1, "remove": 0, "restart": 0, "unchanged": 2},
            }
            assert await operation.dispatch(CHANNEL_RUNTIME_RELOAD_EVENT_V2, payload) == ()

            with pytest.raises(RuntimeV2Error) as error:
                await operation.dispatch(
                    CHANNEL_RUNTIME_RELOAD_EVENT_V2,
                    {**payload, "plan": {"add": -1}},
                )
    finally:
        await host.close()

    assert error.value.code == "invalid_event_payload"


@pytest.mark.unit
def test_channel_adapter_modules_are_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    modules = {entry.module_ref for entry in document.entries if entry.enabled}

    assert CHANNEL_ADAPTER_CATALOG_MODULE_V2 in modules
    assert FEISHU_CHANNEL_ADAPTER_MODULE_V2 in modules


@pytest.mark.unit
async def test_disabling_feishu_contribution_removes_adapter_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == FEISHU_CHANNEL_ADAPTER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=2,
    )
    generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)
    resolver = generation.resolve(
        CHANNEL_ADAPTER_RESOLVER_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    assert isinstance(resolver, ChannelAdapterResolverV2)

    try:
        with pytest.raises(RuntimeV2Error) as error:
            await resolver.build(_build_context("feishu"))
    finally:
        await generation.dispose()

    assert error.value.code == "channel_adapter_not_found"
