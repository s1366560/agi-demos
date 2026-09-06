"""ROOT execution generations and immutable desired revisions have independent clocks."""

from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_model_v2 import (
    PlatformPluginV2PublicationSourceModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
    PlatformPluginPublicationSourceV2Error,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.tests.unit.infrastructure.plugins.v2.test_profile_watcher_v2 import _candidate_inputs
from src.tests.unit.infrastructure.plugins.v2.test_scoped_runtime_registry import _profile

pytestmark = pytest.mark.unit


def _desired():
    return _candidate_inputs(Ed25519PrivateKey.generate())[3]


async def _requested(db, scope, generation):
    snapshot = _profile(scope, generation=generation)
    return await PlatformPluginRepositoryV2(db, scope=scope).record_requested_distribution(
        snapshot, control_envelope_v2(snapshot, version=generation)
    )


async def test_root_generation_advances_while_exact_desired_revision_remains_one(db_session):
    scope = ScopeV2(kind=ScopeKindV2.ROOT)
    desired = _desired()
    assert desired.revision == 1
    repository = PlatformPluginPublicationSourceRepositoryV2(db_session)
    ids = []
    for generation in (2, 3):
        publication = await _requested(db_session, scope, generation)
        ids.append(publication.id)
        assert (
            await repository.record(scope=scope, publication_id=publication.id, desired_set=desired)
            == desired
        )
        await db_session.commit()
    for publication_id in ids:
        assert await repository.read(scope=scope, publication_id=publication_id) == desired
        assert (
            await repository.record(scope=scope, publication_id=publication_id, desired_set=desired)
            == desired
        )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(PlatformPluginV2PublicationSourceModel)
        )
        == 2
    )
    different = replace(desired, desired_set_id="different-root-source")
    different = replace(different, digest=desired_bundle_set_digest_v2(different))
    with pytest.raises(PlatformPluginPublicationSourceV2Error) as caught:
        await repository.record(scope=scope, publication_id=ids[0], desired_set=different)
    assert caught.value.code == "publication_source_conflict"
    assert await repository.read(scope=scope, publication_id=ids[0]) == desired


@pytest.mark.parametrize("kind", [ScopeKindV2.TENANT, ScopeKindV2.PROJECT, ScopeKindV2.SESSION])
async def test_nonroot_revision_mismatch_still_rejected_on_record_and_read(db_session, kind):
    scope = ScopeV2(
        kind=kind,
        tenant_id="t",
        project_id="p" if kind != ScopeKindV2.TENANT else None,
        session_id="s" if kind == ScopeKindV2.SESSION else None,
    )
    repository = PlatformPluginPublicationSourceRepositoryV2(db_session)
    desired = _desired()
    wrong = await _requested(db_session, scope, 2)
    with pytest.raises(PlatformPluginPublicationSourceV2Error) as caught:
        await repository.record(scope=scope, publication_id=wrong.id, desired_set=desired)
    assert caught.value.code == "publication_source_revision_mismatch"
    assert await repository.read(scope=scope, publication_id=wrong.id) is None
    await db_session.rollback()
    valid = await _requested(db_session, scope, 1)
    await repository.record(scope=scope, publication_id=valid.id, desired_set=desired)
    await db_session.commit()
    # Deliberately corrupt the isolated fixture to exercise the read-time invariant.
    valid.generation = 2
    await db_session.flush()
    with pytest.raises(PlatformPluginPublicationSourceV2Error) as caught:
        await repository.read(scope=scope, publication_id=valid.id)
    assert caught.value.code == "publication_source_revision_mismatch"
