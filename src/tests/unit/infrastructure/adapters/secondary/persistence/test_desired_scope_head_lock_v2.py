"""Desired-state CAS shares the transaction-owned scope authority lock."""

import pytest
from sqlalchemy import func, select

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2DesiredBundleSetModel,
    PlatformPluginV2ScopeHeadModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
    PlatformPluginDesiredBundleSetV2Error,
)
from src.infrastructure.plugins.v2.scope import scope_key_v2
from src.tests.unit.infrastructure.adapters.secondary.persistence.test_platform_plugin_desired_bundle_repository_v2 import (
    _desired_set,
)

pytestmark = pytest.mark.unit


async def test_first_desired_write_and_scope_head_rollback_together(db_session):
    scope = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="cas-tenant")
    repository = PlatformPluginDesiredBundleSetRepositoryV2(db_session)
    await repository.record_desired_set(
        scope=scope, desired_set=_desired_set(), expected_revision=None, actor_id="actor"
    )
    head = await db_session.get(PlatformPluginV2ScopeHeadModel, scope_key_v2(scope))
    assert head is not None
    assert head.tenant_id == scope.tenant_id
    assert head.version_high_watermark == 0
    await db_session.rollback()
    assert await db_session.get(PlatformPluginV2ScopeHeadModel, scope_key_v2(scope)) is None
    assert await repository.current_desired_set(scope) is None
    await repository.record_desired_set(
        scope=scope, desired_set=_desired_set(), expected_revision=None, actor_id="actor"
    )
    await db_session.commit()
    with pytest.raises(PlatformPluginDesiredBundleSetV2Error) as failure:
        await repository.record_desired_set(
            scope=scope,
            desired_set=_desired_set(revision=8),
            expected_revision=None,
            actor_id="actor",
        )
    assert failure.value.code == "desired_set_head_conflict"
    await db_session.rollback()
    assert (await repository.current_desired_set(scope)).desired_set.revision == 7


async def test_desired_write_rejects_corrupt_scope_head_before_inserting_revision(db_session):
    scope = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="cas-tenant")
    db_session.add(
        PlatformPluginV2ScopeHeadModel(
            scope_key=scope_key_v2(scope), scope_kind="tenant", tenant_id="other-tenant"
        )
    )
    await db_session.commit()
    with pytest.raises(PlatformPluginDesiredBundleSetV2Error) as failure:
        await PlatformPluginDesiredBundleSetRepositoryV2(db_session).record_desired_set(
            scope=scope, desired_set=_desired_set(), expected_revision=None, actor_id="actor"
        )
    assert failure.value.code == "publication_scope_mismatch"
    assert (
        await db_session.scalar(
            select(func.count()).select_from(PlatformPluginV2DesiredBundleSetModel)
        )
        == 0
    )
