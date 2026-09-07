"""Concurrent source CAS against the actual migrated PostgreSQL tables."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
    PlatformPluginProfileSourceV2Error,
)
from src.infrastructure.plugins.v2.layer_composer import profile_source_digest_v2
from src.tests.integration.test_platform_plugin_scoped_ledger_postgres import sessions  # noqa: F401
from src.tests.unit.infrastructure.adapters.secondary.persistence.test_platform_plugin_profile_source_repository_v2 import (
    source_for,
)

pytestmark = pytest.mark.integration


async def test_concurrent_source_first_write_and_revision_cas(sessions):  # noqa: F811
    scope = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=uuid4().hex)
    first = source_for(scope)

    async def record(source, expected):
        async with sessions.begin() as session:
            return await PlatformPluginProfileSourceRepositoryV2(session).record_source(
                scope=scope, source=source, expected_revision=expected
            )

    initial = await asyncio.wait_for(asyncio.gather(*(record(first, None) for _ in range(6))), 15)
    assert initial == [first] * 6
    second = source_for(scope, revision=2)
    alternative = replace(second, provenance="fixture://competing-source")
    alternative = replace(alternative, digest=profile_source_digest_v2(alternative))

    async def advance(source):
        try:
            return await record(source, 1)
        except PlatformPluginProfileSourceV2Error as error:
            assert error.code == "profile_source_head_conflict"
            return None

    outcomes = await asyncio.wait_for(asyncio.gather(advance(second), advance(alternative)), 15)
    assert sum(value is not None for value in outcomes) == 1
    async with sessions() as session:
        repository = PlatformPluginProfileSourceRepositoryV2(session)
        assert (
            await repository.read_exact(
                scope=scope, source_id=first.source_id, revision=1, digest=first.digest
            )
            == first
        )
        assert (
            await repository.read_exact(
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
                source_id=first.source_id,
                revision=1,
                digest=first.digest,
            )
            is None
        )
