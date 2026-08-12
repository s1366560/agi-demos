"""Workspace Core router group switch contract tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from src.configuration.workspace_core import WorkspaceCoreBackend, WorkspaceCoreSettings
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    verify_api_key_dependency,
)
from src.infrastructure.adapters.primary.web.workspace_core_routes import (
    register_workspace_core_routes,
    register_workspace_core_static_routes,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.workspace_core.client import WorkspaceCoreClient


def _workspace_routes(app: FastAPI) -> list[APIRoute]:
    module_prefix = "src.infrastructure.adapters.primary.web.routers."
    workspace_modules = {
        "blackboard",
        "cyber_genes",
        "cyber_objectives",
        "topology",
        "workspace_agent_policy",
        "workspace_autonomy",
        "workspace_chat",
        "workspace_collaboration_mutations",
        "workspace_context",
        "workspace_plans",
        "workspace_tasks",
        "workspaces",
    }
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.endpoint.__module__.removeprefix(module_prefix) in workspace_modules
    ]


def _avernet_routes(app: FastAPI) -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.endpoint.__module__
        == "src.infrastructure.adapters.primary.web.workspace_core_routes"
    ]


def _avernet_settings() -> WorkspaceCoreSettings:
    return WorkspaceCoreSettings.model_validate(
        {
            "WORKSPACE_CORE_BACKEND": "avernet",
            "WORKSPACE_CORE_BASE_URL": "http://workspace-core.test",
            "WORKSPACE_CORE_SERVICE_TOKEN": "internal-test-token",
            "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN": "provider-webhook-token",
            "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN": "provider-event-token",
            "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN": "agent-registry-token",
        }
    )


def _override_proxy_dependencies(app: FastAPI) -> None:
    async def current_user() -> SimpleNamespace:
        return SimpleNamespace(
            id="user-1",
            email="admin@memstack.ai",
            is_superuser=True,
        )

    async def db_session() -> object:
        yield object()

    async def api_key() -> SimpleNamespace:
        return SimpleNamespace(id="api-key-1", user_id="user-1")

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[verify_api_key_dependency] = api_key
    app.dependency_overrides[get_db] = db_session


@pytest.mark.unit
def test_legacy_registers_complete_workspace_route_group() -> None:
    app = FastAPI()

    register_workspace_core_static_routes(app, WorkspaceCoreBackend.LEGACY)
    register_workspace_core_routes(app, WorkspaceCoreBackend.LEGACY)

    assert len(_workspace_routes(app)) == 92


@pytest.mark.unit
def test_avernet_registers_complete_proxy_group_without_legacy_handlers() -> None:
    app = FastAPI()

    register_workspace_core_static_routes(app, WorkspaceCoreBackend.AVERNET)
    register_workspace_core_routes(app, WorkspaceCoreBackend.AVERNET)

    assert _workspace_routes(app) == []
    assert len(_avernet_routes(app)) == 92


@pytest.mark.unit
def test_avernet_openapi_contract_matches_legacy_route_group() -> None:
    legacy = FastAPI()
    avernet = FastAPI()
    register_workspace_core_static_routes(legacy, WorkspaceCoreBackend.LEGACY)
    register_workspace_core_routes(legacy, WorkspaceCoreBackend.LEGACY)
    register_workspace_core_static_routes(avernet, WorkspaceCoreBackend.AVERNET)
    register_workspace_core_routes(avernet, WorkspaceCoreBackend.AVERNET)

    assert avernet.openapi()["paths"] == legacy.openapi()["paths"]
    assert avernet.openapi()["components"] == legacy.openapi()["components"]


@pytest.mark.unit
async def test_avernet_proxy_separates_service_and_user_authorization() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/llm-providers/routing-policy"
        assert request.url.query == b"project_id=project-1&workspace_id=workspace-1"
        assert request.headers["authorization"] == "Bearer internal-test-token"
        assert request.headers["x-memstack-user-authorization"] == "Bearer user-token"
        assert request.headers["x-memstack-project-id"] == "project-1"
        assert request.headers["x-memstack-workspace-id"] == "workspace-1"
        assert request.headers["x-memstack-user-id"] == "user-1"
        assert request.headers["x-memstack-user-email"] == "admin@memstack.ai"
        assert request.headers["x-memstack-user-is-superuser"] == "true"
        return httpx.Response(
            206,
            json={"proxied": True},
            headers={"ETag": '"revision-7"'},
        )

    app = FastAPI()
    _override_proxy_dependencies(app)
    app.state.workspace_core_client = WorkspaceCoreClient(
        _avernet_settings(),
        transport=httpx.MockTransport(handler),
    )
    register_workspace_core_static_routes(app, WorkspaceCoreBackend.AVERNET)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        response = await client.get(
            "/api/v1/llm-providers/routing-policy",
            params={"project_id": "project-1", "workspace_id": "workspace-1"},
            headers={
                "Authorization": "Bearer user-token",
                "X-MemStack-User-Email": "spoofed@example.com",
            },
        )

    assert response.status_code == 206
    assert response.json() == {"proxied": True}
    assert response.headers["etag"] == '"revision-7"'


@pytest.mark.unit
async def test_avernet_proxy_fails_with_503_without_runtime_client() -> None:
    app = FastAPI()
    _override_proxy_dependencies(app)
    register_workspace_core_static_routes(app, WorkspaceCoreBackend.AVERNET)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        response = await client.get(
            "/api/v1/llm-providers/routing-policy",
            params={"project_id": "project-1", "workspace_id": "workspace-1"},
            headers={"Authorization": "Bearer user-token"},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Workspace Core is unavailable"}


@pytest.mark.unit
async def test_avernet_context_proxy_forwards_api_key_identity() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/workspace-context"
        assert request.headers["x-memstack-user-id"] == "user-1"
        assert request.headers["x-memstack-api-key-id"] == "api-key-1"
        return httpx.Response(
            200,
            json={
                "context": {
                    "tenant_id": "tenant-1",
                    "project_id": "project-1",
                    "revision": 0,
                    "updated_at": "2026-08-11T00:00:00Z",
                },
                "membership_role": "member",
            },
        )

    app = FastAPI()
    _override_proxy_dependencies(app)
    app.state.workspace_core_client = WorkspaceCoreClient(
        _avernet_settings(),
        transport=httpx.MockTransport(handler),
    )
    register_workspace_core_static_routes(app, WorkspaceCoreBackend.AVERNET)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        response = await client.get(
            "/api/v1/workspace-context",
            headers={"Authorization": "Bearer user-token"},
        )

    assert response.status_code == 200


@pytest.mark.unit
async def test_avernet_file_proxy_streams_multipart_and_download_headers() -> None:
    boundary = "workspace-core-stream-boundary"
    upload_body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="parent_path"\r\n\r\n'
        "/\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="large.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
    ).encode() + b"streamed-payload\r\n" + f"--{boundary}--\r\n".encode()
    response_body = b'{"streamed":true}'
    response_stream = _TrackingResponseStream([response_body[:8], response_body[8:]])
    upstream_chunks: list[bytes] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        async for chunk in request.stream:
            if chunk:
                upstream_chunks.append(chunk)
        assert request.url.path.endswith("/blackboard/files/upload")
        assert request.headers["authorization"] == "Bearer internal-test-token"
        assert request.headers["accept-encoding"] == "identity"
        assert request.headers["x-memstack-actor-type"] == "agent"
        assert request.headers["x-memstack-actor-id"] == "agent-stream-1"
        return httpx.Response(
            201,
            headers={
                "Content-Length": str(len(response_body)),
                "Content-Type": "application/json",
                "ETag": '"file-revision-1"',
            },
            stream=response_stream,
        )

    async def upload_chunks() -> AsyncIterator[bytes]:
        yield upload_body[:37]
        yield upload_body[37:113]
        yield upload_body[113:]

    app = FastAPI()
    _override_proxy_dependencies(app)
    app.state.workspace_core_client = WorkspaceCoreClient(
        _avernet_settings(),
        transport=_StreamingHandlerTransport(handler),
    )
    register_workspace_core_routes(app, WorkspaceCoreBackend.AVERNET)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        response = await client.post(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/blackboard/files/upload",
            content=upload_chunks(),
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Idempotency-Key": "stream-upload-1",
                "If-Match": "0",
                "X-Agent-Id": "agent-stream-1",
                "X-Agent-Label": "Stream Agent",
            },
        )

    assert response.status_code == 201
    assert response.content == response_body
    assert response.headers["content-length"] == str(len(response_body))
    assert response.headers["etag"] == '"file-revision-1"'
    assert upstream_chunks == [upload_body[:37], upload_body[37:113], upload_body[113:]]
    assert response_stream.closed is True


class _TrackingResponseStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        super().__init__()
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class _StreamingHandlerTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
    ) -> None:
        super().__init__()
        self._handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._handler(request)
