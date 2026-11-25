"""Eligible explicit tenant LLM routes in provider registry priority order."""

from __future__ import annotations

import json
from typing import cast

from sqlalchemy import Select, select

from src.domain.llm_providers.models import model_allowed_by_prefix
from src.infrastructure.persistence.llm_providers_models import LLMProvider, TenantProviderMapping


def tenant_chat_providers(tenant_id: str) -> Select[tuple[LLMProvider]]:
    return (
        select(LLMProvider)
        .join(TenantProviderMapping, TenantProviderMapping.provider_id == LLMProvider.id)
        .where(
            TenantProviderMapping.tenant_id == tenant_id,
            TenantProviderMapping.operation_type == "llm",
            LLMProvider.operation_type == "llm",
            LLMProvider.is_active.is_(True),
            LLMProvider.is_enabled.is_(True),
        )
        .order_by(TenantProviderMapping.priority, LLMProvider.created_at, LLMProvider.id)
    )


def declared_provider_models(provider: LLMProvider) -> set[str]:
    models: set[str] = {provider.llm_model} if provider.llm_model else set()
    if provider.allowed_models:
        try:
            values: object = json.loads(provider.allowed_models)
        except json.JSONDecodeError:
            values = []
        if isinstance(values, list):
            models.update(str(value) for value in cast(list[object], values) if value)
    models.update(provider.secondary_models or [])
    return models


def selectable_provider_models(provider: LLMProvider) -> set[str]:
    """Apply the chat execution allow/block rules to the registry's declared identities."""
    blocked = json.loads(provider.blocked_models or "[]")
    allowed = json.loads(provider.allowed_models or "[]")
    return {
        model
        for model in declared_provider_models(provider)
        if model_allowed_by_prefix(model, allowed, blocked)
    }
