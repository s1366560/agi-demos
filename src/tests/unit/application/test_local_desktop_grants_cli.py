"""Bootstrap transport uses scoped HTTP issuance and private output, never user tokens."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

_SCRIPT = Path(__file__).resolve().parents[4] / "scripts/bootstrap-local-desktop-grants.py"


def _module():
    spec = importlib.util.spec_from_file_location("desktop_grant_bootstrap_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
@pytest.mark.parametrize("fail_second", [False, True])
async def test_cli_issues_only_desktop_grants_and_retires_bootstrap(
    tmp_path, monkeypatch, capsys, fail_second: bool
) -> None:
    module = _module()
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(module, "async_session_factory", lambda: session)
    identity = SimpleNamespace(user_id="bootstrap-user", bootstrap_id="bootstrap-run")
    identity.email = "bootstrap@localhost.invalid"
    use_case = AsyncMock()
    use_case.execute.return_value = identity
    monkeypatch.setattr(module, "BootstrapLocalPlatformAdministrator", lambda **_: use_case)
    issued = []
    revoked = []
    distribution_grants = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/token":
            return httpx.Response(200, json={"access_token": "test-user-session"})
        if request.method == "POST":
            payload = json.loads(request.content)
            plane = payload["data_plane_id"]
            if fail_second and issued:
                return httpx.Response(503)
            issued.append(plane)
            assert request.headers["Authorization"] == "Bearer test-user-session"
            return httpx.Response(
                201,
                json={
                    "credential_id": plane,
                    "data_plane_id": plane,
                    "secret": "test-private-grant-" + plane,
                    "created_by_user_id": identity.user_id,
                    "expires_at": payload["expires_at"],
                },
            )
        if request.method == "DELETE":
            revoked.append(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(200, json={})
        distribution_grants.append(request.headers["Authorization"])
        return httpx.Response(200, json={"descriptor": {}, "snapshot": {}, "envelope": {}})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(handler)),
    )
    output = tmp_path / "desktop.env"
    metadata = tmp_path / "metadata.json"
    if fail_second:
        with pytest.raises(RuntimeError, match="HTTP 503"):
            await module.provision("http://localhost:8000", output, metadata)
        assert revoked == ["desktop-sidecar-v2"]
        assert not output.exists()
    else:
        await module.provision("http://localhost:8000", output, metadata)
        assert issued == ["desktop-sidecar-v2", "desktop-renderer-v2"]
        assert output.stat().st_mode & 0o777 == 0o600
        assert metadata.stat().st_mode & 0o777 == 0o600
        assert "test-user-session" not in output.read_text()
        assert output.read_text().count("_ACK_PARTICIPATION_V2=true") == 2
        assert "test-private-grant" not in metadata.read_text()
        assert all(value.startswith("Bearer test-private-grant-") for value in distribution_grants)
        assert not revoked
    use_case.deactivate.assert_awaited_once_with(identity)
    assert "test-private-grant" not in capsys.readouterr().out


@pytest.mark.unit
async def test_cli_refuses_to_overwrite_private_output(tmp_path) -> None:
    module = _module()
    output = tmp_path / "existing.env"
    output.write_text("existing")
    with pytest.raises(ValueError, match="must not already exist"):
        await module.provision("http://localhost:8000", output, tmp_path / "metadata.json")
    assert output.read_text() == "existing"
