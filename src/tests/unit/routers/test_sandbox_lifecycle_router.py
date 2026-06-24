"""Unit tests for sandbox lifecycle route hardening."""

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers.sandbox import (
    lifecycle as lifecycle_router,
    utils as sandbox_utils,
)
from src.infrastructure.adapters.primary.web.routers.sandbox.schemas import CreateSandboxRequest
from src.infrastructure.adapters.primary.web.routers.sandbox.utils import assert_caller_owns_sandbox


async def _allow_project_access(**_kwargs: Any) -> None:
    return None


def _sandbox_info() -> SimpleNamespace:
    return SimpleNamespace(
        sandbox_id="sandbox-secret",
        status="running",
        endpoint="http://sandbox.local",
        websocket_url="ws://sandbox.local",
        created_at=None,
        mcp_port=8765,
        desktop_port=None,
        terminal_port=None,
        desktop_url=None,
        terminal_url=None,
    )


@pytest.mark.unit
def test_get_event_publisher_error_log_omits_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingContainer:
        def sandbox_event_publisher(self) -> object:
            raise RuntimeError("event publisher secret")

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(container=FailingContainer()))
    )
    monkeypatch.setattr(sandbox_utils, "_event_publisher", None)
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.sandbox.utils",
    )

    result = sandbox_utils.get_event_publisher(request)

    assert result is None
    assert sandbox_utils._event_publisher is None
    assert "Could not create event publisher" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "event publisher secret" not in caplog.text


@pytest.mark.unit
async def test_ensure_sandbox_sync_error_log_omits_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingAdapter:
        async def sync_from_docker(self) -> int:
            raise RuntimeError("docker sync secret")

    monkeypatch.setattr(sandbox_utils, "_sandbox_adapter", FailingAdapter())
    monkeypatch.setattr(sandbox_utils, "_worker_id", 123)
    monkeypatch.setattr(sandbox_utils, "_sync_pending", True)
    monkeypatch.setattr(sandbox_utils, "_get_worker_id", lambda: 123)
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.sandbox.utils",
    )

    await sandbox_utils.ensure_sandbox_sync()

    assert sandbox_utils._sync_pending is False
    assert "API Server: Failed to sync sandboxes from Docker" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "docker sync secret" not in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_sandbox_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingLifecycleService:
        async def get_or_create_sandbox(self, project_id: str, tenant_id: str) -> Any:
            raise RuntimeError(f"internal docker secret for {project_id}:{tenant_id}")

    class FakeDIContainer:
        def project_sandbox_lifecycle_service(self) -> FailingLifecycleService:
            return FailingLifecycleService()

    import src.configuration.di_container as di_container

    monkeypatch.setattr(lifecycle_router, "assert_caller_owns_project", _allow_project_access)
    monkeypatch.setattr(di_container, "DIContainer", FakeDIContainer)

    with pytest.raises(HTTPException) as exc_info:
        await lifecycle_router.create_sandbox(
            request=CreateSandboxRequest(project_path="/tmp/memstack_project-1"),
            current_user=SimpleNamespace(id="user-1", is_superuser=True),
            tenant_id="tenant-secret",
            adapter=SimpleNamespace(),
            event_publisher=None,
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to create sandbox"
    assert "internal" not in exc_info.value.detail
    assert "tenant-secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_create_sandbox_mcp_connect_log_omits_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class LifecycleService:
        async def get_or_create_sandbox(self, **_kwargs: Any) -> Any:
            return _sandbox_info()

    class FakeDIContainer:
        def project_sandbox_lifecycle_service(self) -> LifecycleService:
            return LifecycleService()

    class Adapter:
        async def connect_mcp(self, _sandbox_id: str) -> None:
            raise RuntimeError("mcp connect secret")

    import src.configuration.di_container as di_container

    monkeypatch.setattr(lifecycle_router, "assert_caller_owns_project", _allow_project_access)
    monkeypatch.setattr(di_container, "DIContainer", FakeDIContainer)
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.sandbox.lifecycle",
    )

    response = await lifecycle_router.create_sandbox(
        request=CreateSandboxRequest(project_path="/tmp/memstack_project-1"),
        current_user=SimpleNamespace(id="user-1", is_superuser=True),
        tenant_id="tenant-secret",
        adapter=Adapter(),
        event_publisher=None,
        db=SimpleNamespace(),
    )

    assert response.id == "sandbox-secret"
    assert response.tools == []
    assert "Could not connect MCP" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "mcp connect secret" not in caplog.text
    assert "sandbox-secret" not in caplog.text


