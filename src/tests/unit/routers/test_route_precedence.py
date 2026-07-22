"""Regression tests for static API routes that overlap dynamic resource paths."""

import pytest

from src.infrastructure.adapters.primary.web.main import app


@pytest.mark.unit
def test_workspace_routing_policy_precedes_dynamic_provider_route() -> None:
    paths = [route.path for route in app.routes]

    assert paths.index("/api/v1/llm-providers/routing-policy") < paths.index(
        "/api/v1/llm-providers/{provider_id}"
    )
