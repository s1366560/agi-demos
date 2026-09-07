"""Exact source persistence through the real SQL repository and protocol parser."""

from dataclasses import replace

import pytest
from sqlalchemy import select

from src.domain.model.plugins.generated_v2 import ProfileLayerKindV2, ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_model_v2 import (
    PlatformPluginV2ProfileSourceModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.plugins.v2.layer_composer import profile_source_digest_v2
from src.tests.unit.infrastructure.plugins.v2.layer_composer_test_support import _layer, _source


def source_for(scope, revision=1):
    source = _source(
        (_layer("layer", ProfileLayerKindV2.TENANT, scope=scope, disabled_entry_ids=("entry",)),)
    )
    source = replace(source, revision=revision)
    return replace(source, digest=profile_source_digest_v2(source))


@pytest.mark.unit
async def test_exact_scope_source_cas_retry_and_immutable_history(db_session):
    a = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="a")
    b = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="b")
    repo = PlatformPluginProfileSourceRepositoryV2(db_session)
    first = source_for(a)
    await repo.record_source(scope=a, source=first, expected_revision=None)
    await repo.record_source(scope=a, source=first, expected_revision=None)
    await repo.record_source(scope=b, source=source_for(b), expected_revision=None)
    second = source_for(a, 2)
    with pytest.raises(ValueError, match="CAS"):
        await repo.record_source(scope=a, source=second, expected_revision=None)
    await repo.record_source(scope=a, source=second, expected_revision=1)
    assert (
        await repo.read_exact(scope=a, source_id=first.source_id, revision=1, digest=first.digest)
        == first
    )
    assert (
        await repo.read_exact(scope=b, source_id=first.source_id, revision=1, digest=first.digest)
        is None
    )
    assert (
        await repo.read_exact(
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
            source_id=first.source_id,
            revision=1,
            digest=first.digest,
        )
        is None
    )


@pytest.mark.unit
async def test_source_rejects_sibling_and_bad_digest_before_insert(db_session):
    a = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="a")
    b = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="b")
    repo = PlatformPluginProfileSourceRepositoryV2(db_session)
    with pytest.raises(ValueError, match="ancestor"):
        await repo.record_source(scope=a, source=source_for(b), expected_revision=None)
    with pytest.raises(ValueError, match="digest"):
        await repo.record_source(
            scope=a, source=replace(source_for(a), digest="0" * 64), expected_revision=None
        )
    assert list((await db_session.scalars(select(PlatformPluginV2ProfileSourceModel))).all()) == []


@pytest.mark.unit
async def test_source_read_detects_payload_identity_corruption(db_session):
    scope = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="a")
    repo = PlatformPluginProfileSourceRepositoryV2(db_session)
    source = source_for(scope)
    await repo.record_source(scope=scope, source=source, expected_revision=None)
    row = (await db_session.scalars(select(PlatformPluginV2ProfileSourceModel))).one()
    row.profile_id = "corrupt"
    await db_session.flush()
    with pytest.raises(ValueError, match="identity"):
        await repo.read_exact(
            scope=scope, source_id=source.source_id, revision=1, digest=source.digest
        )


@pytest.mark.unit
async def test_source_allows_ancestor_layer_and_rejects_revision_gap(db_session):
    tenant = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="a")
    project = ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id="a", project_id="p")
    repo = PlatformPluginProfileSourceRepositoryV2(db_session)
    with pytest.raises(ValueError, match="revision gap"):
        await repo.record_source(
            scope=project, source=source_for(tenant, 2), expected_revision=None
        )
    await repo.record_source(scope=project, source=source_for(tenant), expected_revision=None)
