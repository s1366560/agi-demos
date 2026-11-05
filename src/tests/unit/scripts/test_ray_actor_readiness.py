"""Probe the declared health RPC without creating cluster or business resources."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "docker/ray/check-actor-ready.py"


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("ray_readiness_probe", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = {"running": True, "listening": True, "redis_connected": True, "ready": True}
    actor = SimpleNamespace(health=SimpleNamespace(remote=Mock(return_value="health-ref")))
    client = SimpleNamespace(
        init=Mock(),
        get_actor=Mock(return_value=actor),
        get=Mock(return_value=result),
        shutdown=Mock(),
    )
    monkeypatch.setattr(module, "ray", client)
    return module, client, actor


def test_probe_calls_only_existing_actor_health(probe) -> None:
    module, client, actor = probe
    assert module.check_actor("auto", "memstack", "hitl-router", 3.0)["ready"] is True
    client.init.assert_called_once_with(
        address="auto",
        namespace="memstack",
        ignore_reinit_error=True,
        log_to_driver=False,
        configure_logging=False,
    )
    client.get_actor.assert_called_once_with("hitl-router", namespace="memstack")
    actor.health.remote.assert_called_once_with()
    client.get.assert_called_once_with("health-ref", timeout=3.0)
    client.shutdown.assert_called_once_with()


@pytest.mark.parametrize("address", ["", " ", "local", " LOCAL "])
def test_probe_cannot_create_a_local_cluster(probe, address: str) -> None:
    module, client, _ = probe
    with pytest.raises(ValueError):
        module.check_actor(address, "memstack", "hitl-router", 3.0)
    client.init.assert_not_called()
    client.get_actor.assert_not_called()


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {"ready": True},
        {"running": True, "listening": False, "redis_connected": True, "ready": True},
        {"running": 1, "listening": True, "redis_connected": True, "ready": True},
    ],
)
def test_probe_rejects_incomplete_or_inconsistent_health(probe, result) -> None:
    module, client, _ = probe
    client.get.return_value = result
    with pytest.raises(ValueError):
        module.check_actor("auto", "memstack", "hitl-router", 3.0)
    client.shutdown.assert_called_once_with()


@pytest.mark.parametrize("ready", [True, False])
def test_probe_cli_uses_actual_health_for_exit_status(
    probe, ready: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module, client, _ = probe
    client.get.return_value = {
        "running": ready,
        "listening": ready,
        "redis_connected": ready,
        "ready": ready,
    }
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--address", "auto"])
    assert module.main() == (0 if ready else 1)
    assert json.loads(capsys.readouterr().out)["ready"] is ready


def test_probe_missing_actor_does_not_leak_transport_error(
    probe, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module, client, _ = probe
    client.get_actor.side_effect = ValueError("neutral credential must not escape")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--address", "auto"])
    assert module.main() == 1
    output = capsys.readouterr().out
    assert json.loads(output) == {"ready": False, "error": "ray_actor_not_ready"}
    assert "credential" not in output
    client.get.assert_not_called()
    client.shutdown.assert_called_once_with()


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf"])
def test_probe_rejects_unbounded_timeout_before_connecting(
    probe, timeout: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, client, _ = probe
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--timeout", timeout])
    with pytest.raises(SystemExit, match="2"):
        module.main()
    client.init.assert_not_called()
