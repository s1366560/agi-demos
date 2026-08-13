"""Unit tests for the retired Python Workspace authorization fallback."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers.workspace_access import (
    require_workspace_access,
)


class _UnexpectedDb:
    async def execute(self, _statement: object) -> object:
        raise AssertionError("legacy Workspace tables must not be queried")


@pytest.mark.unit
@pytest.mark.parametrize("require_editor", [False, True])
async def test_python_workspace_access_fallback_fails_closed(
    require_editor: bool,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_workspace_access(
            _UnexpectedDb(),  # type: ignore[arg-type]
            SimpleNamespace(id="user-1", is_superuser=True),  # type: ignore[arg-type]
            "tenant-1",
            "project-1",
            "workspace-1",
            require_editor=require_editor,
        )

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc_info.value.detail["code"] == "WORKSPACE_CORE_UNAVAILABLE"
