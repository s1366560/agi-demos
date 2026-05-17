from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers import subagents as router


class _EmptyFilesystemLoader:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def load_all(self) -> SimpleNamespace:
        return SimpleNamespace(subagents=[])


class _FilesystemLoaderWithAgent:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def load_all(self) -> SimpleNamespace:
        return SimpleNamespace(
            subagents=[
                SimpleNamespace(
                    subagent=SimpleNamespace(name="secret-subagent"),
                    file_info=SimpleNamespace(file_path="/tmp/secret-subagent.md"),
                )
            ]
        )


class _ExistingSubagentRepository:
    def __init__(self, subagent: object | None = None) -> None:
        self.subagent = subagent or SimpleNamespace(
            id="subagent-1",
            tenant_id="tenant-1",
            name="current-subagent",
        )

    async def get_by_name(self, *_args: object) -> object:
        return SimpleNamespace(id="existing-subagent")

    async def get_by_id(self, *_args: object) -> object:
        return self.subagent


class _EmptySubagentRepository:
    async def get_by_name(self, *_args: object) -> None:
        return None


class _ExistingTemplateRepository:
    async def get_by_name(self, *_args: object) -> object:
        return SimpleNamespace(id="existing-template")

    async def get_by_id(self, *_args: object) -> dict[str, object]:
        return {
            "id": "template-1",
            "tenant_id": "tenant-1",
            "name": "secret-template-subagent",
            "system_prompt": "Prompt",
        }


class _Container:
    def __init__(
        self,
        subagent_repo: object | None = None,
        template_repo: object | None = None,
    ) -> None:
        self._subagent_repo = subagent_repo or _ExistingSubagentRepository()
        self._template_repo = template_repo or _ExistingTemplateRepository()

    def subagent_repository(self) -> object:
        return self._subagent_repo

    def subagent_template_repository(self) -> object:
        return self._template_repo


def _patch_container(monkeypatch: pytest.MonkeyPatch, container: _Container) -> None:
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: container)


@pytest.mark.unit
async def test_import_filesystem_subagent_sanitizes_missing_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.infrastructure.agent.subagent.filesystem_loader.FileSystemSubAgentLoader",
        _EmptyFilesystemLoader,
    )

    with pytest.raises(HTTPException) as exc_info:
        await router.import_filesystem_subagent(
            request=SimpleNamespace(),
            name="secret-subagent",
            project_id=None,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Filesystem SubAgent not found"
    assert "secret-subagent" not in exc_info.value.detail


@pytest.mark.unit
async def test_create_subagent_sanitizes_duplicate_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_container(monkeypatch, _Container())

    with pytest.raises(HTTPException) as exc_info:
        await router.create_subagent(
            request=SimpleNamespace(),
            data=router.SubAgentCreate(
                name="secret-subagent",
                display_name="Secret SubAgent",
                system_prompt="Prompt",
                trigger_description="Trigger",
            ),
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert exc_info.value.detail == "SubAgent already exists"
    assert "secret-subagent" not in exc_info.value.detail


@pytest.mark.unit
async def test_create_subagent_value_error_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_container(monkeypatch, _Container(subagent_repo=_EmptySubagentRepository()))

    with pytest.raises(HTTPException) as exc_info:
        await router.create_subagent(
            request=SimpleNamespace(),
            data=router.SubAgentCreate(
                name="agent-1",
                display_name="Agent 1",
                system_prompt="You are helpful.",
                trigger_description="Use for tests.",
                model="internal-model-secret",
            ),
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=AsyncMock()),
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid subagent request"
    assert "internal-model-secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_import_filesystem_subagent_sanitizes_duplicate_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.infrastructure.agent.subagent.filesystem_loader.FileSystemSubAgentLoader",
        _FilesystemLoaderWithAgent,
    )
    _patch_container(monkeypatch, _Container())

    with pytest.raises(HTTPException) as exc_info:
        await router.import_filesystem_subagent(
            request=SimpleNamespace(),
            name="secret-subagent",
            project_id=None,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert exc_info.value.detail == "SubAgent already exists"
    assert "secret-subagent" not in exc_info.value.detail


@pytest.mark.unit
async def test_create_template_sanitizes_duplicate_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_container(monkeypatch, _Container())

    with pytest.raises(HTTPException) as exc_info:
        await router.create_template(
            request=SimpleNamespace(),
            data=router.TemplateCreate(
                name="secret-template",
                version="2.1.3",
                system_prompt="Prompt",
            ),
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert exc_info.value.detail == "Template already exists"
    assert "secret-template" not in exc_info.value.detail
    assert "2.1.3" not in exc_info.value.detail


@pytest.mark.unit
async def test_install_template_sanitizes_duplicate_subagent_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_container(monkeypatch, _Container())

    with pytest.raises(HTTPException) as exc_info:
        await router.install_template(
            request=SimpleNamespace(),
            template_id="template-1",
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert exc_info.value.detail == "SubAgent already exists"
    assert "secret-template-subagent" not in exc_info.value.detail


@pytest.mark.unit
async def test_update_subagent_sanitizes_duplicate_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_container(monkeypatch, _Container())

    with pytest.raises(HTTPException) as exc_info:
        await router.update_subagent(
            request=SimpleNamespace(),
            subagent_id="subagent-1",
            data=router.SubAgentUpdate(name="secret-new-name"),
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert exc_info.value.detail == "SubAgent already exists"
    assert "secret-new-name" not in exc_info.value.detail
