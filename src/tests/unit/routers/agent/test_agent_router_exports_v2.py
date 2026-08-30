"""Static retirement gates for Agent router composition helpers."""

from __future__ import annotations

import pytest

from src.infrastructure.adapters.primary.web.routers import agent

pytestmark = pytest.mark.unit


def test_agent_router_does_not_export_scoped_di_container_helper() -> None:
    assert "get_container_with_db" not in agent.__all__
    assert not hasattr(agent, "get_container_with_db")
