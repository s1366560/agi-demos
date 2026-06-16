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
            project_id=None,
            name="current-subagent",
        )

    async def get_by_name(self, *_args: object) -> object:
        return SimpleNamespace(id="existing-subagent")

    async def get_by_id(self, *_args: object) -> object:
        return self.subagent


class _EmptySubagentRepository:
    async def get_by_name(self, *_args: object) -> None:
        return None


class _ScalarResult:
    def __init__(
        self,
        value: object | None,
        *,
        values: list[object] | None = None,
    ) -> None:
        self.value = value
        self.values = values or []

    def scalar_one_or_none(self) -> object | None:
        return self.value

    def scalars(self) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: self.values)


class _SubagentAccessRepository:
    def __init__(
        self,
        *,
        subagent: router.SubAgent | None = None,
        subagents: list[router.SubAgent] | None = None,
        matches: list[router.SubAgent] | None = None,
    ) -> None:
        self.subagent = subagent
        self.subagents = subagents or ([] if subagent is None else [subagent])
        self.matches = matches or []
        self.delete = AsyncMock(return_value=True)
        self.update = AsyncMock(side_effect=lambda subagent: subagent)
        self.set_enabled = AsyncMock(return_value=subagent)

    async def get_by_id(self, *_args: object) -> router.SubAgent | None:
        return self.subagent

    async def get_by_name(self, *_args: object) -> None:
        return None

    async def list_by_tenant(self, *_args: object, **_kwargs: object) -> list[router.SubAgent]:
        return self.subagents

    async def count_by_tenant(self, *_args: object, **_kwargs: object) -> int:
        return len(self.subagents)

    async def find_by_keywords(self, *_args: object, **_kwargs: object) -> list[router.SubAgent]:
        return self.matches


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


def _make_subagent(
    *,
    subagent_id: str,
    name: str,
    project_id: str | None,
) -> router.SubAgent:
    subagent = router.SubAgent.create(
        tenant_id="tenant-1",
        project_id=project_id,
        name=name,
        display_name=name.replace("-", " ").title(),
        system_prompt="Prompt",
        trigger_description="Trigger",
    )
    subagent.id = subagent_id
    return subagent


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
async def test_create_subagent_rejects_inaccessible_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_container(monkeypatch, _Container(subagent_repo=_EmptySubagentRepository()))
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(None)),
        commit=AsyncMock(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await router.create_subagent(
            request=SimpleNamespace(),
            data=router.SubAgentCreate(
                name="agent-1",
                display_name="Agent 1",
                system_prompt="You are helpful.",
                trigger_description="Use for tests.",
                project_id="project-other-tenant",
            ),
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Access denied"
    assert db.commit.await_count == 0


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
async def test_import_filesystem_subagent_rejects_inaccessible_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.infrastructure.agent.subagent.filesystem_loader.FileSystemSubAgentLoader",
        _FilesystemLoaderWithAgent,
    )
    _patch_container(monkeypatch, _Container(subagent_repo=_EmptySubagentRepository()))
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(None)),
        commit=AsyncMock(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await router.import_filesystem_subagent(
            request=SimpleNamespace(),
            name="secret-subagent",
            project_id="project-other-tenant",
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Access denied"
    assert db.commit.await_count == 0


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


@pytest.mark.unit
@pytest.mark.parametrize(
    "route_name",
    ["get", "update", "delete", "enable", "stats", "export-template"],
)
async def test_project_scoped_subagent_routes_require_project_access(
    monkeypatch: pytest.MonkeyPatch,
    route_name: str,
) -> None:
    subagent = _make_subagent(
        subagent_id="subagent-hidden",
        name="hidden-agent",
        project_id="project-hidden",
    )
    repo = _SubagentAccessRepository(subagent=subagent)
    _patch_container(monkeypatch, _Container(subagent_repo=repo))
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(None)),
        commit=AsyncMock(),
    )
    current_user = SimpleNamespace(id="user-1")
    route_calls = {
        "get": lambda: router.get_subagent(
            request=SimpleNamespace(),
            subagent_id=subagent.id,
            tenant_id="tenant-1",
            current_user=current_user,
            db=db,
        ),
        "update": lambda: router.update_subagent(
            request=SimpleNamespace(),
            subagent_id=subagent.id,
            data=router.SubAgentUpdate(display_name="Updated"),
            tenant_id="tenant-1",
            current_user=current_user,
            db=db,
        ),
        "delete": lambda: router.delete_subagent(
            request=SimpleNamespace(),
            subagent_id=subagent.id,
            tenant_id="tenant-1",
            current_user=current_user,
            db=db,
        ),
        "enable": lambda: router.toggle_subagent_enabled(
            request=SimpleNamespace(),
            subagent_id=subagent.id,
            enabled=False,
            tenant_id="tenant-1",
            current_user=current_user,
            db=db,
        ),
        "stats": lambda: router.get_subagent_stats(
            request=SimpleNamespace(),
            subagent_id=subagent.id,
            tenant_id="tenant-1",
            current_user=current_user,
            db=db,
        ),
        "export-template": lambda: router.export_subagent_as_template(
            request=SimpleNamespace(),
            subagent_id=subagent.id,
            tenant_id="tenant-1",
            current_user=current_user,
            db=db,
        ),
    }

    with pytest.raises(HTTPException) as exc_info:
        await route_calls[route_name]()

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Access denied"
    repo.update.assert_not_awaited()
    repo.delete.assert_not_awaited()
    repo.set_enabled.assert_not_awaited()
    assert db.commit.await_count == 0


