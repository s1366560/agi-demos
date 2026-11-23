"""Register Feishu protocol metadata and its factory on a selected channel generation."""

from collections.abc import Mapping
from typing import Any

from src.infrastructure.plugins.v2.channel_adapters import (
    ChannelAdapterBuildContextV2,
    ChannelAdapterCatalogProtocolV2,
    ChannelAdapterContributionV2,
    ChannelAdapterDisposerV2,
    ChannelAdapterMetadataV2,
)
from src.infrastructure.plugins.v2.runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

FEISHU_CHANNEL_ADAPTER_MODULE_V2 = "builtin://memstack/channel/feishu-adapter"


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
                    "task_timeline_package": {
                        "type": ["string", "null"],
                        "title": "Signed task timeline rendering package",
                        "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$",
                    },
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


def builtin_feishu_channel_adapter_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=FEISHU_CHANNEL_ADAPTER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(FEISHU_CHANNEL_ADAPTER_MODULE_V2),
        apply=_apply_feishu_channel_adapter_v2,
    )
