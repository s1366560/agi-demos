"""Authority coverage for the episodes HTTP surface."""

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
from src.infrastructure.adapters.primary.web.routers import episodes
from src.infrastructure.adapters.secondary.persistence.models import User

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "handler",
    (
        episodes.create_episode,
        episodes.get_episode,
        episodes.list_episodes,
        episodes.delete_episode,
        episodes.health_check,
    ),
)
def test_episode_routes_require_v2_graph_application_authority(handler: object) -> None:
    parameters = signature(handler).parameters
    parameter = parameters["graph_application"]

    assert parameter.default.dependency is graph_application_authority_dependency_v2
    assert parameter.annotation in {"GraphApplicationAuthorityV2", GraphApplicationAuthorityV2}
    assert "db" not in parameters
    assert "graph_store" not in parameters


def test_episode_routes_remove_static_graph_dependencies() -> None:
    assert "get_db" not in vars(episodes)
    assert "get_graph_store" not in vars(episodes)


async def test_episode_health_unavailable_preserves_http_503_contract() -> None:
    authority = SimpleNamespace(
        db=SimpleNamespace(),
        services=SimpleNamespace(graph_store=None),
    )

    with pytest.raises(HTTPException) as error:
        await episodes.health_check(
            current_user=cast(User, SimpleNamespace(id="user-a")),
            graph_application=authority,
        )

    assert error.value.status_code == 503
    assert error.value.detail == "Service unhealthy"
