"""Selectable chat models for an admitted tenant. Host-owned catalog lookup."""

from __future__ import annotations

from typing import Any

from src.infrastructure.persistence.tenant_model_roster import selectable_provider_models


def routes_for(providers: list[Any]) -> tuple[str | None, dict[str, str]]:
    routes: dict[str, str] = {}
    default = None
    for provider in providers:
        offered = selectable_provider_models(provider)
        if default is None and provider.llm_model in offered:
            default = provider.llm_model
        for model in offered:
            routes.setdefault(model, str(provider.id))
    return default, routes
