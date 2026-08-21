"""Generation-owned channel adapter catalog and builtin contributions."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from src.domain.model.channels.message import ChannelConfig

from .runtime import ContextV2, PluginDefinitionV2, RuntimeV2Error, generated_contract_digest_v2

CHANNEL_ADAPTER_CATALOG_MODULE_V2 = "builtin://memstack/channel/adapter-catalog"
FEISHU_CHANNEL_ADAPTER_MODULE_V2 = "builtin://memstack/channel/feishu-adapter"
CHANNEL_ADAPTER_CATALOG_SERVICE_V2 = "service:channel-adapter-catalog"
CHANNEL_ADAPTER_RESOLVER_SERVICE_V2 = "service:channel-adapter-resolver"

type ChannelAdapterDisposerV2 = Callable[[], None | Awaitable[None]]
type ChannelAdapterFactoryV2 = Callable[
    ["ChannelAdapterBuildContextV2"],
    object | Awaitable[object],
]


def _is_mapping(value: object) -> bool:
    return isinstance(value, Mapping)


@dataclass(frozen=True, kw_only=True)
class ChannelAdapterBuildContextV2:
    """Inputs passed to one generation-owned channel adapter factory."""

    channel_type: str
    config_model: object
    channel_config: ChannelConfig


@dataclass(frozen=True, kw_only=True)
class ChannelAdapterMetadataV2:
    """Immutable public metadata contributed for one channel type."""

    channel_type: str
    config_schema: Mapping[str, object]
    config_ui_hints: Mapping[str, object]
    defaults: Mapping[str, object]
    secret_paths: tuple[str, ...]
    source_id: str = ""


@dataclass(frozen=True, kw_only=True)
class ChannelAdapterContributionV2:
    """One explicit Profile contribution to the channel adapter catalog."""

    source_id: str
    metadata: ChannelAdapterMetadataV2
    factory: ChannelAdapterFactoryV2


@runtime_checkable
class ChannelAdapterCatalogProtocolV2(Protocol):
    """Mutable catalog owned by exactly one staged generation."""

    def register_channel(
        self,
        contribution: ChannelAdapterContributionV2,
    ) -> ChannelAdapterDisposerV2: ...

    def metadata(self, channel_type: str) -> ChannelAdapterMetadataV2 | None: ...

    def list_metadata(self) -> Mapping[str, ChannelAdapterMetadataV2]: ...

    async def build(self, context: ChannelAdapterBuildContextV2) -> object: ...


class ChannelAdapterCatalogV2:
    """Resolve adapters only from contributions active in one generation."""

    def __init__(self) -> None:
        super().__init__()
        self._contributions_by_source: dict[str, ChannelAdapterContributionV2] = {}
        self._source_by_channel_type: dict[str, str] = {}

    def register_channel(
        self,
        contribution: ChannelAdapterContributionV2,
    ) -> ChannelAdapterDisposerV2:
        normalized = self._normalize_contribution(contribution)
        source_id = normalized.source_id
        channel_type = normalized.metadata.channel_type
        if source_id in self._contributions_by_source:
            raise RuntimeV2Error(
                "channel_adapter_source_conflict",
                f"channel adapter source {source_id} is already registered",
            )
        previous_source = self._source_by_channel_type.get(channel_type)
        if previous_source is not None:
            raise RuntimeV2Error(
                "channel_adapter_conflict",
                f"channel type {channel_type} duplicate sources: {previous_source}, {source_id}",
            )
        self._contributions_by_source[source_id] = normalized
        self._source_by_channel_type[channel_type] = source_id

        async def dispose() -> None:
            if self._contributions_by_source.get(source_id) is normalized:
                _ = self._contributions_by_source.pop(source_id, None)
                if self._source_by_channel_type.get(channel_type) == source_id:
                    _ = self._source_by_channel_type.pop(channel_type, None)

        return dispose

    def metadata(self, channel_type: str) -> ChannelAdapterMetadataV2 | None:
        normalized = channel_type.strip().casefold()
        source_id = self._source_by_channel_type.get(normalized)
        if source_id is None:
            return None
        return self._contributions_by_source[source_id].metadata

    def list_metadata(self) -> Mapping[str, ChannelAdapterMetadataV2]:
        return MappingProxyType(
            {
                channel_type: self._contributions_by_source[source_id].metadata
                for channel_type, source_id in self._source_by_channel_type.items()
            }
        )

    async def build(self, context: ChannelAdapterBuildContextV2) -> object:
        normalized = context.channel_type.strip().casefold()
        source_id = self._source_by_channel_type.get(normalized)
        if source_id is None:
            raise RuntimeV2Error(
                "channel_adapter_not_found",
                f"channel type {normalized or '<empty>'} has no active contribution",
            )
        contribution = self._contributions_by_source[source_id]
        result = contribution.factory(context)
        if inspect.isawaitable(result):
            result = await result
        if result is None:
            raise RuntimeV2Error(
                "invalid_channel_adapter",
                f"channel adapter source {source_id} returned no adapter",
            )
        return result

    @staticmethod
    def _normalize_contribution(
        contribution: ChannelAdapterContributionV2,
    ) -> ChannelAdapterContributionV2:
        source_id = contribution.source_id.strip()
        channel_type = contribution.metadata.channel_type.strip().casefold()
        if not source_id or not channel_type or not callable(contribution.factory):
            raise RuntimeV2Error(
                "invalid_channel_adapter_contribution",
                "channel adapter contribution requires source_id, channel_type, and factory",
            )
        metadata = contribution.metadata
        metadata_mappings: tuple[object, ...] = (
            metadata.config_schema,
            metadata.config_ui_hints,
            metadata.defaults,
        )
        if not all(_is_mapping(value) for value in metadata_mappings):
            raise RuntimeV2Error(
                "invalid_channel_adapter_contribution",
                f"channel adapter source {source_id} has invalid metadata mappings",
            )
        secret_paths = tuple(path.strip() for path in metadata.secret_paths)
        if any(not path for path in secret_paths) or len(secret_paths) != len(set(secret_paths)):
            raise RuntimeV2Error(
                "invalid_channel_adapter_contribution",
                f"channel adapter source {source_id} has invalid secret paths",
            )
        return ChannelAdapterContributionV2(
            source_id=source_id,
            metadata=ChannelAdapterMetadataV2(
                channel_type=channel_type,
                config_schema=MappingProxyType(dict(metadata.config_schema)),
                config_ui_hints=MappingProxyType(dict(metadata.config_ui_hints)),
                defaults=MappingProxyType(dict(metadata.defaults)),
                secret_paths=secret_paths,
                source_id=source_id,
            ),
            factory=contribution.factory,
        )


@runtime_checkable
class ChannelAdapterResolverProtocolV2(Protocol):
    """Structural contract consumed by generation-pinned channel boundaries."""

    def metadata(self, channel_type: str) -> ChannelAdapterMetadataV2 | None: ...

    def list_metadata(self) -> Mapping[str, ChannelAdapterMetadataV2]: ...

    async def build(self, context: ChannelAdapterBuildContextV2) -> object: ...


@dataclass(frozen=True, kw_only=True)
class ChannelAdapterResolverV2:
    """Read-only facade over one generation's channel contribution catalog."""

    strategy: str
    catalog: ChannelAdapterCatalogProtocolV2

    def metadata(self, channel_type: str) -> ChannelAdapterMetadataV2 | None:
        return self.catalog.metadata(channel_type)

    def list_metadata(self) -> Mapping[str, ChannelAdapterMetadataV2]:
        return self.catalog.list_metadata()

    async def build(self, context: ChannelAdapterBuildContextV2) -> object:
        return await self.catalog.build(context)


