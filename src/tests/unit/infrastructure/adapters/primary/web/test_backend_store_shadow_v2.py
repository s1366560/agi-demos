"""FastAPI wiring coverage for the graph/retrieval V2 shadow boundary."""

from __future__ import annotations

from inspect import signature

import pytest
from fastapi.params import Depends

from src.infrastructure.adapters.primary.web.routers import projects

pytestmark = pytest.mark.unit


def test_backend_store_shadow_remains_on_uncutover_project_composition() -> None:
    parameter = signature(projects.list_projects).parameters["_backend_store_shadow"]

    assert isinstance(parameter.default, Depends)
