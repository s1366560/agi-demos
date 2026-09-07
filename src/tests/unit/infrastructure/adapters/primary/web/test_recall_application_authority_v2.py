"""Authority coverage for the recall HTTP surface."""

from __future__ import annotations

from inspect import signature
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.graph_application_authority_v2 import (
    GraphApplicationAuthorityV2,
    graph_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import recall
from src.infrastructure.adapters.secondary.persistence.models import User

pytestmark = pytest.mark.unit


def test_recall_route_requires_v2_graph_application_authority() -> None:
    parameters = signature(recall.short_term_recall).parameters
    parameter = parameters["graph_application"]

    assert parameter.default.dependency is graph_application_authority_dependency_v2
    assert parameter.annotation in {"GraphApplicationAuthorityV2", GraphApplicationAuthorityV2}
    assert "db" not in parameters
    assert "graph_store" not in parameters


def test_recall_route_removes_static_graph_dependencies() -> None:
    assert "get_db" not in vars(recall)
    assert "get_graph_store" not in vars(recall)


async def test_recall_unavailable_preserves_http_503_contract() -> None:
    authority = SimpleNamespace(
        db=SimpleNamespace(),
        services=SimpleNamespace(graph_store=None),
    )

    with pytest.raises(HTTPException) as error:
        await recall.short_term_recall(
            recall.ShortTermRecallQuery(),
            current_user=cast(User, SimpleNamespace(id="user-a")),
            graph_application=authority,
        )

    assert error.value.status_code == 503
    assert error.value.detail == "Graph backend unavailable"