def _apply_channel_adapter_catalog_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "explicit-contributions":
        raise ValueError("channel adapter catalog requires strategy explicit-contributions")
    catalog = ChannelAdapterCatalogV2()
    _ = context.provide(
        CHANNEL_ADAPTER_CATALOG_SERVICE_V2,
        catalog,
        label="channel-adapter-catalog",
    )
    _ = context.provide(
        CHANNEL_ADAPTER_RESOLVER_SERVICE_V2,
        ChannelAdapterResolverV2(strategy=strategy, catalog=catalog),
        label="channel-adapter-resolver",
    )


def _build_feishu_adapter_v2(context: ChannelAdapterBuildContextV2) -> object:
    from src.infrastructure.adapters.secondary.channels.channel_plugin_loader import (
        load_channel_module,
    )

    adapter_module = load_channel_module("feishu", "adapter")
    adapter_type = getattr(adapter_module, "FeishuAdapter", None)
    if not callable(adapter_type):
        raise RuntimeV2Error(
            "invalid_channel_adapter",
            "Feishu contribution did not load a callable adapter",
        )
    return adapter_type(context.channel_config)


def _feishu_contribution_v2(source_id: str) -> ChannelAdapterContributionV2:
    return ChannelAdapterContributionV2(
        source_id=source_id,
        metadata=ChannelAdapterMetadataV2(
            channel_type="feishu",
            config_schema={
                "type": "object",
                "properties": {
                    "app_id": {"type": "string", "title": "App ID", "minLength": 1},
                    "app_secret": {
                        "type": "string",
                        "title": "App Secret",
                        "minLength": 1,
                    },
                    "encrypt_key": {"type": "string", "title": "Encrypt Key"},
                    "verification_token": {
                        "type": "string",
                        "title": "Verification Token",
                    },
                    "domain": {"type": "string", "title": "Domain", "default": "feishu"},
                    "connection_mode": {
                        "type": "string",
                        "title": "Connection Mode",
                        "enum": ["websocket", "webhook"],
                        "default": "websocket",
                    },
                    "webhook_url": {"type": "string", "title": "Webhook URL"},
                    "webhook_port": {
                        "type": "integer",
                        "title": "Webhook Port",
                        "minimum": 1,
                        "maximum": 65535,
                    },
                    "webhook_path": {"type": "string", "title": "Webhook Path"},
                },
                "required": ["app_id", "app_secret"],
                "additionalProperties": False,
            },
            config_ui_hints={
                "app_secret": {"sensitive": True},
                "encrypt_key": {"sensitive": True, "advanced": True},
                "verification_token": {"sensitive": True, "advanced": True},
                "webhook_port": {"advanced": True},
                "webhook_path": {"advanced": True},
            },
            defaults={
                "domain": "feishu",
                "connection_mode": "websocket",
                "webhook_path": "/api/v1/channels/events/feishu",
                "webhook_port": 8000,
            },
            secret_paths=("app_secret", "encrypt_key", "verification_token"),
        ),
        factory=_build_feishu_adapter_v2,
    )


