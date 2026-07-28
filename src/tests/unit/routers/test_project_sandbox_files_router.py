"""Contract tests for project-scoped sandbox files and remote desktop sessions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.infrastructure.adapters.primary.web.routers import project_sandbox as router_mod


def _listing() -> dict[str, object]:
    return {
        "contract_version": 1,
        "authority": "sandbox",
        "isolation": "isolated",
        "root": "/",
        "path": "/",
        "entries": [
            {
                "path": "/README.md",
                "name": "README.md",
                "kind": "file",
                "size_bytes": 5,
                "mime_type": "text/markdown",
            }
        ],
        "cursor": None,
        "revision": "a" * 64,
    }


def _client(monkeypatch) -> tuple[TestClient, AsyncMock, AsyncMock]:
    app = FastAPI()
    app.include_router(router_mod.router)

    async def allow_access(*_args, **_kwargs) -> str:
        return "tenant-1"

    monkeypatch.setattr(router_mod, "verify_project_access", allow_access)

    async def current_user():
        return SimpleNamespace(id="user-1")

    async def db():
        yield Mock()

    service = AsyncMock()
    service.ensure_sandbox_running = AsyncMock(return_value=SimpleNamespace(sandbox_id="sandbox-1"))
    orchestrator = AsyncMock()

    app.dependency_overrides[router_mod.get_current_user] = current_user
    app.dependency_overrides[router_mod.get_db] = db
    app.dependency_overrides[router_mod.get_lifecycle_service] = lambda: service
    app.dependency_overrides[router_mod.get_orchestrator] = lambda: orchestrator
    app.dependency_overrides[router_mod.get_api_key_from_header] = lambda: "scoped-api-key"
    return TestClient(app), service, orchestrator


def test_sandbox_runtime_capabilities_are_explicit_and_do_not_claim_terminal_resume(
    monkeypatch,
) -> None:
    client, _service, _orchestrator = _client(monkeypatch)

    response = client.get("/api/v1/projects/project-1/sandbox/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "service_version": "0.1.0",
        "contract_version": 2,
        "terminal_interactive": {
            "availability": "available",
            "contract_version": 1,
            "reason_code": None,
        },
        "terminal_resume": {
            "availability": "unavailable",
            "contract_version": 2,
            "reason_code": "terminal_session_v2_registry_unavailable",
        },
        "files": {
            "availability": "available",
            "contract_version": 1,
            "reason_code": None,
        },
        "kasm_vnc": {
            "availability": "available",
            "contract_version": 1,
            "reason_code": None,
        },
    }


def test_sandbox_files_return_strict_structured_authority(monkeypatch) -> None:
    client, service, _orchestrator = _client(monkeypatch)
    service.execute_tool.return_value = {
        "content": [{"type": "text", "text": "listed"}],
        "is_error": False,
        "listing": _listing(),
    }

    response = client.get(
        "/api/v1/projects/project-1/sandbox/files",
        params={"path": "/", "limit": 20},
    )

    assert response.status_code == 200
    assert response.json() == _listing()
    service.execute_tool.assert_awaited_once_with(
        project_id="project-1",
        tool_name="platform_list_workspace_files",
        arguments={"path": "/", "limit": 20, "cursor": None},
        timeout=15.0,
    )


def test_sandbox_file_read_and_download_validate_mcp_contract(monkeypatch) -> None:
    client, service, _orchestrator = _client(monkeypatch)
    service.execute_tool.side_effect = [
        {
            "content": [{"type": "text", "text": "read"}],
            "is_error": False,
            "file": {
                "contract_version": 1,
                "authority": "sandbox",
                "isolation": "isolated",
                "path": "/README.md",
                "encoding": "utf-8",
                "content": "hello",
                "mime_type": "text/markdown",
                "size_bytes": 5,
                "revision": "b" * 64,
                "truncated": False,
            },
        },
        {
            "content": [{"type": "text", "text": "download"}],
            "is_error": False,
            "download": {
                "contract_version": 1,
                "authority": "sandbox",
                "isolation": "isolated",
                "path": "/README.md",
                "filename": "README.md",
                "mime_type": "text/markdown",
                "size_bytes": 5,
                "sha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
                "base64": "aGVsbG8=",
            },
        },
    ]

    read = client.get(
        "/api/v1/projects/project-1/sandbox/files/content",
        params={"path": "/README.md", "max_bytes": 1024},
    )
    download = client.get(
        "/api/v1/projects/project-1/sandbox/files/download",
        params={"path": "/README.md"},
    )

    assert read.status_code == 200
    assert read.json()["content"] == "hello"
    assert download.status_code == 200
    assert download.content == b"hello"
    assert download.headers["x-memstack-file-authority"] == "sandbox"
    assert download.headers["x-memstack-file-isolation"] == "isolated"


def test_sandbox_file_tool_errors_and_malformed_payloads_fail_closed(monkeypatch) -> None:
    client, service, _orchestrator = _client(monkeypatch)
    service.execute_tool.side_effect = [
        {
            "content": [{"type": "text", "text": "stale"}],
            "is_error": True,
            "reason_code": "sandbox_file_cursor_stale",
        },
        {
            "content": [],
            "is_error": False,
            "listing": {"contract_version": 1},
        },
    ]

    stale = client.get(
        "/api/v1/projects/project-1/sandbox/files",
        params={"path": "/", "cursor": f"{'a' * 64}.2"},
    )
    malformed = client.get(
        "/api/v1/projects/project-1/sandbox/files",
        params={"path": "/"},
    )

    assert stale.status_code == 409
    assert stale.json()["detail"]["reason_code"] == "sandbox_file_cursor_stale"
    assert malformed.status_code == 502
    assert malformed.json()["detail"]["reason_code"] == "sandbox_file_contract_invalid"


def test_remote_desktop_session_seeds_cookie_and_returns_fixed_proxy_descriptor(
    monkeypatch,
) -> None:
    client, service, orchestrator = _client(monkeypatch)
    orchestrator.start_desktop.return_value = SimpleNamespace(running=True)

    response = client.post(
        "/api/v1/projects/project-1/sandbox/desktop/session",
        params={"resolution": "1440x900"},
        headers={"Authorization": "Bearer scoped-api-key"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "contract_version": 1,
        "project_id": "project-1",
        "protocol": "kasmvnc-1",
        "proxy_url": "/api/v1/projects/project-1/sandbox/desktop/proxy/vnc.html",
        "auth_mode": "scoped_http_only_cookie",
    }
    set_cookie = response.headers["set-cookie"]
    assert "sandbox_proxy_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=none" in set_cookie
    assert "Secure" in set_cookie
    assert "Path=/api/v1/projects/project-1/sandbox" in set_cookie
    assert "scoped-api-key" not in response.text
    service.ensure_sandbox_running.assert_awaited_once_with(
        project_id="project-1",
        tenant_id="tenant-1",
    )
