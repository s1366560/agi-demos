"""Tool for listing currently available chat models across active providers."""

from __future__ import annotations

import difflib
import json
import logging
from typing import Any

from src.domain.llm_providers.models import OperationType, ProviderConfig
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.llm.model_catalog import get_model_catalog_service
from src.infrastructure.persistence.llm_providers_repository import SQLAlchemyProviderRepository

logger = logging.getLogger(__name__)

_PROVIDER_ALIASES: dict[str, str] = {
    "azure_openai": "openai",
}


def _normalize_provider_for_catalog(provider_type: str) -> str:
    """Normalize provider type to catalog provider key."""
    normalized = provider_type.strip().lower()
    for suffix in ("_coding", "_embedding", "_reranker"):
        if normalized.endswith(suffix):
            normalized = normalized.removesuffix(suffix)
            break
    return _PROVIDER_ALIASES.get(normalized, normalized)


def _provider_type_value(provider_type: Any) -> str:
    """Convert provider type enum/string to string value."""
    raw = getattr(provider_type, "value", provider_type)
    return str(raw or "").strip()


def _build_model_metadata_payload(meta: Any) -> dict[str, Any]:
    """Build compact metadata payload for model list responses."""
    return {
        "name": meta.name,
        "provider": meta.provider,
        "context_length": meta.context_length,
        "max_output_tokens": meta.max_output_tokens,
        "supports_attachment": meta.supports_attachment,
        "supports_temperature": meta.supports_temperature,
        "supports_tool_call": meta.supports_tool_call,
        "reasoning": meta.reasoning,
        "is_deprecated": meta.is_deprecated,
    }


async def _resolve_candidate_providers(tenant_id: str) -> list[ProviderConfig]:
    """Resolve active tenant providers (or global active providers as fallback)."""
    async with async_session_factory() as session:
        repository = SQLAlchemyProviderRepository(session=session)
        tenant_mappings = await repository.get_tenant_providers(tenant_id, OperationType.LLM)

        providers: list[ProviderConfig]
        if tenant_mappings:
            active_providers = [
                provider for provider in await repository.list_active() if provider.is_enabled
            ]
            active_provider_by_id = {provider.id: provider for provider in active_providers}
            providers = [
                active_provider_by_id[mapping.provider_id]
                for mapping in tenant_mappings
                if mapping.provider_id in active_provider_by_id
            ]
        else:
            providers = [
                provider
                for provider in await repository.list_active()
                if provider.is_active and provider.is_enabled
            ]

    # Keep a single active config per provider type (first one by priority/creation order wins)
    deduplicated: list[ProviderConfig] = []
    seen_provider_types: set[str] = set()
    for provider in providers:
        provider_type = _provider_type_value(provider.provider_type)
        if provider_type in seen_provider_types:
            continue
        seen_provider_types.add(provider_type)
        deduplicated.append(provider)

    return deduplicated


async def _persist_model_override(conversation_id: str, model_name: str) -> None:
    try:
        from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
            SqlConversationRepository,
        )

        async with async_session_factory() as session:
            repo = SqlConversationRepository(session)
            conversation = await repo.find_by_id(conversation_id)
            if conversation:
                conversation.update_agent_config({"llm_model_override": model_name})
                await repo.save(conversation)
                await session.commit()
    except Exception:
        logger.warning(
            "Failed to persist model override for conversation %s",
            conversation_id,
            exc_info=True,
        )


def _collect_provider_models(
    provider: ProviderConfig,
    *,
    include_deprecated: bool,
) -> tuple[str, str, dict[str, Any | None]]:
    """Collect available model metadata for a single provider."""
    provider_type = _provider_type_value(provider.provider_type)
    catalog_provider = _normalize_provider_for_catalog(provider_type)
    catalog = get_model_catalog_service()
    metadata_by_name: dict[str, Any | None] = {}

    catalog_models = catalog.list_models(
        provider=catalog_provider,
        include_deprecated=include_deprecated,
    )
    for meta in catalog_models:
        if provider.is_model_allowed(meta.name):
            metadata_by_name[meta.name] = meta

    for configured_model in (provider.llm_model, provider.llm_small_model):
        normalized = (configured_model or "").strip()
        if not normalized:
            continue
        canonical_meta = catalog.get_model_fuzzy(normalized)
        canonical_name = canonical_meta.name if canonical_meta is not None else normalized
        if not provider.is_model_allowed(canonical_name):
            continue
        metadata_by_name.setdefault(canonical_name, canonical_meta)

    return provider_type, catalog_provider, metadata_by_name


