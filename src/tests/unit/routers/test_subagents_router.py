from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from pydantic import ValidationError

from src.infrastructure.adapters.primary.web.routers import subagents as router
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.subagent_management_services import (
    SubAgentAccessDeniedV2,
    SubAgentAccessV2,
    SubAgentAlreadyExistsV2,
)
from src.infrastructure.plugins.v2.subagent_selection_services import (
    SubAgentSelectionResultV2,
)
from src.infrastructure.plugins.v2.subagent_template_management_services import (
    SubAgentTemplateAlreadyExistsV2,
)


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
                    subagent=_make_subagent(
                        subagent_id="filesystem-subagent",
                        name="secret-subagent",
                        project_id=None,
                    ),
                    file_info=SimpleNamespace(file_path="/tmp/secret-subagent.md"),
                )
            ]
        )


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


def _management_service(
    *,
    subagent: router.SubAgent | None = None,
    subagents: list[router.SubAgent] | None = None,
) -> SimpleNamespace:
    access = (
        None
        if subagent is None
        else SubAgentAccessV2(
            subagent=subagent,
            tenant_id="tenant-1",
            user_id="user-1",
        )
    )
    return SimpleNamespace(
        tenant_id="tenant-1",
        user_id="user-1",
        create=AsyncMock(side_effect=lambda item: item),
        list_accessible=AsyncMock(return_value=subagents or []),
        require_access=AsyncMock(return_value=access),
        update=AsyncMock(side_effect=lambda _access, item: item),
        delete=AsyncMock(return_value=None),
        set_enabled=AsyncMock(return_value=subagent),
    )


def _patch_subagent_authority(
    monkeypatch: pytest.MonkeyPatch,
    service: object,
) -> None:
    @asynccontextmanager
    async def authority(**_kwargs: object) -> AsyncIterator[SimpleNamespace]:
        yield SimpleNamespace(service=service)

    monkeypatch.setattr(router, "subagent_http_application_authority_v2", authority)


def _patch_selection_authority(
    monkeypatch: pytest.MonkeyPatch,
    service: object,
) -> None:
    @asynccontextmanager
    async def authority(**_kwargs: object) -> AsyncIterator[SimpleNamespace]:
        yield SimpleNamespace(service=service)

    monkeypatch.setattr(router, "subagent_selection_http_application_authority_v2", authority)


def _template_management_service() -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id="tenant-1",
        user_id="user-1",
        create=AsyncMock(),
        list_published=AsyncMock(),
        list_categories=AsyncMock(return_value=[]),
        require_template=AsyncMock(),
        update=AsyncMock(),
        delete=AsyncMock(return_value=None),
        install=AsyncMock(),
        export_subagent=AsyncMock(),
        seed_builtin=AsyncMock(return_value=0),
    )


def _patch_template_authority(
    monkeypatch: pytest.MonkeyPatch,
    service: object,
) -> None:
    @asynccontextmanager
    async def authority(**_kwargs: object) -> AsyncIterator[SimpleNamespace]:
        yield SimpleNamespace(service=service)

    monkeypatch.setattr(router, "subagent_template_http_application_authority_v2", authority)


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
async def test_get_selected_subagent_tenant_id_uses_fallback_without_query_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_access = AsyncMock()
    monkeypatch.setattr(router, "require_tenant_access", require_access)

    tenant_id = await router._get_selected_subagent_tenant_id(
        selected_tenant_id=None,
        fallback_tenant_id="home-tenant",
        current_user=SimpleNamespace(id="user-1"),
        db=SimpleNamespace(),
    )

    assert tenant_id == "home-tenant"
    require_access.assert_not_awaited()


@pytest.mark.unit
async def test_get_selected_subagent_tenant_id_validates_explicit_query_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_access = AsyncMock()
    monkeypatch.setattr(router, "require_tenant_access", require_access)
    current_user = SimpleNamespace(id="user-1")
    db = SimpleNamespace()

    tenant_id = await router._get_selected_subagent_tenant_id(
        selected_tenant_id="selected-tenant",
        fallback_tenant_id="home-tenant",
        current_user=current_user,
        db=db,
    )

    assert tenant_id == "selected-tenant"
    require_access.assert_awaited_once_with(db, current_user, "selected-tenant")


