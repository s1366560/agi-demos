"""Zero-reference gates for retired static MCP application composition."""

from __future__ import annotations

import pytest

from src.configuration.containers.sandbox_container import SandboxContainer
from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.primary.web.routers.mcp import utils

pytestmark = pytest.mark.unit

_RETIRED_ACCESSORS = {
    "sandbox_mcp_server_manager",
    "mcp_app_service",
    "mcp_runtime_service",
}


def test_static_mcp_application_facades_are_removed() -> None:
    assert _RETIRED_ACCESSORS.isdisjoint(vars(DIContainer))
    assert _RETIRED_ACCESSORS.isdisjoint(vars(SandboxContainer))
    assert "get_sandbox_mcp_server_manager" not in vars(utils)
