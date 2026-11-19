"""Health and OpenAPI publish one API release string."""

from __future__ import annotations

import pytest

from src.configuration.api_release import API_RELEASE_VERSION
from src.infrastructure.adapters.primary.web.main import create_app


@pytest.mark.unit
async def test_health_and_openapi_share_the_api_release() -> None:
    app = create_app()
    health = None
    for route in app.routes:
        if getattr(route, "path", None) == "/health":
            health = route.endpoint
            break
    assert health is not None
    assert app.version == API_RELEASE_VERSION
    assert app.openapi()["info"]["version"] == API_RELEASE_VERSION
    assert await health() == {"status": "ok", "version": API_RELEASE_VERSION}
