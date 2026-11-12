"""An unstaged plugin generation fails closed instead of serving another table."""

import pytest

from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


def test_unstaged_generation_reports_route_table_unavailable() -> None:
    registry = RouteTableRegistryV2()
    with pytest.raises(RuntimeV2Error) as raised:
        registry.resolve("generation-not-staged")
    assert raised.value.code == "route_generation_unavailable"
    assert "pinned plugin generation" in str(raised.value)
