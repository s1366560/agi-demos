"""V2-owned production contributions for the builtin genes HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import status

from src.application.schemas.gene_schemas import (
    GeneListResponse,
    GeneRatingResponse,
    GeneResponse,
    GeneReviewListResponse,
    GeneReviewResponse,
    GenomeListResponse,
    GenomeRatingResponse,
    GenomeResponse,
)
from src.infrastructure.adapters.primary.web.routers import genes

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

GENES_HTTP_ROUTES_ENTRY_V2 = "builtin-genes-http-routes"
GENES_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/genes-routes"
GENES_HTTP_ROUTES_ROW_V2 = "genes"
_GENES_PREFIX_V2 = "/api/v1/genes"

type GenesRouteSpecV2 = tuple[
    Callable[..., Any],
    object | None,
    str,
    str,
    int | None,
    str | None,
]

_GENES_ROUTE_SPECS_V2: tuple[GenesRouteSpecV2, ...] = (
    (
        genes.create_gene,
        GeneResponse,
        "POST",
        "/",
        status.HTTP_201_CREATED,
        None,
    ),
    (genes.list_genes, GeneListResponse, "GET", "/", None, None),
    (genes.update_gene, GeneResponse, "PUT", "/{gene_id}", None, None),
    (
        genes.delete_gene,
        None,
        "DELETE",
        "/{gene_id}",
        status.HTTP_204_NO_CONTENT,
        None,
    ),
    (
        genes.publish_gene,
        GeneResponse,
        "POST",
        "/{gene_id}/publish",
        None,
        None,
    ),
    (
        genes.unpublish_gene,
        GeneResponse,
        "POST",
        "/{gene_id}/unpublish",
        None,
        None,
    ),
    (
        genes.create_genome,
        GenomeResponse,
        "POST",
        "/genomes",
        status.HTTP_201_CREATED,
        None,
    ),
    (genes.list_genomes, GenomeListResponse, "GET", "/genomes", None, None),
    (
        genes.get_genome,
        GenomeResponse,
        "GET",
        "/genomes/{genome_id}",
        None,
        None,
    ),
    (
        genes.update_genome,
        GenomeResponse,
        "PUT",
        "/genomes/{genome_id}",
        None,
        None,
    ),
    (
        genes.delete_genome,
        None,
        "DELETE",
        "/genomes/{genome_id}",
        status.HTTP_204_NO_CONTENT,
        None,
    ),
    (
        genes.publish_genome,
        GenomeResponse,
        "POST",
        "/genomes/{genome_id}/publish",
        None,
        None,
    ),
    (
        genes.unpublish_genome,
        GenomeResponse,
        "POST",
        "/genomes/{genome_id}/unpublish",
        None,
        None,
    ),
    (
        genes.install_gene,
        genes.InstanceGeneResponse,
        "POST",
        "/instances/{instance_id}/install",
        status.HTTP_201_CREATED,
        None,
    ),
    (
        genes.install_genome,
        genes.InstallGenomeResponse,
        "POST",
        "/instances/{instance_id}/genomes/{genome_id}/install",
        status.HTTP_201_CREATED,
        None,
    ),
    (
        genes.uninstall_gene,
        None,
        "DELETE",
        "/instances/{instance_id}/genes/{instance_gene_id}",
        status.HTTP_204_NO_CONTENT,
        None,
    ),
    (
        genes.list_instance_genes,
        genes.InstanceGeneListResponse,
        "GET",
        "/instances/{instance_id}/genes",
        None,
        None,
    ),
    (
        genes.get_instance_gene,
        genes.InstanceGeneResponse,
        "GET",
        "/instances/{instance_id}/genes/{instance_gene_id}",
        None,
        None,
    ),
    (
        genes.rate_gene,
        GeneRatingResponse,
        "POST",
        "/{gene_id}/ratings",
        status.HTTP_201_CREATED,
        None,
    ),
    (
        genes.list_gene_ratings,
        list[GeneRatingResponse],
        "GET",
        "/{gene_id}/ratings",
        None,
        None,
    ),
    (
        genes.list_genome_ratings,
        list[GenomeRatingResponse],
        "GET",
        "/genomes/{genome_id}/ratings",
        None,
        None,
    ),
    (
        genes.rate_genome,
        GenomeRatingResponse,
        "POST",
        "/genomes/{genome_id}/ratings",
        status.HTTP_201_CREATED,
        None,
    ),
    (
        genes.list_evolution_events,
        genes.EvolutionEventListResponse,
        "GET",
        "/evolution",
        None,
        None,
    ),
    (
        genes.create_evolution_event,
        genes.EvolutionEventResponse,
        "POST",
        "/evolution",
        status.HTTP_201_CREATED,
        None,
    ),
    (
        genes.get_evolution_event,
        genes.EvolutionEventResponse,
        "GET",
        "/evolution/{event_id}",
        None,
        None,
    ),
    (genes.get_gene, GeneResponse, "GET", "/{gene_id}", None, None),
    (
        genes.list_gene_reviews,
        GeneReviewListResponse,
        "GET",
        "/{gene_id}/reviews",
        None,
        "List gene reviews",
    ),
    (
        genes.create_gene_review,
        GeneReviewResponse,
        "POST",
        "/{gene_id}/reviews",
        None,
        "Create gene review",
    ),
    (
        genes.delete_gene_review,
        None,
        "DELETE",
        "/{gene_id}/reviews/{review_id}",
        status.HTTP_204_NO_CONTENT,
        "Delete gene review",
    ),
)


def _genes_route_v2(
    endpoint: Callable[..., Any],
    response_model: object | None,
    method: str,
    path: str,
    status_code: int | None,
    summary: str | None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=GENES_HTTP_ROUTES_ENTRY_V2,
        path=f"{_GENES_PREFIX_V2}{path}",
        methods=(method,),
        endpoint=endpoint,
        name=endpoint.__name__,
        tags=("Genes",),
        summary=summary,
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=GENES_HTTP_ROUTES_ROW_V2,
    )


def genes_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``genes`` inventory row."""
    return tuple(_genes_route_v2(*spec) for spec in _GENES_ROUTE_SPECS_V2)


def builtin_genes_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register genes routes as reversible effects of one V2 Fiber."""
    definitions = genes_route_definitions_v2()

    async def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        builder = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
        if not isinstance(builder, RouteTableBuilderV2):
            raise RuntimeV2Error(
                "invalid_route_table_builder",
                "route_table inject is not a protocol v2 route table builder",
            )

        async def setup() -> tuple[Callable[[], Awaitable[None]], ...]:
            disposers: list[Callable[[], Awaitable[None]]] = []
            try:
                for definition in definitions:
                    disposers.append(builder.contribute(definition))
            except Exception:
                for dispose in reversed(disposers):
                    await dispose()
                raise
            return tuple(disposers)

        await context.effect(setup, label=GENES_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=GENES_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(GENES_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "GENES_HTTP_ROUTES_ENTRY_V2",
    "GENES_HTTP_ROUTES_MODULE_V2",
    "GENES_HTTP_ROUTES_ROW_V2",
    "builtin_genes_http_routes_definition_v2",
    "genes_route_definitions_v2",
]
