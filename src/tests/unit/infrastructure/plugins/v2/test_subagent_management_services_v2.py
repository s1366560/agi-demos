"""V2 application seam coverage for SubAgent management."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.subagent import SubAgent
from src.infrastructure.adapters.primary.web.routers.subagents import (
    create_subagent,
    delete_subagent,
    get_subagent,
    get_subagent_stats,
    import_filesystem_subagent,
    list_subagents,
    toggle_subagent_enabled,
    update_subagent,
)
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.subagent_management_services import (
    SUBAGENT_MANAGEMENT_MODULE_V2,
    SubAgentAccessDeniedV2,
    SubAgentAlreadyExistsV2,
    SubAgentManagementRepositoriesV2,
    SubAgentManagementServiceV2,
    SubAgentNotFoundV2,
    SubAgentProjectGrantV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"


class _ProjectAccess:
    def __init__(self) -> None:
        self.require_access = AsyncMock(
            side_effect=lambda **kwargs: SubAgentProjectGrantV2(**kwargs)
        )
        self.accessible_project_ids = AsyncMock(return_value=set())


def _make_subagent(
    *,
    subagent_id: str = "subagent-a",
    tenant_id: str = "tenant-a",
    project_id: str | None = None,
    name: str = "agent-a",
) -> SubAgent:
    subagent = SubAgent.create(
        tenant_id=tenant_id,
        project_id=project_id,
        name=name,
        display_name="Agent A",
        system_prompt="Prompt",
        trigger_description="Trigger",
    )
    subagent.id = subagent_id
    return subagent


def _service(
    *,
    subagent: SubAgent | None = None,
    subagents: list[SubAgent] | None = None,
) -> tuple[SubAgentManagementServiceV2, SimpleNamespace, _ProjectAccess]:
    repository = SimpleNamespace(
        create=AsyncMock(side_effect=lambda item: item),
        get_by_id=AsyncMock(return_value=subagent),
        get_by_name=AsyncMock(return_value=None),
        list_by_tenant=AsyncMock(return_value=subagents or []),
        count_by_tenant=AsyncMock(return_value=len(subagents or [])),
        update=AsyncMock(side_effect=lambda item: item),
        delete=AsyncMock(return_value=True),
        set_enabled=AsyncMock(side_effect=lambda _subagent_id, _enabled: subagent),
    )
    project_access = _ProjectAccess()
    db = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    return (
        SubAgentManagementServiceV2(
            repositories=SubAgentManagementRepositoriesV2(
                db=db,
                subagents=repository,
                project_access=project_access,
            ),
            tenant_id="tenant-a",
            user_id="user-a",
        ),
        repository,
        project_access,
    )


async def test_list_filters_project_scoped_subagents_by_exact_membership() -> None:
    tenant_agent = _make_subagent(subagent_id="tenant-agent")
    visible = _make_subagent(subagent_id="visible", project_id="project-visible")
    hidden = _make_subagent(subagent_id="hidden", project_id="project-hidden")
    service, repository, project_access = _service(subagents=[hidden, visible, tenant_agent])
    project_access.accessible_project_ids.return_value = {"project-visible"}

    result = await service.list_accessible(enabled_only=False)

    assert result == [visible, tenant_agent]
    repository.list_by_tenant.assert_awaited_once_with(
        "tenant-a",
        enabled_only=False,
        limit=3,
        offset=0,
    )
    project_access.accessible_project_ids.assert_awaited_once_with(
        tenant_id="tenant-a",
        user_id="user-a",
    )


async def test_create_requires_project_access_before_persistence_and_commits() -> None:
    service, repository, project_access = _service()
    subagent = _make_subagent(project_id="project-a")

    created = await service.create(subagent)

    assert created is subagent
    project_access.require_access.assert_awaited_once_with(
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
    )
    repository.create.assert_awaited_once_with(subagent)
    service.repositories.db.commit.assert_awaited_once()


async def test_create_rejects_duplicate_without_persistence() -> None:
    service, repository, _project_access = _service()
    subagent = _make_subagent()
    repository.get_by_name.return_value = _make_subagent(subagent_id="existing")

    with pytest.raises(SubAgentAlreadyExistsV2):
        await service.create(subagent)

    repository.create.assert_not_awaited()
    service.repositories.db.commit.assert_not_awaited()


async def test_require_access_hides_cross_tenant_subagent() -> None:
    service, _repository, project_access = _service(
        subagent=_make_subagent(tenant_id="tenant-other")
    )

    with pytest.raises(SubAgentNotFoundV2):
        await service.require_access("subagent-a")

    project_access.require_access.assert_not_awaited()


async def test_require_access_fails_closed_for_inaccessible_project() -> None:
    service, _repository, project_access = _service(subagent=_make_subagent(project_id="project-a"))
    project_access.require_access.side_effect = SubAgentAccessDeniedV2("project-a")

    with pytest.raises(SubAgentAccessDeniedV2):
        await service.require_access("subagent-a")


async def test_update_rejects_duplicate_name_without_commit() -> None:
    current = _make_subagent()
    updated = _make_subagent(name="renamed")
    service, repository, _project_access = _service(subagent=current)
    repository.get_by_name.return_value = _make_subagent(subagent_id="other", name="renamed")
    access = await service.require_access("subagent-a")

    with pytest.raises(SubAgentAlreadyExistsV2):
        await service.update(access, updated)

    repository.update.assert_not_awaited()
    service.repositories.db.commit.assert_not_awaited()


async def test_delete_and_toggle_commit_through_operation_session() -> None:
    current = _make_subagent()
    service, repository, _project_access = _service(subagent=current)
    access = await service.require_access("subagent-a")

    await service.delete(access)
    toggled = await service.set_enabled(access, enabled=False)

    assert toggled is current
    repository.delete.assert_awaited_once_with("subagent-a")
    repository.set_enabled.assert_awaited_once_with("subagent-a", False)
    assert service.repositories.db.commit.await_count == 2


def test_subagent_management_module_is_an_explicit_profile_consumer() -> None:
    profile = load_profile_document_v2(_PROFILE_PATH)
    entry = next(
        entry for entry in profile.entries if entry.module_ref == SUBAGENT_MANAGEMENT_MODULE_V2
    )

    assert entry.enabled is True
    assert entry.config == {"strategy": "operation-scoped-provider"}
    assert entry.inject == {"repositories": "service:persistence.subagent-repository-provider"}


def test_subagent_crud_routes_have_no_static_container_lookup() -> None:
    for handler in (
        create_subagent,
        list_subagents,
        import_filesystem_subagent,
        get_subagent,
        update_subagent,
        delete_subagent,
        toggle_subagent_enabled,
        get_subagent_stats,
    ):
        source = inspect.getsource(handler)
        assert "get_container_with_db" not in source
        assert "container." not in source
