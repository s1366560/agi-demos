from __future__ import annotations

import pytest
from starlette.routing import Match

from src.infrastructure.adapters.primary.web.routers.genes import router


def _matched_endpoint_name(path: str, method: str) -> str | None:
    scope = {
        "type": "http",
        "path": path,
        "method": method,
        "headers": [],
        "root_path": "",
    }
    for route in router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return route.endpoint.__name__
    return None


@pytest.mark.parametrize(
    ("path", "method", "endpoint_name"),
    [
        ("/api/v1/genes/genomes", "GET", "list_genomes"),
        ("/api/v1/genes/genomes/genome_123/unpublish", "POST", "unpublish_genome"),
        ("/api/v1/genes/evolution", "GET", "list_evolution_events"),
        ("/api/v1/genes/gene_123", "GET", "get_gene"),
    ],
)
def test_static_gene_routes_match_before_generic_gene_lookup(
    path: str,
    method: str,
    endpoint_name: str,
) -> None:
    assert _matched_endpoint_name(path, method) == endpoint_name
