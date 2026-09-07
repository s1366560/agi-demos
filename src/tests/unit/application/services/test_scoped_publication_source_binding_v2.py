"""Publication history retains its exact immutable desired configuration."""

from dataclasses import replace

import pytest
from sqlalchemy import func, select

from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
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
from src.tests.unit.application.services import (
    test_scoped_profile_publication_service_v2 as service_support,
)

setup_service = service_support.setup_service

pytestmark = pytest.mark.unit


async def _publication_id(factory, nonce):
    async with factory() as session:
        return (
            await session.execute(
                select(PlatformPluginV2PublicationModel.id).where(
                    PlatformPluginV2PublicationModel.nonce == nonce
                )
            )
        ).scalar_one()


def _next_desired(desired):
    newer = replace(desired, revision=desired.revision + 1)
    return replace(newer, digest=desired_bundle_set_digest_v2(newer))


async def test_real_service_binds_exact_desired_and_later_configuration_does_not_rewrite(
    setup_service,
):
    service, _coordinator, scope, desired, factory, events, _load = setup_service
    result = await service.publish_current(scope)
    assert result.publication.accepted
    assert events == ["apply:provider:根"]
    publication_id = await _publication_id(factory, result.publication.envelope.nonce)
    async with factory() as session:
        repository = PlatformPluginPublicationSourceRepositoryV2(session)
        assert await repository.read(scope=scope, publication_id=publication_id) == desired
        newer = _next_desired(desired)
        await PlatformPluginDesiredBundleSetRepositoryV2(session).record_desired_set(
            scope=scope,
            desired_set=newer,
            expected_revision=desired.revision,
            actor_id="new-config",
        )
        await session.commit()
    async with factory() as session:
        assert (
            await PlatformPluginPublicationSourceRepositoryV2(session).read(
                scope=scope, publication_id=publication_id
            )
            == desired
        )
        assert (
            await PlatformPluginDesiredBundleSetRepositoryV2(session).current_desired_set(scope)
        ).desired_set == newer


async def test_binding_write_failure_rolls_back_requested_and_never_applies(
    setup_service, monkeypatch
):
    service, _coordinator, scope, _desired, factory, events, _load = setup_service
    original_error = RuntimeError("binding write fault")

    async def fail(self, *, scope, publication_id, desired_set):
        raise original_error

    monkeypatch.setattr(PlatformPluginPublicationSourceRepositoryV2, "record", fail)
    with pytest.raises(RuntimeError) as caught:
        await service.publish_current(scope)
    assert caught.value is original_error
    assert events == []
    async with factory() as session:
        for model in (PlatformPluginV2PublicationModel, PlatformPluginV2PublicationSourceModel):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
    # The failure was before any application; retry must still be able to publish.
    monkeypatch.undo()
    assert (await service.publish_current(scope)).publication.accepted
    assert events == ["apply:provider:根"]


async def test_exact_binding_record_is_idempotent_and_different_desired_is_rejected(setup_service):
    service, _coordinator, scope, desired, factory, _events, _load = setup_service
    result = await service.publish_current(scope)
    publication_id = await _publication_id(factory, result.publication.envelope.nonce)
    async with factory() as session:
        repository = PlatformPluginPublicationSourceRepositoryV2(session)
        assert (
            await repository.record(scope=scope, publication_id=publication_id, desired_set=desired)
            == desired
        )
        await session.commit()
    async with factory() as session:
        repository = PlatformPluginPublicationSourceRepositoryV2(session)
        different = replace(desired, desired_set_id="another-desired")
        different = replace(different, digest=desired_bundle_set_digest_v2(different))
        with pytest.raises(PlatformPluginPublicationSourceV2Error) as caught:
            await repository.record(
                scope=scope, publication_id=publication_id, desired_set=different
            )
        assert caught.value.code == "publication_source_conflict"
        await session.rollback()
    async with factory() as session:
        assert (
            await PlatformPluginPublicationSourceRepositoryV2(session).read(
                scope=scope, publication_id=publication_id
            )
            == desired
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(PlatformPluginV2PublicationSourceModel)
            )
            == 1
        )


async def test_publication_binding_cannot_be_read_through_another_scope(setup_service):
    service, _coordinator, scope, desired, factory, _events, _load = setup_service
    result = await service.publish_current(scope)
    publication_id = await _publication_id(factory, result.publication.envelope.nonce)
    sibling = replace(scope, session_id="another-session")
    async with factory() as session:
        repository = PlatformPluginPublicationSourceRepositoryV2(session)
        with pytest.raises(PlatformPluginPublicationSourceV2Error) as caught:
            await repository.read(scope=sibling, publication_id=publication_id)
        assert caught.value.code == "publication_scope_mismatch"
        assert await repository.read(scope=scope, publication_id=publication_id) == desired


async def test_republish_keeps_ready_source_binding_and_public_distribution_shape(setup_service):
    service, _coordinator, scope, desired, factory, _events, _load = setup_service
    result = await service.publish_current(scope)
    assert result.publication.accepted
    original_id = await _publication_id(factory, result.publication.envelope.nonce)
    async with factory() as session:
        await PlatformPluginDesiredBundleSetRepositoryV2(session).record_desired_set(
            scope=scope,
            desired_set=_next_desired(desired),
            expected_revision=desired.revision,
            actor_id="new-config",
        )
        await session.commit()
    async with factory() as session:
        repository = PlatformPluginRepositoryV2(session, scope=scope)
        republished = await repository.republish_last_globally_ready()
        assert republished.id != original_id
        assert set(republished.distribution) == {"snapshot", "envelope", "descriptor"}
        new_id = republished.id
        await session.commit()
    async with factory() as session:
        binding = PlatformPluginPublicationSourceRepositoryV2(session)
        assert await binding.read(scope=scope, publication_id=original_id) == desired
        assert await binding.read(scope=scope, publication_id=new_id) == desired
        public = await PlatformPluginRepositoryV2(
            session, scope=scope
        ).latest_requested_distribution()
        assert set(public) == {"snapshot", "envelope", "descriptor"}