def _apply_feishu_channel_adapter_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> ChannelAdapterDisposerV2:
    if config.get("channel_type") != "feishu":
        raise ValueError("Feishu channel contribution requires channel_type feishu")
    source_id = config.get("source_id")
    if source_id != "builtin-feishu":
        raise ValueError("Feishu channel contribution requires source_id builtin-feishu")
    catalog = context.require("catalog")
    if not isinstance(catalog, ChannelAdapterCatalogProtocolV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "channel adapter catalog service has an invalid implementation",
        )
    return catalog.register_channel(_feishu_contribution_v2(source_id))


def builtin_channel_adapter_catalog_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=CHANNEL_ADAPTER_CATALOG_MODULE_V2,
        contract_digest=generated_contract_digest_v2(CHANNEL_ADAPTER_CATALOG_MODULE_V2),
        apply=_apply_channel_adapter_catalog_v2,
    )


def builtin_feishu_channel_adapter_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=FEISHU_CHANNEL_ADAPTER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(FEISHU_CHANNEL_ADAPTER_MODULE_V2),
        apply=_apply_feishu_channel_adapter_v2,
    )


__all__ = [
    "CHANNEL_ADAPTER_CATALOG_MODULE_V2",
    "CHANNEL_ADAPTER_CATALOG_SERVICE_V2",
    "CHANNEL_ADAPTER_RESOLVER_SERVICE_V2",
    "FEISHU_CHANNEL_ADAPTER_MODULE_V2",
    "ChannelAdapterBuildContextV2",
    "ChannelAdapterCatalogProtocolV2",
    "ChannelAdapterCatalogV2",
    "ChannelAdapterContributionV2",
    "ChannelAdapterMetadataV2",
    "ChannelAdapterResolverProtocolV2",
    "ChannelAdapterResolverV2",
    "builtin_channel_adapter_catalog_definition_v2",
    "builtin_feishu_channel_adapter_definition_v2",
]