@pytest.mark.unit
async def test_list_subagents_filters_project_scoped_agents_by_project_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_subagent = _make_subagent(
        subagent_id="subagent-tenant",
        name="tenant-agent",
        project_id=None,
    )
    visible_subagent = _make_subagent(
        subagent_id="subagent-visible",
        name="visible-agent",
        project_id="project-visible",
    )
    hidden_subagent = _make_subagent(
        subagent_id="subagent-hidden",
        name="hidden-agent",
        project_id="project-hidden",
    )
    repo = _SubagentAccessRepository(
        subagents=[hidden_subagent, visible_subagent, tenant_subagent]
    )
    _patch_container(monkeypatch, _Container(subagent_repo=repo))
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(None, values=["project-visible"])),
    )

    response = await router.list_subagents(
        request=SimpleNamespace(),
        source="database",
        include_filesystem=False,
        limit=100,
        offset=0,
        tenant_id="tenant-1",
        current_user=SimpleNamespace(id="user-1"),
        db=db,
    )

    assert response.total == 2
    assert {subagent.id for subagent in response.subagents} == {
        "subagent-visible",
        "subagent-tenant",
    }


@pytest.mark.unit
async def test_match_subagent_skips_inaccessible_project_scoped_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    visible_subagent = _make_subagent(
        subagent_id="subagent-visible",
        name="visible-agent",
        project_id="project-visible",
    )
    hidden_subagent = _make_subagent(
        subagent_id="subagent-hidden",
        name="hidden-agent",
        project_id="project-hidden",
    )
    repo = _SubagentAccessRepository(matches=[hidden_subagent, visible_subagent])
    _patch_container(monkeypatch, _Container(subagent_repo=repo))
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(None, values=["project-visible"])),
    )

    response = await router.match_subagent(
        request=SimpleNamespace(),
        data=router.SubAgentMatchRequest(task_description="review this"),
        tenant_id="tenant-1",
        current_user=SimpleNamespace(id="user-1"),
        db=db,
    )

    assert response.confidence == 0.8
    assert response.subagent is not None
    assert response.subagent.id == "subagent-visible"


@pytest.mark.unit
async def test_match_subagent_returns_empty_when_only_inaccessible_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hidden_subagent = _make_subagent(
        subagent_id="subagent-hidden",
        name="hidden-agent",
        project_id="project-hidden",
    )
    repo = _SubagentAccessRepository(matches=[hidden_subagent])
    _patch_container(monkeypatch, _Container(subagent_repo=repo))
    db = SimpleNamespace(execute=AsyncMock(return_value=_ScalarResult(None, values=[])))

    response = await router.match_subagent(
        request=SimpleNamespace(),
        data=router.SubAgentMatchRequest(task_description="review this"),
        tenant_id="tenant-1",
        current_user=SimpleNamespace(id="user-1"),
        db=db,
    )

    assert response.confidence == 0.0
    assert response.subagent is None