def _build_model_suggestions(
    requested_model: str,
    available_models: list[str],
    *,
    limit: int = 8,
) -> list[str]:
    """Return a compact, stable suggestion list for invalid model requests."""
    if not available_models:
        return []

    normalized = requested_model.strip().lower()
    ranked: list[str] = []

    if normalized:
        for name in available_models:
            name_lower = name.lower()
            if name_lower.startswith(normalized) and name not in ranked:
                ranked.append(name)
        for name in available_models:
            if normalized in name.lower() and name not in ranked:
                ranked.append(name)

    for name in difflib.get_close_matches(requested_model, available_models, n=limit, cutoff=0.3):
        if name not in ranked:
            ranked.append(name)

    if not ranked:
        ranked = list(available_models)

    return ranked[:limit]


def _resolve_requested_model_name(
    requested_model: str,
    *,
    model_lookup: dict[str, tuple[str, ProviderConfig, str]],
) -> tuple[str, ProviderConfig, str] | None:
    """Resolve a requested model string to canonical model + provider tuple."""
    normalized_requested = requested_model.strip()
    if not normalized_requested:
        return None

    catalog = get_model_catalog_service()
    candidates: list[str] = []

    def _add_candidate(value: str | None) -> None:
        if value is None:
            return
        normalized = value.strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    _add_candidate(normalized_requested)
    canonical_meta = catalog.get_model_fuzzy(normalized_requested)
    _add_candidate(canonical_meta.name if canonical_meta is not None else None)

    if "/" in normalized_requested:
        _add_candidate(normalized_requested.split("/", 1)[1])
    if canonical_meta is not None and "/" in canonical_meta.name:
        _add_candidate(canonical_meta.name.split("/", 1)[1])

    for candidate in candidates:
        resolved = model_lookup.get(candidate.lower())
        if resolved is not None:
            return resolved
    return None


@tool_define(
    name="list_available_models",
    description=(
        "List currently available chat models across active LLM providers in this tenant. "
        "Use this before model switching so you only choose models currently allowed by "
        "provider and allow/block rules."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional substring filter for model names.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of models to return.",
                "minimum": 1,
                "maximum": 200,
                "default": 50,
            },
            "include_deprecated": {
                "type": "boolean",
                "description": "Whether to include deprecated models.",
                "default": False,
            },
            "include_metadata": {
                "type": "boolean",
                "description": "Whether to return per-model metadata instead of names only.",
                "default": False,
            },
        },
        "required": [],
    },
    permission=None,
    category="llm",
)
async def list_available_models_tool(
    ctx: ToolContext,
    *,
    query: str | None = None,
    limit: int = 50,
    include_deprecated: bool = False,
    include_metadata: bool = False,
) -> ToolResult:
    """Return available models across active chat providers."""
    tenant_id = (ctx.tenant_id or "").strip()
    if not tenant_id:
        return ToolResult(
            output=json.dumps(
                {"error": "tenant_id is required to list available models", "models": []},
                ensure_ascii=False,
            ),
            is_error=True,
        )

    providers = await _resolve_candidate_providers(tenant_id)
    if not providers:
        return ToolResult(
            output=json.dumps(
                {
                    "error": "No active LLM providers configured for this tenant",
                    "tenant_id": tenant_id,
                    "models": [],
                },
                ensure_ascii=False,
            ),
            is_error=True,
        )

    metadata_by_name: dict[str, Any | None] = {}
    providers_payload: list[dict[str, Any]] = []
    for provider in providers:
        provider_type, catalog_provider, provider_metadata = _collect_provider_models(
            provider,
            include_deprecated=include_deprecated,
        )
        provider_model_names = sorted(provider_metadata.keys())
        providers_payload.append(
            {
                "name": provider.name,
                "provider_type": provider_type,
                "catalog_provider": catalog_provider,
                "llm_model": provider.llm_model,
                "llm_small_model": provider.llm_small_model,
                "allowed_models": provider.allowed_models,
                "blocked_models": provider.blocked_models,
                "total_available_models": len(provider_model_names),
            }
        )
        for model_name, model_meta in provider_metadata.items():
            metadata_by_name.setdefault(model_name, model_meta)

    normalized_query = (query or "").strip().lower()
    all_names = sorted(metadata_by_name.keys())
    filtered_names = (
        [name for name in all_names if normalized_query in name.lower()]
        if normalized_query
        else all_names
    )
    limited_names = filtered_names[:limit]

    # Prepend the virtual "auto" entry when it matches the query so the
    # LLM (and downstream selector UI) can discover Agent-First routing.
    show_auto = not normalized_query or "auto" in normalized_query
    auto_entry_meta = {
        "name": "auto",
        "provider": None,
        "description": (
            "Agent-First auto-router. Picks the best concrete model from "
            "the tenant's pool per turn (tier, vision, tools)."
        ),
        "is_virtual": True,
    }

    models_payload: list[Any]
    if include_metadata:
        models_payload = []
        if show_auto:
            models_payload.append(auto_entry_meta)
        for name in limited_names:
            meta = metadata_by_name.get(name)
            if meta is None:
                models_payload.append({"name": name, "provider": None})
                continue
            models_payload.append(_build_model_metadata_payload(meta))
    else:
        models_payload = (["auto"] if show_auto else []) + limited_names

    primary_provider = providers_payload[0] if providers_payload else None
    payload = {
        "tenant_id": tenant_id,
        "project_id": ctx.project_id or None,
        "provider": primary_provider,  # Backward-compatible primary provider field
        "providers": providers_payload,
        "query": normalized_query or None,
        "total_available_models": len(filtered_names),
        "returned_models": len(limited_names),
        "models": models_payload,
    }

    return ToolResult(output=json.dumps(payload, ensure_ascii=False))


