"""Unit tests for Ray client retry state handling."""

from __future__ import annotations

import asyncio
import importlib
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.configuration.ray_config import RaySettings
from src.infrastructure.adapters.secondary import ray as ray_pkg
from src.infrastructure.adapters.secondary.ray import client


@pytest.fixture(autouse=True)
def reset_ray_client_state(monkeypatch):
    """Keep Ray client globals and timeout env isolated between tests."""

    client._ray_available = False
    client._ray_failure_cooldown_until = 0
    monkeypatch.setattr(client.ray_pkg, "_ray_init_failed", False, raising=False)
    monkeypatch.delenv("RAY_CONNECT_TIMEOUT", raising=False)
    monkeypatch.delenv("RAY_INIT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("RAY_FAILURE_COOLDOWN_SECONDS", raising=False)
    yield
    client._ray_available = False
    client._ray_failure_cooldown_until = 0


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        ray_address="ray://ray-head:10001",
        ray_namespace="memstack",
        ray_log_to_driver=False,
    )


def _direct_settings() -> SimpleNamespace:
    return SimpleNamespace(
        ray_address="ray-head:6379",
        ray_namespace="memstack",
        ray_log_to_driver=False,
    )


def test_ray_init_timeout_default_allows_container_client_startup():
    """The default Ray client init window must tolerate normal Docker startup latency."""

    assert RaySettings().ray_init_timeout_seconds >= 15.0
    assert client._ray_init_timeout_seconds() >= 15.0


def test_ray_adapter_import_has_no_connection_side_effects(monkeypatch):
    """Importing the Ray adapter should not connect or set default env."""

    monkeypatch.delenv("RAY_ADDRESS", raising=False)
    monkeypatch.delenv("RAY_NAMESPACE", raising=False)
    ray_init = MagicMock()
    tcp_connect = MagicMock()
    monkeypatch.setattr(ray_pkg.ray, "init", ray_init)
    monkeypatch.setattr(ray_pkg.socket, "create_connection", tcp_connect)

    reloaded = importlib.reload(ray_pkg)

    ray_init.assert_not_called()
    tcp_connect.assert_not_called()
    assert os.environ.get("RAY_ADDRESS") is None
    assert os.environ.get("RAY_NAMESPACE") is None
    assert reloaded._ray_init_failed is False


def test_ray_reachable_accepts_auto_address_without_tcp_probe(monkeypatch):
    tcp_connect = MagicMock()
    monkeypatch.setattr(ray_pkg.socket, "create_connection", tcp_connect)

    assert ray_pkg._check_ray_reachable("auto") is True
    tcp_connect.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_init_ray_if_needed_reads_package_failure_flag_dynamically(monkeypatch):
    """A transient import-time Ray failure must not poison later worker retries."""

    monkeypatch.setattr(client.ray, "is_initialized", MagicMock(return_value=False))
    ray_init = MagicMock()
    monkeypatch.setattr(client.ray, "init", ray_init)
    monkeypatch.setattr(client, "get_ray_settings", _settings)
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ray_client_init_runs_on_event_loop_thread(monkeypatch):
    """Ray Client forks a server process and must not run in executor threads."""

    monkeypatch.setattr(client.ray, "is_initialized", MagicMock(return_value=False))
    monkeypatch.setattr(client.ray_pkg, "_check_ray_reachable", MagicMock(return_value=True))
    monkeypatch.setattr(client, "get_ray_settings", _settings)
    event_loop_thread = threading.get_ident()
    init_threads: list[int] = []

    def record_init(**_kwargs):
        init_threads.append(threading.get_ident())

    monkeypatch.setattr(client.ray, "init", MagicMock(side_effect=record_init))

    assert await client.init_ray_if_needed() is True
    assert init_threads == [event_loop_thread]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_init_ray_if_needed_unreachable_sets_cooldown(monkeypatch):
    """A failed TCP pre-check should fail fast and avoid ray.init."""

    monkeypatch.setattr(client.ray, "is_initialized", MagicMock(return_value=False))
    ray_init = MagicMock()
    check_reachable = MagicMock(return_value=False)
    monkeypatch.setattr(client.ray, "init", ray_init)
    monkeypatch.setattr(client.ray_pkg, "_check_ray_reachable", check_reachable)
    monkeypatch.setattr(client, "get_ray_settings", _settings)

    assert await client.init_ray_if_needed() is False

    check_reachable.assert_called_once_with("ray://ray-head:10001", 3.0)
    ray_init.assert_not_called()
    assert client._cooldown_remaining_seconds() > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_init_ray_if_needed_cooldown_skips_repeated_probe(monkeypatch):
    """Repeated calls during cooldown should not keep probing a dead cluster."""

    monkeypatch.setattr(client.ray, "is_initialized", MagicMock(return_value=False))
    check_reachable = MagicMock(return_value=False)
    ray_init = MagicMock()
    monkeypatch.setattr(client.ray_pkg, "_check_ray_reachable", check_reachable)
    monkeypatch.setattr(client.ray, "init", ray_init)
    monkeypatch.setattr(client, "get_ray_settings", _settings)

    assert await client.init_ray_if_needed() is False
    assert await client.init_ray_if_needed() is False

    check_reachable.assert_called_once()
    ray_init.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_slow_ray_init_does_not_block_event_loop(monkeypatch):
    """Slow ray.init runs in an executor and times out without freezing asyncio."""

    monkeypatch.setenv("RAY_INIT_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setattr(client.ray, "is_initialized", MagicMock(return_value=False))
    monkeypatch.setattr(client.ray_pkg, "_check_ray_reachable", MagicMock(return_value=True))
    monkeypatch.setattr(client, "get_ray_settings", _direct_settings)

    def slow_init(**_kwargs):
        time.sleep(0.2)

    monkeypatch.setattr(client.ray, "init", MagicMock(side_effect=slow_init))

    async def ticker() -> int:
        ticks = 0
        deadline = asyncio.get_running_loop().time() + 0.12
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
            ticks += 1
        return ticks

    result, ticks = await asyncio.gather(client.init_ray_if_needed(), ticker())

    assert result is False
    assert ticks >= 3
    assert client._cooldown_remaining_seconds() > 0
