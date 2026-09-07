"""Workspace Core router group switch contract tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from src.configuration.workspace_core import WorkspaceCoreSettings
from src.infrastructure.adapters.primary.web.dependencies import (
    get_api_key_from_header,
    get_current_actor,
    get_current_user,
    verify_api_key_dependency,
)
from src.infrastructure.adapters.primary.web.routers import (
    cyber_genes,
    cyber_objectives,
    topology,
    workspace_chat,
    workspace_tasks,
    workspaces,
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


def _dependency_calls(route: APIRoute) -> list[Callable[..., object]]:
    calls: list[Callable[..., object]] = []

    def walk(dependency: object) -> None:
        for child in dependency.dependencies:
            calls.append(child.call)
            walk(child)

    walk(route.dependant)
    return calls


def _avernet_settings() -> WorkspaceCoreSettings:
    return WorkspaceCoreSettings.model_validate(
        {
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
def test_avernet_registers_complete_proxy_group_without_legacy_handlers() -> None:
    app = FastAPI()

    register_workspace_core_static_routes(app)
    register_workspace_core_routes(app)

    assert _workspace_routes(app) == []
    assert len(_avernet_routes(app)) == 95


@pytest.mark.unit
def test_avernet_proxy_routes_keep_only_platform_authentication_dependencies() -> None:
    app = FastAPI()

    register_workspace_core_static_routes(app)
    register_workspace_core_routes(app)

    routes = _avernet_routes(app)
    allowed_root_dependencies = {
        get_api_key_from_header,
        get_current_actor,
        get_current_user,
        get_db,
        verify_api_key_dependency,
    }
    dependency_calls = [call for route in routes for call in _dependency_calls(route)]
    assert get_current_user in dependency_calls
    assert get_current_actor in dependency_calls
    assert all(dependency_call in allowed_root_dependencies for dependency_call in dependency_calls)


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
    register_workspace_core_static_routes(app)

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
async def test_avernet_cyber_gene_routes_proxy_exact_contract_without_legacy_di(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, str, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append((request.method, request.url.raw_path.decode(), await request.aread()))
        assert request.headers["x-memstack-tenant-id"] == "tenant-1"
        assert request.headers["x-memstack-project-id"] == "project-1"
        assert request.headers["x-memstack-workspace-id"] == "workspace-1"
        assert request.headers["x-memstack-user-id"] == "user-1"
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.method == "POST":
            return httpx.Response(201, json={"id": "gene-1"})
        return httpx.Response(200, json={"id": "gene-1"})

    def legacy_di_trap(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("cyber-gene proxy touched the retired DI path")

    monkeypatch.setattr(cyber_genes, "get_container_with_db", legacy_di_trap, raising=False)
    app = FastAPI()
    _override_proxy_dependencies(app)
    app.state.workspace_core_client = WorkspaceCoreClient(
        _avernet_settings(),
        transport=httpx.MockTransport(handler),
    )
    register_workspace_core_routes(app)
    base = "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/genes"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        responses = [
            await client.post(base, json={"name": "Gene"}),
            await client.get(base, params={"category": "skill", "limit": 10}),
            await client.get(f"{base}/gene-1"),
            await client.patch(f"{base}/gene-1", json={"name": "Updated"}),
            await client.delete(f"{base}/gene-1"),
        ]

    assert [response.status_code for response in responses] == [201, 200, 200, 200, 204]
    assert [(method, path) for method, path, _body in observed] == [
        ("POST", base),
        ("GET", f"{base}?category=skill&limit=10"),
        ("GET", f"{base}/gene-1"),
        ("PATCH", f"{base}/gene-1"),
        ("DELETE", f"{base}/gene-1"),
    ]


@pytest.mark.unit
async def test_avernet_cyber_objective_routes_proxy_exact_contract_without_legacy_di(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, str, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append((request.method, request.url.raw_path.decode(), await request.aread()))
        assert request.headers["x-memstack-tenant-id"] == "tenant-1"
        assert request.headers["x-memstack-project-id"] == "project-1"
        assert request.headers["x-memstack-workspace-id"] == "workspace-1"
        assert request.headers["x-memstack-user-id"] == "user-1"
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.method == "POST":
            return httpx.Response(201, json={"id": "objective-1"})
        return httpx.Response(200, json={"id": "objective-1"})

    def legacy_di_trap(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("cyber-objective proxy touched the retired DI path")

    monkeypatch.setattr(cyber_objectives, "get_container_with_db", legacy_di_trap, raising=False)
    app = FastAPI()
    _override_proxy_dependencies(app)
    app.state.workspace_core_client = WorkspaceCoreClient(
        _avernet_settings(),
        transport=httpx.MockTransport(handler),
    )
    register_workspace_core_routes(app)
    base = "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/objectives"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        responses = [
            await client.post(base, json={"title": "Objective"}),
            await client.get(base, params={"obj_type": "objective", "limit": 10}),
            await client.get(f"{base}/objective-1"),
            await client.patch(f"{base}/objective-1", json={"title": "Updated"}),
            await client.delete(f"{base}/objective-1"),
            await client.post(
                f"{base}/objective-1/project-to-task",
                json={"preferred_language": "zh-CN"},
            ),
        ]

    assert [response.status_code for response in responses] == [201, 200, 200, 200, 204, 201]
    assert [(method, path) for method, path, _body in observed] == [
        ("POST", base),
        ("GET", f"{base}?obj_type=objective&limit=10"),
        ("GET", f"{base}/objective-1"),
        ("PATCH", f"{base}/objective-1"),
        ("DELETE", f"{base}/objective-1"),
        ("POST", f"{base}/objective-1/project-to-task"),
    ]


@pytest.mark.unit
async def test_avernet_topology_routes_proxy_exact_contract_without_legacy_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, str, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append((request.method, request.url.raw_path.decode(), await request.aread()))
        assert request.headers["x-memstack-workspace-id"] == "workspace-1"
        assert request.headers["x-memstack-user-id"] == "user-1"
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.method == "POST":
            return httpx.Response(201, json={"id": "topology-1"})
        return httpx.Response(200, json={"id": "topology-1"})

    def legacy_service_trap(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("topology proxy touched the retired local service")

    monkeypatch.setattr(topology, "get_topology_service", legacy_service_trap, raising=False)
    app = FastAPI()
    _override_proxy_dependencies(app)
    app.state.workspace_core_client = WorkspaceCoreClient(
        _avernet_settings(),
        transport=httpx.MockTransport(handler),
    )
    register_workspace_core_routes(app)
    base = "/api/v1/workspaces/workspace-1/topology"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        responses = [
            await client.post(f"{base}/nodes", json={"node_type": "note"}),
            await client.get(f"{base}/nodes", params={"limit": 10}),
            await client.get(f"{base}/nodes/node-1"),
            await client.patch(f"{base}/nodes/node-1", json={"title": "Updated"}),
            await client.delete(f"{base}/nodes/node-1"),
            await client.post(
                f"{base}/edges",
                json={"source_node_id": "node-1", "target_node_id": "node-2"},
            ),
            await client.get(f"{base}/edges", params={"limit": 20}),
            await client.get(f"{base}/edges/edge-1"),
            await client.patch(f"{base}/edges/edge-1", json={"label": "Updated"}),
            await client.delete(f"{base}/edges/edge-1"),
        ]

    assert [response.status_code for response in responses] == [
        201,
        200,
        200,
        200,
        204,
        201,
        200,
        200,
        200,
        204,
    ]
    assert [(method, path) for method, path, _body in observed] == [
        ("POST", f"{base}/nodes"),
        ("GET", f"{base}/nodes?limit=10"),
        ("GET", f"{base}/nodes/node-1"),
        ("PATCH", f"{base}/nodes/node-1"),
        ("DELETE", f"{base}/nodes/node-1"),
        ("POST", f"{base}/edges"),
        ("GET", f"{base}/edges?limit=20"),
        ("GET", f"{base}/edges/edge-1"),
        ("PATCH", f"{base}/edges/edge-1"),
        ("DELETE", f"{base}/edges/edge-1"),
    ]


@pytest.mark.unit
async def test_avernet_workspace_chat_routes_proxy_exact_contract_without_legacy_di(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, str, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append((request.method, request.url.raw_path.decode(), await request.aread()))
        assert request.headers["x-memstack-tenant-id"] == "tenant-1"
        assert request.headers["x-memstack-project-id"] == "project-1"
        assert request.headers["x-memstack-workspace-id"] == "workspace-1"
        assert request.headers["x-memstack-user-id"] == "user-1"
        if request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id": "message-1",
                    "workspace_id": "workspace-1",
                    "sender_id": "user-1",
                    "sender_type": "human",
                    "content": "Hello Core",
                    "mentions": ["agent-1"],
                    "parent_message_id": None,
                    "metadata": {},
                    "created_at": "2026-08-26T00:00:00Z",
                },
            )
        return httpx.Response(200, json={"items": []})

    def legacy_di_trap(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("workspace chat proxy touched the retired local DI path")

    monkeypatch.setattr(workspace_chat, "get_message_service", legacy_di_trap, raising=False)
    app = FastAPI()
    _override_proxy_dependencies(app)
    app.state.workspace_core_client = WorkspaceCoreClient(
        _avernet_settings(),
        transport=httpx.MockTransport(handler),
    )
    register_workspace_core_routes(app)
    base = "/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/messages"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        responses = [
            await client.post(
                base,
                json={"content": "Hello Core", "mentions": ["agent-1"]},
            ),
            await client.get(base, params={"limit": 25, "before": "message-9"}),
            await client.get(f"{base}/mentions/agent-1", params={"limit": 10}),
        ]

    assert [response.status_code for response in responses] == [201, 200, 200]
    assert [(method, path) for method, path, _body in observed] == [
        ("POST", base),
        ("GET", f"{base}?limit=25&before=message-9"),
        ("GET", f"{base}/mentions/agent-1?limit=10"),
    ]
    assert observed[0][2] == b'{"content":"Hello Core","mentions":["agent-1"]}'


@pytest.mark.unit
async def test_avernet_workspace_task_routes_proxy_exact_contract_without_legacy_di(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, str, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append((request.method, request.url.raw_path.decode(), await request.aread()))
        assert request.headers["x-memstack-workspace-id"] == "workspace-1"
        assert request.headers["x-memstack-user-id"] == "user-1"
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.method == "POST" and request.url.path == base:
            return httpx.Response(201, json={"id": "task-1"})
        return httpx.Response(200, json={"id": "task-1"})

    def legacy_di_trap(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("workspace task proxy touched the retired local DI path")

    monkeypatch.setattr(
        workspace_tasks,
        "_get_workspace_task_service",
        legacy_di_trap,
        raising=False,
    )
    app = FastAPI()
    _override_proxy_dependencies(app)
    app.state.workspace_core_client = WorkspaceCoreClient(
        _avernet_settings(),
        transport=httpx.MockTransport(handler),
    )
    register_workspace_core_routes(app)
    base = "/api/v1/workspaces/workspace-1/tasks"
    task = f"{base}/task-1"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        responses = [
            await client.post(base, json={"title": "Task"}),
            await client.get(
                base,
                params={"status": "todo", "limit": 10, "offset": 5},
            ),
            await client.get(task),
            await client.get(f"{task}/experience"),
            await client.get(f"{task}/execution-session"),
            await client.post(
                f"{task}/recovery-actions",
                json={"action": "retry_launch"},
            ),
            await client.patch(task, json={"title": "Updated"}),
            await client.delete(task),
            await client.post(
                f"{task}/assign-agent",
                json={"workspace_agent_id": "binding-1"},
            ),
            await client.post(f"{task}/unassign-agent"),
            await client.post(f"{task}/claim"),
            await client.post(f"{task}/start"),
            await client.post(f"{task}/block"),
            await client.post(f"{task}/complete"),
        ]

    assert [response.status_code for response in responses] == [
        201,
        200,
        200,
        200,
        200,
        200,
        200,
        204,
        200,
        200,
        200,
        200,
        200,
        200,
    ]
    assert [(method, path) for method, path, _body in observed] == [
        ("POST", base),
        ("GET", f"{base}?status=todo&limit=10&offset=5"),
        ("GET", task),
        ("GET", f"{task}/experience"),
        ("GET", f"{task}/execution-session"),
        ("POST", f"{task}/recovery-actions"),
        ("PATCH", task),
        ("DELETE", task),
        ("POST", f"{task}/assign-agent"),
        ("POST", f"{task}/unassign-agent"),
        ("POST", f"{task}/claim"),
        ("POST", f"{task}/start"),
        ("POST", f"{task}/block"),
        ("POST", f"{task}/complete"),
    ]


@pytest.mark.unit
async def test_avernet_workspace_lifecycle_routes_proxy_exact_contract_without_legacy_di(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, str, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append((request.method, request.url.raw_path.decode(), await request.aread()))
        assert request.headers["x-memstack-tenant-id"] == "tenant-1"
        assert request.headers["x-memstack-project-id"] == "project-1"
        if request.url.path != base:
            assert request.headers["x-memstack-workspace-id"] == "workspace-1"
        assert request.headers["x-memstack-user-id"] == "user-1"
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.method == "POST":
            return httpx.Response(201, json={"id": "workspace-1"})
        if request.method == "GET" and request.url.path in {base, members, agents}:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"id": "workspace-1"})

    def legacy_di_trap(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("workspace proxy touched the retired local DI path")

    monkeypatch.setattr(workspaces, "get_workspace_service", legacy_di_trap, raising=False)
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.workspace_core_routes.async_session_factory",
        lambda: _FakeMembershipSessionFactory("owner"),
    )
    app = FastAPI()
    _override_proxy_dependencies(app)
    app.state.workspace_core_client = WorkspaceCoreClient(
        _avernet_settings(),
        transport=httpx.MockTransport(handler),
    )
    register_workspace_core_routes(app)
    base = "/api/v1/tenants/tenant-1/projects/project-1/workspaces"
    workspace = f"{base}/workspace-1"
    members = f"{workspace}/members"
    agents = f"{workspace}/agents"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        responses = [
            await client.post(base, json={"name": "Workspace"}),
            await client.get(base, params={"limit": 10, "offset": 2}),
            await client.get(workspace),
            await client.get(f"{workspace}/collaboration/capabilities"),
            await client.patch(workspace, json={"name": "Updated"}),
            await client.delete(workspace),
            await client.get(members, params={"limit": 20, "offset": 3}),
            await client.post(members, json={"user_id": "user-2", "role": "editor"}),
            await client.patch(f"{members}/user-2", json={"role": "viewer"}),
            await client.delete(f"{members}/user-2"),
            await client.get(
                agents,
                params={"active_only": True, "limit": 30, "offset": 4},
            ),
            await client.post(agents, json={"agent_id": "agent-1"}),
            await client.patch(
                f"{agents}/binding-1",
                json={"display_name": "Updated"},
            ),
            await client.delete(f"{agents}/binding-1"),
        ]

    assert [response.status_code for response in responses] == [
        201,
        200,
        200,
        200,
        200,
        204,
        200,
        201,
        200,
        204,
        200,
        201,
        200,
        204,
    ]
    assert [(method, path) for method, path, _body in observed] == [
        ("POST", base),
        ("GET", f"{base}?limit=10&offset=2"),
        ("GET", workspace),
        ("GET", f"{workspace}/collaboration/capabilities"),
        ("PATCH", workspace),
        ("DELETE", workspace),
        ("GET", f"{members}?limit=20&offset=3"),
        ("POST", members),
        ("PATCH", f"{members}/user-2"),
        ("DELETE", f"{members}/user-2"),
        ("GET", f"{agents}?active_only=true&limit=30&offset=4"),
        ("POST", agents),
        ("PATCH", f"{agents}/binding-1"),
        ("DELETE", f"{agents}/binding-1"),
    ]
    assert observed[0][2] == b'{"name":"Workspace"}'


@pytest.mark.unit
async def test_avernet_proxy_fails_with_503_without_runtime_client() -> None:
    app = FastAPI()
    _override_proxy_dependencies(app)
    register_workspace_core_static_routes(app)

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
    assert response.json() == {
        "detail": {
            "code": "WORKSPACE_CORE_UNAVAILABLE",
            "reason": "workspace_core_unavailable",
            "detail": "Workspace Core is unavailable",
        }
    }


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
    register_workspace_core_static_routes(app)

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
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="parent_path"\r\n\r\n'
            "/\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="large.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode()
        + b"streamed-payload\r\n"
        + f"--{boundary}--\r\n".encode()
    )
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
    register_workspace_core_routes(app)

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


class _FakeRoleResult:
    def __init__(self, role: str | None) -> None:
        self._role = role

    def scalar_one_or_none(self) -> str | None:
        return self._role


class _FakeMembershipSession:
    def __init__(self, role: str | None) -> None:
        self._role = role

    async def execute(self, _statement: object) -> _FakeRoleResult:
        return _FakeRoleResult(self._role)


class _FakeMembershipSessionFactory:
    def __init__(self, role: str | None) -> None:
        self._role = role

    async def __aenter__(self) -> _FakeMembershipSession:
        return _FakeMembershipSession(self._role)

    async def __aexit__(self, *_args: object) -> None:
        return None


@pytest.mark.unit
async def test_avernet_proxy_vouches_project_membership_role_on_workspace_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        return httpx.Response(201, json={"id": "workspace-1"})

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.workspace_core_routes.async_session_factory",
        lambda: _FakeMembershipSessionFactory("owner"),
    )

    app = FastAPI()
    _override_proxy_dependencies(app)
    app.state.workspace_core_client = WorkspaceCoreClient(
        _avernet_settings(),
        transport=httpx.MockTransport(handler),
    )
    register_workspace_core_routes(app)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        response = await client.post(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces",
            json={"name": "Demo"},
            headers={"Authorization": "Bearer user-token"},
        )

    assert response.status_code == 201
    assert captured["x-memstack-project-membership-role"] == "owner"


@pytest.mark.unit
async def test_avernet_proxy_omits_membership_role_without_project_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        return httpx.Response(403, json={"detail": "Access denied"})

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.workspace_core_routes.async_session_factory",
        lambda: _FakeMembershipSessionFactory(None),
    )

    app = FastAPI()
    _override_proxy_dependencies(app)
    app.state.workspace_core_client = WorkspaceCoreClient(
        _avernet_settings(),
        transport=httpx.MockTransport(handler),
    )
    register_workspace_core_routes(app)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        response = await client.post(
            "/api/v1/tenants/tenant-1/projects/project-1/workspaces",
            json={"name": "Demo"},
            headers={"Authorization": "Bearer user-token"},
        )

    assert response.status_code == 403
    assert "x-memstack-project-membership-role" not in captured


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
