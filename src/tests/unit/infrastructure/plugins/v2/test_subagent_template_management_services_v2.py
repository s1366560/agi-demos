"""V2 application seam coverage for SubAgent template management."""

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
    create_template,
    delete_template,
    export_subagent_as_template,
    get_template,
    install_template,
    list_subagent_templates,
    list_template_categories,
    seed_templates,
    update_template,
)
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.subagent_management_services import (
    SubAgentAlreadyExistsV2,
    SubAgentProjectGrantV2,
)
from src.infrastructure.plugins.v2.subagent_template_management_services import (
    SUBAGENT_TEMPLATE_MANAGEMENT_MODULE_V2,
    SubAgentTemplateAlreadyExistsV2,
    SubAgentTemplateBuiltinMutationV2,
    SubAgentTemplateManagementServiceV2,
    SubAgentTemplateNotFoundV2,
    SubAgentTemplatePersistenceErrorV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"


class _ProjectAccess:
    def __init__(self) -> None:
        self.require_access = AsyncMock(
            side_effect=lambda **kwargs: SubAgentProjectGrantV2(**kwargs)
        )


def _template(
    *,
    template_id: str = "template-a",
    tenant_id: str = "tenant-a",
    name: str = "researcher",
    is_builtin: bool = False,
) -> dict[str, object]:
    return {
        "id": template_id,
        "tenant_id": tenant_id,
        "name": name,
        "version": "1.0.0",
        "display_name": "Researcher",
        "description": "Research tasks",
        "category": "research",
        "tags": ["research"],
        "system_prompt": "Research carefully.",
        "trigger_description": "Research",
        "trigger_keywords": ["research"],
        "trigger_examples": ["Investigate this topic"],
        "model": "inherit",
        "max_tokens": 4096,
        "temperature": 0.7,
        "max_iterations": 10,
        "allowed_tools": ["memory_search"],
        "author": None,
        "is_builtin": is_builtin,
        "is_published": True,
        "install_count": 0,
        "rating": 0.0,
        "metadata": None,
        "created_at": None,
        "updated_at": None,
    }


def _subagent(*, project_id: str | None = None) -> SubAgent:
    subagent = SubAgent.create(
        tenant_id="tenant-a",
        project_id=project_id,
        name="researcher",
        display_name="Researcher",
        system_prompt="Research carefully.",
        trigger_description="Research",
    )
    subagent.id = "subagent-a"
    return subagent


def _service(
    *,
    template: dict[str, object] | None = None,
    templates: list[dict[str, object]] | None = None,
    subagent: SubAgent | None = None,
) -> tuple[
    SubAgentTemplateManagementServiceV2,
    SimpleNamespace,
    SimpleNamespace,
    _ProjectAccess,
]:
    template_repository = SimpleNamespace(
        create=AsyncMock(side_effect=lambda item: {**_template(), **item}),
        get_by_id=AsyncMock(return_value=template),
        get_by_name=AsyncMock(return_value=None),
        update=AsyncMock(
            side_effect=lambda template_id, item: {
                **(template or _template(template_id=template_id)),
                **item,
            }
        ),
        delete=AsyncMock(return_value=True),
        list_templates=AsyncMock(return_value=templates or []),
        count_templates=AsyncMock(return_value=len(templates or [])),
        list_categories=AsyncMock(return_value=["research"]),
        increment_install_count=AsyncMock(return_value=None),
    )
    subagent_repository = SimpleNamespace(
        create=AsyncMock(side_effect=lambda item: item),
        get_by_id=AsyncMock(return_value=subagent),
        get_by_name=AsyncMock(return_value=None),
    )
    project_access = _ProjectAccess()
    db = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    return (
        SubAgentTemplateManagementServiceV2(
            db=db,
            templates=template_repository,
            subagents=subagent_repository,
            project_access=project_access,
            tenant_id="tenant-a",
            user_id="user-a",
        ),
        template_repository,
        subagent_repository,
        project_access,
    )


async def test_list_and_categories_are_exact_tenant_queries() -> None:
    record = _template()
    service, templates, _subagents, _project_access = _service(templates=[record])

    page = await service.list_published(
        category="research",
        query="memory",
        limit=20,
        offset=5,
    )
    categories = await service.list_categories()

    assert page.templates == [record]
    assert page.total == 1
    assert categories == ["research"]
    templates.list_templates.assert_awaited_once_with(
        tenant_id="tenant-a",
        category="research",
        query="memory",
        published_only=True,
        limit=20,
        offset=5,
    )
    templates.count_templates.assert_awaited_once_with(
        tenant_id="tenant-a",
        category="research",
    )
    templates.list_categories.assert_awaited_once_with("tenant-a")


async def test_list_fails_closed_for_cross_tenant_repository_result() -> None:
    service, _templates, _subagents, _project_access = _service(
        templates=[_template(tenant_id="tenant-other")]
    )

    with pytest.raises(SubAgentTemplateNotFoundV2):
        await service.list_published(category=None, query=None, limit=50, offset=0)


async def test_create_overrides_tenant_and_commits_once() -> None:
    service, templates, _subagents, _project_access = _service()

    created = await service.create(
        {
            "tenant_id": "tenant-other",
            "name": "researcher",
            "version": "1.0.0",
            "system_prompt": "Research carefully.",
        }
    )

    assert created["tenant_id"] == "tenant-a"
    templates.get_by_name.assert_awaited_once_with("tenant-a", "researcher", "1.0.0")
    persisted = templates.create.await_args.args[0]
    assert persisted["tenant_id"] == "tenant-a"
    service.db.commit.assert_awaited_once()


async def test_create_rejects_duplicate_without_persistence() -> None:
    service, templates, _subagents, _project_access = _service()
    templates.get_by_name.return_value = _template()

    with pytest.raises(SubAgentTemplateAlreadyExistsV2):
        await service.create(
            {
                "name": "researcher",
                "version": "1.0.0",
                "system_prompt": "Research carefully.",
            }
        )

    templates.create.assert_not_awaited()
    service.db.commit.assert_not_awaited()


async def test_get_hides_cross_tenant_template() -> None:
    service, _templates, _subagents, _project_access = _service(
        template=_template(tenant_id="tenant-other")
    )

    with pytest.raises(SubAgentTemplateNotFoundV2):
        await service.require_template("template-a")


async def test_update_and_delete_reject_builtin_without_mutation() -> None:
    service, templates, _subagents, _project_access = _service(template=_template(is_builtin=True))

    with pytest.raises(SubAgentTemplateBuiltinMutationV2):
        await service.update("template-a", {"display_name": "Changed"})
    with pytest.raises(SubAgentTemplateBuiltinMutationV2):
        await service.delete("template-a")

    templates.update.assert_not_awaited()
    templates.delete.assert_not_awaited()
    service.db.commit.assert_not_awaited()


async def test_update_fails_closed_when_repository_loses_record() -> None:
    service, templates, _subagents, _project_access = _service(template=_template())
    templates.update.side_effect = None
    templates.update.return_value = None

    with pytest.raises(SubAgentTemplatePersistenceErrorV2):
        await service.update("template-a", {"display_name": "Changed"})

    service.db.commit.assert_not_awaited()


async def test_install_is_one_operation_owned_transaction() -> None:
    service, templates, subagents, _project_access = _service(template=_template())

    created = await service.install("template-a")

    assert created.tenant_id == "tenant-a"
    assert created.name == "researcher"
    subagents.get_by_name.assert_awaited_once_with("tenant-a", "researcher")
    subagents.create.assert_awaited_once()
    templates.increment_install_count.assert_awaited_once_with("template-a")
    service.db.commit.assert_awaited_once()


async def test_install_rejects_duplicate_without_increment_or_commit() -> None:
    service, templates, subagents, _project_access = _service(template=_template())
    subagents.get_by_name.return_value = _subagent()

    with pytest.raises(SubAgentAlreadyExistsV2):
        await service.install("template-a")

    subagents.create.assert_not_awaited()
    templates.increment_install_count.assert_not_awaited()
    service.db.commit.assert_not_awaited()


async def test_export_authorizes_project_and_commits_template() -> None:
    subagent = _subagent(project_id="project-a")
    service, templates, _subagents, project_access = _service(subagent=subagent)

    created = await service.export_subagent("subagent-a")

    assert created["tenant_id"] == "tenant-a"
    assert created["name"] == "researcher"
    project_access.require_access.assert_awaited_once_with(
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
    )
    service.db.commit.assert_awaited_once()
    template_data = templates.create.await_args.args[0]
    assert template_data["description"] == "Exported from SubAgent: Researcher"


async def test_seed_uses_operation_repository_and_commits_once() -> None:
    service, templates, _subagents, _project_access = _service()

    created = await service.seed_builtin()

    assert created == 3
    assert templates.get_by_name.await_count == 3
    assert templates.create.await_count == 3
    service.db.commit.assert_awaited_once()


def test_subagent_template_module_declares_both_repository_aliases() -> None:
    profile = load_profile_document_v2(_PROFILE_PATH)
    entry = next(
        entry
        for entry in profile.entries
        if entry.module_ref == SUBAGENT_TEMPLATE_MANAGEMENT_MODULE_V2
    )

    assert entry.enabled is True
    assert entry.config == {"strategy": "operation-scoped-provider"}
    assert entry.inject == {
        "subagents": "service:persistence.subagent-repository-provider",
        "templates": "service:persistence.subagent-template-repository-provider",
    }


def test_subagent_template_routes_have_no_static_container_lookup() -> None:
    for handler in (
        list_subagent_templates,
        create_template,
        list_template_categories,
        get_template,
        update_template,
        delete_template,
        install_template,
        export_subagent_as_template,
        seed_templates,
    ):
        source = inspect.getsource(handler)
        assert "get_container_with_db" not in source
        assert "container." not in source
