"""FastAPI wiring coverage for the graph/retrieval V2 shadow boundary."""

from __future__ import annotations

from inspect import signature

import pytest
from fastapi.params import Depends

from src.infrastructure.adapters.primary.web.routers import (
    graph_stores,
    projects,
    retrieval_stores,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "endpoint",
    (
        graph_stores.list_store_types,
        retrieval_stores.list_store_types,
        projects.list_projects,
    ),
)
def test_backend_store_shadow_is_attached_to_production_composition_points(
    endpoint: object,
) -> None:
    parameter = signature(endpoint).parameters["_backend_store_shadow"]

    assert isinstance(parameter.default, Depends)
