"""Retired plugin skills cannot be loaded through cached or new runtime tools."""

from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.marketplace_skill_runtime import resolve_marketplace_skill
from src.infrastructure.agent.tools.skill_loader import make_skill_loader_tool
from src.tests.unit.application.services.test_plugin_marketplace_v3 import (
    db,  # noqa: F401
    install_fixture,
    service,  # noqa: F401
)
from src.tests.unit.infrastructure.agent.tools.test_skill_loader_runtime import _context

pytestmark = pytest.mark.unit


async def test_current_authority_rejects_disabled_and_uninstalled_cached_loaders(
    service,  # noqa: F811
    db,  # noqa: F811
):
    installed = await install_fixture(service)
    await service.mutate(installed["id"], "enable", {"idempotency_key": "enable"})
    await db.commit()
    resolver = partial(
        resolve_marketplace_skill,
        "tenant-a",
        "project-a",
        sessions=async_sessionmaker(db.bind, expire_on_commit=False),
    )
    old_snapshot = await resolver("example-skill")
    stale = SimpleNamespace(
        list_available_skills=AsyncMock(return_value=[old_snapshot]),
        load_skill_content=AsyncMock(return_value="STALE CACHE"),
        record_skill_usage=AsyncMock(),
    )

    def loader():
        return make_skill_loader_tool(
            skill_service=stale,
            tenant_id="tenant-a",
            project_id="project-a",
            available_skill_names=["example-skill"],
            marketplace_skill_resolver=resolver,
        )

    cached = loader()
    result = await cached.execute(_context("enabled"), name="example-skill")
    assert result.is_error is False
    assert "# Example" in result.output
    assert "STALE CACHE" not in result.output
    for action in ("disable", "uninstall"):
        await service.mutate(installed["id"], action, {"idempotency_key": action})
        await db.commit()
        for tool in (cached, loader()):
            result = await tool.execute(_context(action), name="example-skill")
            assert result.is_error is True
            assert "disabled or unavailable" in result.output
        assert old_snapshot.full_content == "# Example"
    stale.load_skill_content.assert_not_awaited()
    assert (
        await resolve_marketplace_skill(
            "tenant-a",
            "other-project",
            "example-skill",
            sessions=async_sessionmaker(db.bind, expire_on_commit=False),
        )
        is None
    )