@tool_define(
    name="switch_model_next_turn",
    description=(
        "Schedule model switching for the next user turn. "
        "Use this when the user asks to use a specific model next round."
    ),
    parameters={
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": "Target model name to apply starting from the next user turn.",
            },
            "reason": {
                "type": "string",
                "description": "Optional reason to show in UI/event payload.",
            },
        },
        "required": ["model"],
    },
    permission=None,
    category="llm",
)
async def switch_model_next_turn_tool(
    ctx: ToolContext,
    *,
    model: str,
    reason: str | None = None,
) -> ToolResult:
    """Validate and emit next-turn model switch event for frontend state sync."""
    tenant_id = (ctx.tenant_id or "").strip()
    if not tenant_id:
        return ToolResult(
            output=json.dumps(
                {
                    "status": "error",
                    "error": "tenant_id is required to switch model",
                    "requested_model": model,
                },
                ensure_ascii=False,
            ),
            is_error=True,
        )

    requested_model = (model or "").strip()
    if not requested_model:
        return ToolResult(
            output=json.dumps(
                {
                    "status": "error",
                    "error": "model is required",
                    "requested_model": model,
                },
                ensure_ascii=False,
            ),
            is_error=True,
        )

    providers = await _resolve_candidate_providers(tenant_id)
    if not providers:
        return ToolResult(
            output=json.dumps(
                {
                    "status": "error",
                    "error": "No active LLM providers configured for this tenant",
                    "tenant_id": tenant_id,
                    "requested_model": requested_model,
                },
                ensure_ascii=False,
            ),
            is_error=True,
        )

    metadata_by_name: dict[str, Any | None] = {}
    model_lookup: dict[str, tuple[str, ProviderConfig, str]] = {}
    for provider in providers:
        provider_type, _catalog_provider, provider_metadata = _collect_provider_models(
            provider,
            include_deprecated=False,
        )
        for model_name, model_meta in provider_metadata.items():
            metadata_by_name.setdefault(model_name, model_meta)
            model_lookup.setdefault(model_name.lower(), (model_name, provider, provider_type))

    resolved_model = _resolve_requested_model_name(requested_model, model_lookup=model_lookup)
    if resolved_model is None:
        available_models = sorted(metadata_by_name.keys())
        return ToolResult(
            output=json.dumps(
                {
                    "status": "error",
                    "error": f"Requested model '{requested_model}' is not available in this tenant",
                    "requested_model": requested_model,
                    "suggestions": _build_model_suggestions(requested_model, available_models),
                },
                ensure_ascii=False,
            ),
            is_error=True,
        )

    canonical_model_name, provider_config, provider_type = resolved_model
    normalized_reason = (reason or "").strip() or None
    event_payload = {
        "conversation_id": ctx.conversation_id,
        "tenant_id": tenant_id,
        "project_id": ctx.project_id or None,
        "model": canonical_model_name,
        "provider_type": provider_type,
        "provider_name": provider_config.name,
        "scope": "next_turn",
        "reason": normalized_reason,
    }
    await ctx.emit({"type": "model_switch_requested", "data": event_payload})

    await _persist_model_override(ctx.conversation_id, canonical_model_name)

    return ToolResult(
        output=json.dumps(
            {
                "status": "scheduled",
                "message": f"Model switch scheduled for next turn: {canonical_model_name}",
                **event_payload,
            },
            ensure_ascii=False,
        )
    )
