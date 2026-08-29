"""V2 plugin configuration authority coverage for the evolution scheduler."""

from __future__ import annotations

from contextlib import asynccontextmanager
from inspect import getsource
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.infrastructure.agent.plugins.skill_evolution.config import SkillEvolutionConfig
from src.infrastructure.agent.plugins.skill_evolution.scheduler import _load_tenant_config

pytestmark = pytest.mark.unit


async def test_scheduler_loads_tenant_override_through_background_repository_lease() -> None:
    db = object()
    repository = SimpleNamespace(
        get_by_tenant_and_plugin=AsyncMock(
            return_value=SimpleNamespace(config={"min_sessions_per_skill": 19})
        )
    )
    lifecycle: list[str] = []

    @asynccontextmanager
    async def repository_lease(*, db: object, tenant_id: str):
        assert db is db_session
        assert tenant_id == "tenant-a"
        lifecycle.append("enter")
        yield SimpleNamespace(repository=repository)
        lifecycle.append("exit")

    db_session = db
    config = await _load_tenant_config(
        repository_lease,
        db,
        tenant_id="tenant-a",
        default_config=SkillEvolutionConfig(min_sessions_per_skill=5),
    )

    assert config.min_sessions_per_skill == 19
    assert lifecycle == ["enter", "exit"]
    repository.get_by_tenant_and_plugin.assert_awaited_once_with(
        tenant_id="tenant-a",
        plugin_name="skill_evolution",
    )


async def test_scheduler_uses_default_config_only_when_override_row_is_absent() -> None:
    default = SkillEvolutionConfig(min_sessions_per_skill=23)
    repository = SimpleNamespace(get_by_tenant_and_plugin=AsyncMock(return_value=None))

    @asynccontextmanager
    async def repository_lease(**_kwargs: object):
        yield SimpleNamespace(repository=repository)

    resolved = await _load_tenant_config(
        repository_lease,
        object(),
        tenant_id="tenant-a",
        default_config=default,
    )

    assert resolved is default


async def test_scheduler_propagates_repository_failure_without_environment_fallback() -> None:
    repository = SimpleNamespace(
        get_by_tenant_and_plugin=AsyncMock(
            side_effect=SQLAlchemyError("scheduler plugin config unavailable")
        )
    )

    @asynccontextmanager
    async def repository_lease(**_kwargs: object):
        yield SimpleNamespace(repository=repository)

    with pytest.raises(SQLAlchemyError, match="scheduler plugin config unavailable"):
        await _load_tenant_config(
            repository_lease,
            object(),
            tenant_id="tenant-a",
            default_config=SkillEvolutionConfig(min_sessions_per_skill=29),
        )


def test_scheduler_config_loader_has_no_static_repository_or_optional_database_fallback() -> None:
    source = getsource(_load_tenant_config)

    assert "PluginConfigRepository(" not in source
    assert "SQLAlchemyError" not in source
    assert "except" not in source
