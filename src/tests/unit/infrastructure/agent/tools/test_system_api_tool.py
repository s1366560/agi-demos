"""Tests for the system_api bridge tool."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.system_api import make_system_api_tool, system_api_tool


def _make_ctx(**overrides: Any) -> ToolContext:
    defaults: dict[str, Any] = {
        "session_id": "session-1",
        "message_id": "message-1",
        "call_id": "call-1",
        "agent_name": "react-agent",
        "conversation_id": "conv-1",
        "project_id": "project-1",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


def _openapi_schema() -> dict[str, Any]:
    return {
        "paths": {
            "/api/v1/projects/{project_id}": {
                "get": {
                    "operationId": "get_project_api_v1_projects__project_id__get",
                    "summary": "Get project",
                    "tags": ["projects"],
                    "parameters": [
                        {
                            "name": "project_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                },
                "patch": {
                    "operationId": "update_project_api_v1_projects__project_id__patch",
                    "summary": "Update project",
                    "tags": ["projects"],
                    "requestBody": {"content": {"application/json": {}}},
                },
            },
            "/api/v1/tasks": {
                "get": {
                    "operationId": "list_tasks_api_v1_tasks_get",
                    "summary": "List tasks",
                    "tags": ["tasks"],
                },
            },
            "/health": {
                "get": {
                    "operationId": "health_get",
                    "summary": "Health",
                    "tags": ["system"],
                },
            },
        }
    }


@pytest.fixture(autouse=True)
def _clear_openapi_cache() -> None:
    import src.infrastructure.agent.tools.system_api as module

    if hasattr(module._get_openapi_schema, "cache_clear"):
        module._get_openapi_schema.cache_clear()


@pytest.mark.unit
class TestSystemApiTool:
    async def test_bound_runtimes_are_isolated_between_interleaved_requests(self) -> None:
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        calls: list[tuple[str, str]] = []

        def _schema(path: str) -> dict[str, Any]:
            return {
                "paths": {
                    path: {
                        "get": {
                            "operationId": "shared_operation",
                            "summary": "Shared operation",
                        }
                    }
                }
            }

        class _FakeResponse:
            status_code = 200
            content = b"{}"

            def json(self) -> dict[str, bool]:
                return {"ok": True}

        def _client_factory(label: str, *, wait: bool) -> type:
            class _FakeAsyncClient:
                def __init__(self, **_kwargs: Any) -> None:
                    return None

                async def __aenter__(self) -> _FakeAsyncClient:
                    return self

                async def __aexit__(self, *_args: object) -> None:
                    return None

                async def request(self, _method: str, url: str, **_kwargs: Any) -> _FakeResponse:
                    calls.append((label, url))
                    if wait:
                        first_entered.set()
                        await release_first.wait()
                    else:
                        await first_entered.wait()
                        release_first.set()
                    return _FakeResponse()

            return _FakeAsyncClient

        first_tool = make_system_api_tool(
            openapi_schema_provider=lambda: _schema("/api/v1/generation-a"),
            base_url="http://generation-a.local",
            client_factory=_client_factory("generation-a", wait=True),
        )
        second_tool = make_system_api_tool(
            openapi_schema_provider=lambda: _schema("/api/v1/generation-b"),
            base_url="http://generation-b.local",
            client_factory=_client_factory("generation-b", wait=False),
        )

        first_task = asyncio.create_task(
            first_tool.execute(
                _make_ctx(api_auth_token="test-token-generation-a"),
                action="request",
                operation_id="shared_operation",
            )
        )
        await first_entered.wait()
        second_result = await second_tool.execute(
            _make_ctx(api_auth_token="test-token-generation-b"),
            action="request",
            operation_id="shared_operation",
        )
        first_result = await first_task

        assert first_result.is_error is False
        assert second_result.is_error is False
        assert calls == [
            ("generation-a", "http://generation-a.local/api/v1/generation-a"),
            ("generation-b", "http://generation-b.local/api/v1/generation-b"),
        ]

    async def test_tool_metadata(self) -> None:
        assert system_api_tool.name == "system_api"
        assert system_api_tool.permission == "system_api"
        assert system_api_tool.category == "system"
        assert system_api_tool.parameters["required"] == ["action"]
        token = "ms_sk_" + ("a" * 64)
        assert token not in repr(_make_ctx(api_auth_token=token))

    async def test_list_filters_openapi_operations(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.infrastructure.agent.tools.system_api as module

        monkeypatch.setattr(module, "_get_openapi_schema", _openapi_schema)

        result = await system_api_tool.execute(
            _make_ctx(),
            action="list",
            tag="projects",
            search="update",
        )
        payload = json.loads(result.output)

        assert result.is_error is False
        assert payload["total_operations"] == 3
        assert payload["returned_operations"] == 1
        assert payload["operations"][0]["operation_id"] == (
            "update_project_api_v1_projects__project_id__patch"
        )
        assert payload["operations"][0]["has_request_body"] is True

    async def test_describe_returns_operation_contract(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.infrastructure.agent.tools.system_api as module

        monkeypatch.setattr(module, "_get_openapi_schema", _openapi_schema)

        result = await system_api_tool.execute(
            _make_ctx(),
            action="describe",
            operation_id="get_project_api_v1_projects__project_id__get",
        )
        payload = json.loads(result.output)

        assert result.is_error is False
        assert payload["method"] == "GET"
        assert payload["path_template"] == "/api/v1/projects/{project_id}"
        assert payload["parameters"][0]["name"] == "project_id"

    async def test_request_rejects_missing_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.infrastructure.agent.tools.system_api as module

        monkeypatch.setattr(module, "_get_openapi_schema", _openapi_schema)
        monkeypatch.delenv("MEMSTACK_AGENT_API_KEY", raising=False)
        monkeypatch.delenv("MEMSTACK_API_KEY", raising=False)

        result = await system_api_tool.execute(
            _make_ctx(),
            action="request",
            operation_id="get_project_api_v1_projects__project_id__get",
            path_params={"project_id": "project-1"},
        )
        payload = json.loads(result.output)

        assert result.is_error is True
        assert payload["error"] == "api_auth_unavailable"

    async def test_request_calls_operation_and_redacts_secret(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import src.infrastructure.agent.tools.system_api as module

        token = "ms_sk_" + ("a" * 64)
        calls: list[dict[str, Any]] = []

        class _FakeResponse:
            status_code = 200
            content = b"{}"

            def json(self) -> dict[str, Any]:
                return {
                    "ok": True,
                    "echo": f"Bearer {token}",
                    "Authorization": f"Bearer {token}",
                }

        class _FakeAsyncClient:
            def __init__(self, **kwargs: Any) -> None:
                calls.append({"client_kwargs": kwargs})

            async def __aenter__(self) -> _FakeAsyncClient:
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def request(self, *args: Any, **kwargs: Any) -> _FakeResponse:
                calls.append({"args": args, "kwargs": kwargs})
                return _FakeResponse()

        monkeypatch.setattr(module, "_get_openapi_schema", _openapi_schema)
        monkeypatch.setattr(module, "_base_url", lambda: "http://memstack.local/api/v1")
        monkeypatch.setattr(module.httpx, "AsyncClient", _FakeAsyncClient)

        result = await system_api_tool.execute(
            _make_ctx(api_auth_token=token),
            action="request",
            operation_id="update_project_api_v1_projects__project_id__patch",
            path_params={"project_id": "project 1"},
            query={"include": "stats"},
            body={"name": "Updated"},
            timeout_seconds=2,
        )
        payload = json.loads(result.output)
        request_call = calls[1]

        assert result.is_error is False
        assert request_call["args"] == (
            "PATCH",
            "http://memstack.local/api/v1/projects/project%201",
        )
        assert request_call["kwargs"]["headers"]["Authorization"] == f"Bearer {token}"
        assert request_call["kwargs"]["params"] == {"include": "stats"}
        assert request_call["kwargs"]["json"] == {"name": "Updated"}
        assert token not in result.output
        assert payload["response"]["Authorization"] == "[REDACTED]"
        assert payload["response"]["echo"] == "Bearer [REDACTED]"

    async def test_registration_adds_tool(self) -> None:
        from src.infrastructure.agent.state.agent_worker_state import _add_system_api_tool

        tools: dict[str, Any] = {}
        _add_system_api_tool(tools, tenant_id="tenant-1", project_id="project-1")

        assert tools["system_api"].name == "system_api"

    async def test_registration_uses_bound_factory(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.infrastructure.agent.state import agent_worker_state

        marker = object()
        captured: dict[str, object] = {}

        def _make_system_api_tool(**kwargs: object) -> object:
            captured.update(kwargs)
            return marker

        monkeypatch.setattr(
            "src.infrastructure.agent.tools.system_api.make_system_api_tool",
            _make_system_api_tool,
            raising=False,
        )

        tools: dict[str, Any] = {}
        agent_worker_state._add_system_api_tool(
            tools,
            tenant_id="tenant-1",
            project_id="project-1",
        )

        assert tools == {"system_api": marker}
        assert captured == {}
