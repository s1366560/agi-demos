"""Unit tests for Ray client retry state handling."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.infrastructure.adapters.secondary.ray import client


@pytest.mark.unit
@pytest.mark.asyncio
async def test_init_ray_if_needed_reads_package_failure_flag_dynamically(monkeypatch):
    """A transient import-time Ray failure must not poison later worker retries."""

    monkeypatch.setattr(client.ray, "is_initialized", MagicMock(return_value=False))
    ray_init = MagicMock()
    monkeypatch.setattr(client.ray, "init", ray_init)
    monkeypatch.setattr(
        client,
        "get_ray_settings",
        lambda: SimpleNamespace(
            ray_address="ray://ray-head:10001",
            ray_namespace="memstack",
            ray_log_to_driver=False,
        ),
    )
    monkeypatch.setattr(client.ray_pkg, "_check_ray_reachable", lambda *_args: True)
    monkeypatch.setattr(client.ray_pkg, "_ray_init_failed", True)
    client._ray_available = False

    assert await client.init_ray_if_needed() is False
    ray_init.assert_not_called()

    monkeypatch.setattr(client.ray_pkg, "_ray_init_failed", False)

    assert await client.init_ray_if_needed() is True
    ray_init.assert_called_once_with(
        address="ray://ray-head:10001",
        namespace="memstack",
        log_to_driver=False,
        ignore_reinit_error=True,
    )
