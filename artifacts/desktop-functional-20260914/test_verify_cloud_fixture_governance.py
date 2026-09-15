"""Isolated governance script failure tests: no database or network access."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

SCRIPT = Path(__file__).with_name("verify_cloud_fixture_governance.py")


@pytest.mark.parametrize(
    "failure", ["commit", "revoke", "cleanup", "manifest", "success", "dryrun"]
)
async def test_governance_cleanup_and_exact_target(monkeypatch, tmp_path, failure):
    spec = importlib.util.spec_from_file_location("governance_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = json.loads(
        (SCRIPT.parent / "marketplace-wasm-fixture/install-request.json").read_text()
    )
    target = tmp_path / "marketplace-wasm-fixture"
    target.mkdir()
    (target / "install-request.json").write_text(json.dumps(fixture))
    module.__file__ = str(tmp_path / SCRIPT.name)

    class Session:
        def __init__(self, initial):
            self.initial = initial

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def commit(self):
            if self.initial and failure == "commit":
                raise ConnectionError("SECRET commit error")

        async def rollback(self):
            pass

    sessions = []

    def session_factory():
        session = Session(not sessions)
        sessions.append(session)
        return session

    identity = SimpleNamespace(user_id="qa-test-actor", email="qa@localhost.invalid")
    bootstrap = SimpleNamespace(execute=AsyncMock(return_value=identity), deactivate=AsyncMock())
    if failure == "cleanup":
        bootstrap.deactivate.side_effect = RuntimeError("SECRET cleanup error")
    monkeypatch.setattr(module, "async_session_factory", session_factory)
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(environment="development", postgres_host="localhost"),
    )
    monkeypatch.setattr(module, "BootstrapLocalPlatformAdministrator", lambda **kwargs: bootstrap)
    monkeypatch.setattr(module, "SqlLocalPlatformAdministratorRepository", lambda session: None)
    requests = []
    entry = dict(
        plugin_id=fixture["plugin_id"],
        version=fixture["version"],
        publisher=fixture["publisher"],
        artifact_digest=fixture["artifact_sha256"],
        artifact_registry=fixture["artifact"]["registry"],
        artifact_repository=fixture["artifact"]["repository"],
        oci_manifest_digest=fixture["artifact"]["manifest_sha256"],
        manifest=fixture["manifest"],
        revoked=True,
        install_status="uninstalled",
    )
    if failure == "manifest":
        entry["manifest"] = {"different": True}

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "SECRET"})
        if request.method == "GET":
            return httpx.Response(200, json={"versions": [entry]})
        if failure == "revoke":
            return httpx.Response(503, json={"detail": "SECRET"})
        return httpx.Response(200, json={"plugin_id": fixture["plugin_id"]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(respond)),
    )
    if failure in {"success", "dryrun"}:
        await module.run(failure != "dryrun")
    else:
        with pytest.raises((ConnectionError, RuntimeError, ValueError, httpx.HTTPStatusError)):
            await module.run(True)
    if failure == "dryrun":
        assert not sessions and not requests
        bootstrap.execute.assert_not_awaited()
        return
    bootstrap.deactivate.assert_awaited_once_with(identity)
    assert len(sessions) == 2
    report_text = (tmp_path / "cloud-fixture-governance-result.json").read_text()
    report = json.loads(report_text)
    assert "SECRET" not in report_text
    assert report["actor_id"] == identity.user_id
    assert report["temporary_identity_deactivated"] == (failure != "cleanup")
    if failure == "cleanup":
        assert report["cleanup_error_type"] == "RuntimeError"
    mutations = [r for r in requests if r.method == "POST" and not r.url.path.endswith("/token")]
    assert all(
        r.url.path.startswith("/api/v1/plugin-marketplace/packages/qa-marketplace-marker-bundle/")
        for r in mutations
    )
    if failure in {"commit", "manifest"}:
        assert not mutations
    if failure == "revoke":
        assert len(mutations) == 1 and mutations[0].url.path.endswith("/revoke")
