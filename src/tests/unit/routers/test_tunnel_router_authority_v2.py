"""Static production-boundary checks for the V2-owned tunnel router."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from src.infrastructure.adapters.primary.web.routers import tunnel as subject

pytestmark = pytest.mark.unit


def test_router_handlers_are_thin_generation_authority_mappings() -> None:
    connect_parameters = inspect.signature(subject.tunnel_connect).parameters
    status_parameters = inspect.signature(subject.tunnel_status).parameters

    assert tuple(connect_parameters) == ("websocket", "tunnel")
    assert tuple(status_parameters) == ("tunnel",)


def test_router_source_has_no_static_adapter_database_or_authorization_path() -> None:
    source = Path(subject.__file__).read_text(encoding="utf-8")

    for forbidden in (
        "TunnelAdapter",
        "_tunnel_adapter",
        "sqlalchemy",
        "get_db",
        "has_global_admin_access",
        "authenticate_websocket_or_close",
    ):
        assert forbidden not in source
