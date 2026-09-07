"""Unit tests for sandbox lifecycle route hardening."""

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers.sandbox import (
    lifecycle as lifecycle_router,
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


def _sandbox_authority(lifecycle_service: object) -> SimpleNamespace:
    return SimpleNamespace(
        services=SimpleNamespace(lifecycle_service=lifecycle_service),
    )


class _SandboxAuthorityContext:
    def __init__(self, lifecycle_service: object) -> None:
        self._authority = _sandbox_authority(lifecycle_service)

    async def __aenter__(self) -> SimpleNamespace:
        return self._authority

    async def __aexit__(self, *_args: object) -> None:
        return None


def _install_sandbox_authority(
    monkeypatch: pytest.MonkeyPatch,
    lifecycle_service: object,
    *,
    captured: dict[str, object] | None = None,
) -> None:
    def factory(**kwargs: object) -> _SandboxAuthorityContext:
        if captured is not None:
            captured.update(kwargs)
        return _SandboxAuthorityContext(lifecycle_service)

    monkeypatch.setattr(lifecycle_router, "sandbox_operation_authority_v2", factory)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_sandbox_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingLifecycleService:
        async def get_or_create_sandbox(self, project_id: str, tenant_id: str) -> Any:
            raise RuntimeError(f"internal docker secret for {project_id}:{tenant_id}")

    class FakeDIContainer:
        pass

    import src.configuration.di_container as di_container

    monkeypatch.setattr(lifecycle_router, "assert_caller_owns_project", _allow_project_access)
    monkeypatch.setattr(di_container, "DIContainer", FakeDIContainer)
    captured: dict[str, object] = {}
    _install_sandbox_authority(
        monkeypatch,
        FailingLifecycleService(),
        captured=captured,
    )

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
    scope = captured["scope"]
    assert scope.kind.value == "project"
    assert scope.tenant_id == "tenant-secret"
    assert scope.project_id == "project-1"


@pytest.mark.unit
async def test_create_sandbox_mcp_connect_log_omits_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class LifecycleService:
        async def get_or_create_sandbox(self, **_kwargs: Any) -> Any:
            return _sandbox_info()

    class FakeDIContainer:
        pass

    class Adapter:
        async def connect_mcp(self, _sandbox_id: str) -> None:
            raise RuntimeError("mcp connect secret")

    import src.configuration.di_container as di_container

    monkeypatch.setattr(lifecycle_router, "assert_caller_owns_project", _allow_project_access)
    monkeypatch.setattr(di_container, "DIContainer", FakeDIContainer)
    _install_sandbox_authority(monkeypatch, LifecycleService())
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

    class Adapter:
        async def connect_mcp(self, _sandbox_id: str) -> None:
            return None

        async def list_tools(self, _sandbox_id: str) -> list[dict[str, str]]:
            return [{"name": "read"}]

    monkeypatch.setattr(lifecycle_router, "assert_caller_owns_project", _allow_project_access)
    monkeypatch.setattr(
        lifecycle_router,
        "get_sandbox_tool_registry",
        lambda: FailingRegistry(),
    )
    _install_sandbox_authority(monkeypatch, LifecycleService())
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
        pass

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
    _install_sandbox_authority(monkeypatch, LifecycleService())
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

    class Adapter:
        async def terminate_sandbox(self, _sandbox_id: str) -> bool:
            return True

    monkeypatch.setattr(lifecycle_router, "assert_caller_owns_sandbox", allow_sandbox_access)
    monkeypatch.setattr(
        lifecycle_router,
        "get_sandbox_tool_registry",
        lambda: FailingRegistry(),
    )
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
