"""Unit tests for sandbox lifecycle route hardening."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers.sandbox import lifecycle as lifecycle_router
from src.infrastructure.adapters.primary.web.routers.sandbox.schemas import CreateSandboxRequest


async def _allow_project_access(**_kwargs: Any) -> None:
    return None


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