@pytest.mark.unit
async def test_import_filesystem_subagent_sanitizes_missing_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.infrastructure.agent.subagent.filesystem_loader.FileSystemSubAgentLoader",
        _EmptyFilesystemLoader,
    )
    _patch_subagent_authority(monkeypatch, _management_service())

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
    service = _management_service()
    service.create.side_effect = SubAgentAlreadyExistsV2("secret-subagent")
    _patch_subagent_authority(monkeypatch, service)

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
    _patch_subagent_authority(monkeypatch, _management_service())

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
    service = _management_service()
    service.create.side_effect = SubAgentAccessDeniedV2("project-other-tenant")
    _patch_subagent_authority(monkeypatch, service)
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
    service = _management_service()
    service.create.side_effect = SubAgentAlreadyExistsV2("secret-subagent")
    _patch_subagent_authority(monkeypatch, service)

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
    service = _management_service()
    service.create.side_effect = SubAgentAccessDeniedV2("project-other-tenant")
    _patch_subagent_authority(monkeypatch, service)
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
    service = _template_management_service()
    service.create.side_effect = SubAgentTemplateAlreadyExistsV2("secret-template@2.1.3")
    _patch_template_authority(monkeypatch, service)

    with pytest.raises(HTTPException) as exc_info:
        await router.create_template(
            request=SimpleNamespace(),
            data=router.TemplateCreate(
                name="secret-template",
                version="2.1.3",
                system_prompt="Prompt",
            ),
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
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
    service = _template_management_service()
    service.install.side_effect = SubAgentAlreadyExistsV2("secret-template-subagent")
    _patch_template_authority(monkeypatch, service)

    with pytest.raises(HTTPException) as exc_info:
        await router.install_template(
            request=SimpleNamespace(),
            template_id="template-1",
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert exc_info.value.detail == "SubAgent already exists"
    assert "secret-template-subagent" not in exc_info.value.detail


@pytest.mark.unit
async def test_update_subagent_sanitizes_duplicate_name(monkeypatch: pytest.MonkeyPatch) -> None:
    subagent = _make_subagent(
        subagent_id="subagent-1",
        name="current-subagent",
        project_id=None,
    )
    service = _management_service(subagent=subagent)
    service.update.side_effect = SubAgentAlreadyExistsV2("secret-new-name")
    _patch_subagent_authority(monkeypatch, service)

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
    service = _management_service(subagent=subagent)
    service.require_access.side_effect = SubAgentAccessDeniedV2("project-hidden")
    _patch_subagent_authority(monkeypatch, service)
    template_service = _template_management_service()
    template_service.export_subagent.side_effect = SubAgentAccessDeniedV2("project-hidden")
    _patch_template_authority(monkeypatch, template_service)
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
    service.update.assert_not_awaited()
    service.delete.assert_not_awaited()
    service.set_enabled.assert_not_awaited()
    assert db.commit.await_count == 0


@pytest.mark.unit
async def test_list_subagents_uses_v2_access_filtered_results(
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
    service = _management_service(subagents=[visible_subagent, tenant_subagent])
    _patch_subagent_authority(monkeypatch, service)

    response = await router.list_subagents(
        request=SimpleNamespace(),
        enabled_only=False,
        search=None,
        sort="name",
        source="database",
        include_filesystem=False,
        limit=100,
        offset=0,
        tenant_id="tenant-1",
        current_user=SimpleNamespace(id="user-1"),
        db=SimpleNamespace(),
    )

    assert response.total == 2
    assert {subagent.id for subagent in response.subagents} == {
        "subagent-visible",
        "subagent-tenant",
    }
    service.list_accessible.assert_awaited_once_with(enabled_only=False)


@pytest.mark.unit
async def test_list_subagents_searches_before_paginating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha_subagent = _make_subagent(
        subagent_id="subagent-alpha",
        name="alpha-agent",
        project_id=None,
    )
    beta_subagent = _make_subagent(
        subagent_id="subagent-beta",
        name="beta-agent",
        project_id=None,
    )
    beta_subagent.trigger = router.AgentTrigger(
        description="Handles database diagnostics",
        keywords=["database"],
    )
    beta_subagent.total_invocations = 12
    beta_subagent.success_rate = 0.75
    service = _management_service(subagents=[alpha_subagent, beta_subagent])
    _patch_subagent_authority(monkeypatch, service)

    response = await router.list_subagents(
        request=SimpleNamespace(),
        enabled_only=False,
        search="database",
        sort="invocations",
        source="database",
        include_filesystem=False,
        limit=1,
        offset=0,
        tenant_id="tenant-1",
        current_user=SimpleNamespace(id="user-1"),
        db=SimpleNamespace(),
    )

    assert response.total == 1
    assert response.enabled_total == 1
    assert response.total_invocations == 12
    assert response.average_success_rate == 0.75
    assert [subagent.id for subagent in response.subagents] == ["subagent-beta"]
    service.list_accessible.assert_awaited_once_with(enabled_only=False)


@pytest.mark.unit
async def test_match_subagent_returns_structured_judge_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_subagent = _make_subagent(
        subagent_id="subagent-visible",
        name="visible-agent",
        project_id="project-visible",
    )
    result = SubAgentSelectionResultV2(
        selected=selected_subagent,
        confidence=0.93,
        rationale="The selected SubAgent best fits the task.",
        audit=None,
    )
    service = SimpleNamespace(match=AsyncMock(return_value=result))
    _patch_selection_authority(monkeypatch, service)
    db = SimpleNamespace()

    response = await router.match_subagent(
        request=SimpleNamespace(),
        data=router.SubAgentMatchRequest(task_description="review this"),
        tenant_id="tenant-1",
        current_user=SimpleNamespace(id="user-1"),
        db=db,
    )

    assert response.confidence == 0.93
    assert response.subagent is not None
    assert response.subagent.id == "subagent-visible"
    service.match.assert_awaited_once_with("review this")


@pytest.mark.unit
async def test_match_subagent_returns_explicit_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = SubAgentSelectionResultV2(
        selected=None,
        confidence=0.0,
        rationale="No supplied candidate is appropriate.",
        audit=None,
    )
    service = SimpleNamespace(match=AsyncMock(return_value=result))
    _patch_selection_authority(monkeypatch, service)

    response = await router.match_subagent(
        request=SimpleNamespace(),
        data=router.SubAgentMatchRequest(task_description="review this"),
        tenant_id="tenant-1",
        current_user=SimpleNamespace(id="user-1"),
        db=SimpleNamespace(),
    )

    assert response.confidence == 0.0
    assert response.subagent is None
    service.match.assert_awaited_once_with("review this")


@pytest.mark.unit
async def test_match_subagent_returns_structured_unavailable_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        match=AsyncMock(
            side_effect=RuntimeV2Error(
                "subagent_selection_judge_failed",
                "provider detail must not escape",
            )
        )
    )
    _patch_selection_authority(monkeypatch, service)

    with pytest.raises(HTTPException) as exc_info:
        await router.match_subagent(
            request=SimpleNamespace(),
            data=router.SubAgentMatchRequest(task_description="review this"),
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc_info.value.detail == {
        "code": "subagent_selection_judge_failed",
        "message": "SubAgent selection authority is unavailable",
    }
    assert "provider detail" not in str(exc_info.value.detail)
    service.match.assert_awaited_once_with("review this")


@pytest.mark.unit
def test_subagent_match_request_rejects_oversized_task() -> None:
    with pytest.raises(ValidationError):
        router.SubAgentMatchRequest(task_description="x" * 8001)
