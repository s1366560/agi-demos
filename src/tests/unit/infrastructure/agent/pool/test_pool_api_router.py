from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status

from src.infrastructure.agent.pool.api import router


class _FailingInstance:
    async def pause(self) -> None:
        raise RuntimeError("secret pause backend reason")


@pytest.mark.unit
async def test_get_instance_sanitizes_missing_instance_key() -> None:
    manager = SimpleNamespace(_instances={})

    with pytest.raises(HTTPException) as exc_info:
        await router._get_instance("tenant:project:secret-instance", manager=manager)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Instance not found"
    assert "secret-instance" not in exc_info.value.detail


@pytest.mark.unit
async def test_pause_instance_sanitizes_backend_error() -> None:
    manager = SimpleNamespace(_instances={"tenant:project:secret-instance": _FailingInstance()})

    with pytest.raises(HTTPException) as exc_info:
        await router._pause_instance("tenant:project:secret-instance", manager=manager)

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to pause instance"
    assert "secret pause backend reason" not in exc_info.value.detail


@pytest.mark.unit
async def test_set_project_tier_sanitizes_invalid_tier() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await router._set_project_tier(
            project_id="project-1",
            request=router.SetTierRequest(tier="secret-tier"),
            tenant_id="tenant-1",
            manager=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid project tier"
    assert "secret-tier" not in exc_info.value.detail
