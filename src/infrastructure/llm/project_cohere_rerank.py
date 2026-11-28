"""Apply a project's signed Cohere adapter using its tenant-authorized model transport."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from src.configuration.config import get_settings
from src.domain.llm_providers.models import (
    OperationType,
    ProviderType,
    validate_provider_base_url_transport,
)
from src.domain.llm_providers.provider_catalog import family_security
from src.host.packages.project_plugin_installation import ProjectPluginInstallationService
from src.infrastructure.adapters.secondary.persistence.models import Project
from src.infrastructure.llm.litellm.litellm_reranker import LiteLLMReranker, LiteLLMRerankerConfig
from src.infrastructure.llm.provider_credentials import resolve_persisted_provider_credential
from src.infrastructure.persistence.llm_providers_repository import SQLAlchemyProviderRepository
from src.infrastructure.plugins.package_registry import load_plugin_trust_keys
from src.infrastructure.plugins.v2.project_package_execution import invoke_project_tool
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    ScopeBindingV2,
    SignedPackageBytesV2,
)
from src.infrastructure.security.encryption_service import get_encryption_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class _Options(_Strict):
    top_n: int = Field(ge=1, le=200)
    max_chunks_per_doc: int = Field(ge=1, le=10)


class _Match(_Strict):
    index: int = Field(ge=0)
    score: float = Field(ge=0, le=1)


class _Matches(_Strict):
    matches: list[_Match] = Field(max_length=200)


async def _tenant_transport(db: AsyncSession, tenant: str) -> LiteLLMReranker:
    provider = await SQLAlchemyProviderRepository(db).find_tenant_provider(
        tenant, OperationType.RERANK
    )
    if (
        provider is None
        or not provider.is_enabled
        or provider.provider_type != ProviderType.COHERE
        or not provider.reranker_model
        or not provider.is_model_allowed(provider.reranker_model)
    ):
        raise ValueError("No authorized Cohere reranker is assigned")
    security = family_security("cohere")
    if security is None or security.probe_base_url is None:
        raise ValueError("Cohere transport is unavailable")
    base = validate_provider_base_url_transport(
        provider.base_url or security.probe_base_url, ProviderType.COHERE
    )
    if not base:
        raise ValueError("Cohere endpoint is unavailable")
    credential = resolve_persisted_provider_credential(
        provider_type=ProviderType.COHERE,
        config=provider.config,
        base_url=base,
        api_key_encrypted=provider.api_key_encrypted,
        decrypt=get_encryption_service().decrypt,
    )
    if not credential:
        raise ValueError("Cohere transport needs an authorized credential")
    # LiteLLM appends /v1/rerank to base URLs other than a complete operation URL.
    base = base.rstrip("/")
    if base.endswith("/v1"):
        base += "/rerank"
    return LiteLLMReranker(
        LiteLLMRerankerConfig(
            model=provider.reranker_model,
            provider_type=ProviderType.COHERE,
            api_key=credential,
            base_url=base,
        )
    )


async def rank_project_search(
    db: AsyncSession,
    project_id: str,
    query: str,
    results: list[dict[str, Any]],
    limit: int,
    *,
    actor_id: str | None = None,
) -> list[dict[str, Any]]:
    """The caller has checked graph read access before fetching project candidates."""
    if len(results) < 2:
        return results
    tenant, plugin_id = (
        await db.execute(
            select(
                Project.tenant_id, Project.graph_config["cohere_rerank_package"].as_string()
            ).where(Project.id == project_id)
        )
    ).one()
    if not plugin_id:
        return results
    scope = ScopeBindingV2(tenant_id=tenant, project_id=project_id)
    keys = await asyncio.to_thread(
        load_plugin_trust_keys, get_settings().plugin_marketplace_trusted_key_files
    )
    service = ProjectPluginInstallationService(db, scope, tuple(keys), actor_id=actor_id)
    count = len(results)

    async def rerank(package: SignedPackageBytesV2) -> list[dict[str, Any]]:
        if package.worker is not None or package.approved_permissions != frozenset(
            {"tools.execute"}
        ):
            raise ValueError("Cohere adapters must be compute-only Wasm packages")

        async def adapt(payload: dict[str, Any]) -> dict[str, Any]:
            return await invoke_project_tool(
                package, scope, "adapt_rerank", {"candidate_count": count, **payload}
            )

        options = _Options.model_validate(await adapt({"operation": "request", "limit": limit}))
        if options.top_n > min(limit, count):
            raise ValueError("Cohere adapter exceeded the selected candidate count")
        host = await _tenant_transport(db, tenant)
        scores = await host.native_cohere_scores(
            query,
            [item["content"] for item in results],
            options.top_n,
            max_chunks_per_doc=options.max_chunks_per_doc,
        )
        if len(scores) > options.top_n:
            raise ValueError("Cohere returned too many scores")
        raw = [{"index": i, "relevance_score": v} for i, v in scores]
        matches = _Matches.model_validate(
            await adapt({"operation": "response", "results": raw})
        ).matches
        available = {i for i, _ in scores if 0 <= i < count}
        indices = {match.index for match in matches}
        if len(matches) != len(indices) or not indices <= available:
            raise ValueError("Cohere adapter returned an invalid candidate position")
        return [{**results[match.index], "score": match.score} for match in matches]

    return await service.call_active(plugin_id, rerank)
