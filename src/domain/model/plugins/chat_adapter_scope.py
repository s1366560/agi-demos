"""Provider coverage declared by signed and approved model adapter permissions."""

from collections.abc import Collection

CHAT_ADAPTER_GRANTS = {
    "model.chat.adapt": frozenset({"openai", "deepseek"}),
    "model.chat.adapt.openai": frozenset({"openai"}),
    "model.chat.adapt.deepseek": frozenset({"deepseek"}),
}


def chat_adapter_providers(permissions: Collection[str]) -> frozenset[str]:
    return frozenset(
        provider
        for permission, providers in CHAT_ADAPTER_GRANTS.items()
        if permission in permissions
        for provider in providers
    )


def chat_adapter_pin(permissions: Collection[str]) -> dict[str, str | int]:
    """Pin provider scope with the existing run selection, including generic V2 adapters."""
    providers = chat_adapter_providers(permissions)
    if not providers:
        return {}
    if len(providers) == 1:
        return {"chat_adapter": True, "chat_provider": next(iter(providers))}
    return {"chat_adapter": True}