@pytest.mark.unit
async def test_create_sandbox_tool_registration_log_omits_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class LifecycleService:
        async def get_or_create_sandbox(self, **_kwargs: Any) -> Any:
            return _sandbox_info()

    class FailingRegistry:
        async def register_sandbox_tools(self, **_kwargs: Any) -> list[Any]:
            raise RuntimeError("tool registry secret")

    class FakeDIContainer:
        def project_sandbox_lifecycle_service(self) -> LifecycleService:
            return LifecycleService()

        def sandbox_tool_registry(self) -> FailingRegistry:
            return FailingRegistry()

    class Adapter:
        async def connect_mcp(self, _sandbox_id: str) -> None:
            return None

        async def list_tools(self, _sandbox_id: str) -> list[dict[str, str]]:
            return [{"name": "read"}]

    import src.configuration.di_container as di_container

    monkeypatch.setattr(lifecycle_router, "assert_caller_owns_project", _allow_project_access)
    monkeypatch.setattr(di_container, "DIContainer", FakeDIContainer)
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.sandbox.lifecycle",
    )

    response = await lifecycle_router.create_sandbox(
        request=CreateSandboxRequest(project_path="/tmp/memstack_project-1"),
        current_user=SimpleNamespace(id="user-1", is_superuser=True),
        tenant_id="tenant-secret",
        adapter=Adapter(),
        event_publisher=None,
        db=SimpleNamespace(),
    )

    assert response.tools == ["read"]
    assert "[SandboxAPI] Failed to register tools to Agent" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "tool registry secret" not in caplog.text
    assert "sandbox-secret" not in caplog.text


@pytest.mark.unit
async def test_create_sandbox_publish_error_log_omits_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class LifecycleService:
        async def get_or_create_sandbox(self, **_kwargs: Any) -> Any:
            return _sandbox_info()

    class FakeDIContainer:
        def project_sandbox_lifecycle_service(self) -> LifecycleService:
            return LifecycleService()

    class Adapter:
        async def connect_mcp(self, _sandbox_id: str) -> None:
            return None

        async def list_tools(self, _sandbox_id: str) -> list[dict[str, str]]:
            return []

    class FailingEventPublisher:
        async def publish_sandbox_created(self, **_kwargs: Any) -> None:
            raise RuntimeError("sandbox created secret")

    import src.configuration.di_container as di_container

    monkeypatch.setattr(lifecycle_router, "assert_caller_owns_project", _allow_project_access)
    monkeypatch.setattr(di_container, "DIContainer", FakeDIContainer)
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.sandbox.lifecycle",
    )

    response = await lifecycle_router.create_sandbox(
        request=CreateSandboxRequest(project_path="/tmp/memstack_project-1"),
        current_user=SimpleNamespace(id="user-1", is_superuser=True),
        tenant_id="tenant-secret",
        adapter=Adapter(),
        event_publisher=FailingEventPublisher(),
        db=SimpleNamespace(),
    )

    assert response.id == "sandbox-secret"
    assert "Failed to publish sandbox_created event" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "sandbox created secret" not in caplog.text
    assert "sandbox-secret" not in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_sandboxes_invalid_status_is_sanitized() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await lifecycle_router.list_sandboxes(
            status="secret-status",
            current_user=SimpleNamespace(id="user-1", is_superuser=True),
            adapter=SimpleNamespace(),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid sandbox status"
    assert "secret-status" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_terminate_sandbox_missing_after_authorization_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_sandbox_access(**_kwargs: Any) -> tuple[SimpleNamespace, str]:
        return SimpleNamespace(id="sandbox-secret"), "project-1"

    class Adapter:
        async def terminate_sandbox(self, _sandbox_id: str) -> bool:
            return False

    monkeypatch.setattr(lifecycle_router, "assert_caller_owns_sandbox", allow_sandbox_access)

    with pytest.raises(HTTPException) as exc_info:
        await lifecycle_router.terminate_sandbox(
            sandbox_id="sandbox-secret",
            current_user=SimpleNamespace(id="user-1", is_superuser=True),
            adapter=Adapter(),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Sandbox not found"
    assert "sandbox-secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_terminate_sandbox_tool_unregister_log_omits_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def allow_sandbox_access(**_kwargs: Any) -> tuple[SimpleNamespace, str]:
        return SimpleNamespace(id="sandbox-secret"), "project-1"

    class FailingRegistry:
        async def unregister_sandbox_tools(self, _sandbox_id: str) -> bool:
            raise RuntimeError("tool unregister secret")

    class FakeDIContainer:
        def sandbox_tool_registry(self) -> FailingRegistry:
            return FailingRegistry()

    class Adapter:
        async def terminate_sandbox(self, _sandbox_id: str) -> bool:
            return True

    import src.configuration.di_container as di_container

    monkeypatch.setattr(lifecycle_router, "assert_caller_owns_sandbox", allow_sandbox_access)
    monkeypatch.setattr(di_container, "DIContainer", FakeDIContainer)
    caplog.set_level(
        logging.WARNING,
        logger="src.infrastructure.adapters.primary.web.routers.sandbox.lifecycle",
    )

    result = await lifecycle_router.terminate_sandbox(
        sandbox_id="sandbox-secret",
        current_user=SimpleNamespace(id="user-1", is_superuser=True),
        adapter=Adapter(),
        db=SimpleNamespace(),
    )

    assert result == {"status": "terminated", "sandbox_id": "sandbox-secret"}
    assert "[SandboxAPI] Failed to unregister tools" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "tool unregister secret" not in caplog.text
    assert "sandbox-secret" not in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_assert_caller_owns_sandbox_missing_sandbox_is_sanitized() -> None:
    adapter = SimpleNamespace(get_sandbox=AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as exc_info:
        await assert_caller_owns_sandbox(
            sandbox_id="sandbox-secret",
            user=SimpleNamespace(id="user-1", is_superuser=True),
            db=SimpleNamespace(),
            adapter=adapter,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Sandbox not found"
    assert "sandbox-secret" not in exc_info.value.detail
