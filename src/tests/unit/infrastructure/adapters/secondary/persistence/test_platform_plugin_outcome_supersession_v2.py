"""Supersession journals actual Loader outcomes without changing receipt authority."""

from copy import deepcopy
from dataclasses import replace

import pytest
from sqlalchemy import delete, func, inspect, select

from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2ApplyStateModel,
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_outcome_supersession_model_v2 import (
    PlatformPluginV2OutcomeSupersessionModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_outcome_supersession_repository_v2 import (
    PlatformPluginOutcomeSupersessionRepositoryV2,
    PlatformPluginOutcomeSupersessionV2Error,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_model_v2 import (
    PlatformPluginV2PublicationSourceModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.protocol import (
    control_envelope_v2,
    snapshot_apply_receipt_v2_to_payload,
)
from src.infrastructure.plugins.v2.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginDistributionV2
from src.tests.unit.application.services import (
    test_scoped_profile_publication_service_v2 as support,
)

pytestmark = pytest.mark.unit
setup_service = support.setup_service
PLANE = "python-api-v2"


def _next(snapshot, generation):
    return compose_profile_v2(
        ProfileDocumentV2(profile_id=snapshot.profile_id, entries=snapshot.entries),
        {manifest.plugin_id: manifest for manifest in snapshot.manifests},
        generation=generation,
    )


async def _advance(factory, scope):
    async with factory() as session:
        repository = PlatformPluginDesiredBundleSetRepositoryV2(session)
        current = (await repository.current_desired_set(scope)).desired_set
        desired = replace(current, revision=current.revision + 1)
        desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
        await repository.record_desired_set(
            scope=scope, desired_set=desired, expected_revision=current.revision, actor_id="fixture"
        )
        await session.commit()
        return desired


async def _request(factory, scope, snapshot, desired):
    async with factory() as session:
        repository = PlatformPluginRepositoryV2(session, scope=scope)
        version = await repository.allocate_publication_version()
        envelope = control_envelope_v2(snapshot, version=version)
        row = await repository.record_requested_distribution(snapshot, envelope)
        if desired is not None:
            await PlatformPluginPublicationSourceRepositoryV2(session).record(
                scope=scope, publication_id=row.id, desired_set=desired
            )
        await session.commit()
        return PlatformPluginDistributionV2(
            descriptor=PluginGenerationDescriptorV2(
                profile_id=snapshot.profile_id,
                generation=snapshot.generation,
                digest=snapshot.digest,
            ),
            snapshot=snapshot,
            envelope=envelope,
        )


@pytest.fixture
async def audit_case(setup_service, request):
    service, coordinator, scope, _desired, factory, _events, _load = setup_service
    outcome = (await service.publish_current(scope)).publication
    if getattr(request, "param", "ACK") == "NACK":
        desired = await _advance(factory, scope)
        outcome = await coordinator.publish(
            scope, _next(outcome.snapshot, desired.revision), verified_archives=()
        )
        assert not outcome.accepted
    desired = await _advance(factory, scope)
    replacement = await _request(factory, scope, _next(outcome.snapshot, desired.revision), desired)
    return factory, scope, outcome, replacement


async def _authority_state(factory):
    async with factory() as session:
        snapshots = []
        for model in (
            PlatformPluginV2PublicationModel,
            PlatformPluginV2ApplyStateModel,
            PlatformPluginV2ApplyStateEventModel,
        ):
            rows = (await session.scalars(select(model))).all()
            snapshots.append(
                sorted(
                    [
                        deepcopy(
                            {
                                column.key: getattr(row, column.key)
                                for column in inspect(model).columns
                            }
                        )
                        for row in rows
                    ],
                    key=lambda row: row["id"],
                )
            )
        return snapshots


async def _record(factory, scope, outcome, replacement, *, plane=PLANE):
    async with factory() as session:
        row = await PlatformPluginOutcomeSupersessionRepositoryV2(session).record(
            scope=scope, data_plane_id=plane, outcome=outcome, replacement=replacement
        )
        await session.commit()
        return row


@pytest.mark.parametrize("audit_case", ["ACK", "NACK"], indirect=True)
async def test_actual_outcome_journal_is_idempotent_without_readiness_mutation(audit_case):
    factory, scope, outcome, replacement = audit_case
    before = await _authority_state(factory)
    first = await _record(factory, scope, outcome, replacement)
    second = await _record(factory, scope, outcome, replacement)
    assert first.receipt_payload == snapshot_apply_receipt_v2_to_payload(outcome.receipt)
    assert second.receipt_payload == first.receipt_payload
    assert second.created_at == first.created_at
    assert await _authority_state(factory) == before
    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(PlatformPluginV2OutcomeSupersessionModel)
            )
            == 1
        )


@pytest.mark.parametrize("audit_case", ["NACK"], indirect=True)
async def test_same_pair_different_actual_receipt_is_rejected(audit_case):
    factory, scope, outcome, replacement = audit_case
    await _record(factory, scope, outcome, replacement)
    altered = replace(outcome, receipt=replace(outcome.receipt, error_message="different outcome"))
    before = await _authority_state(factory)
    with pytest.raises(PlatformPluginOutcomeSupersessionV2Error) as caught:
        await _record(factory, scope, altered, replacement)
    assert caught.value.code == "supersession_conflict"
    assert await _authority_state(factory) == before


@pytest.mark.parametrize(
    ("fault", "code"),
    [
        ("cross-scope", "supersession_publication_missing"),
        ("unknown-plane", "supersession_plane_unregistered"),
        ("not-latest", "supersession_replacement_stale"),
        ("no-source", "supersession_source_missing"),
        ("changed-desired", "supersession_source_changed"),
        ("not-newer", "supersession_not_newer"),
        ("unknown-request", "supersession_publication_missing"),
        ("distribution-mismatch", "supersession_distribution_mismatch"),
        ("invalid-receipt", "supersession_receipt_invalid"),
    ],
)
async def test_supersession_rejects_invalid_relationships_without_authority_changes(
    audit_case, fault, code
):
    factory, scope, outcome, replacement = audit_case
    requested_scope, plane = scope, PLANE
    if fault == "cross-scope":
        requested_scope = replace(scope, session_id="unrelated-session")
    elif fault == "unknown-plane":
        plane = "unknown-plane"
    elif fault == "not-latest":
        await _request(factory, scope, replacement.snapshot, None)
    elif fault == "no-source":
        async with factory() as session:
            publication_id = await session.scalar(
                select(PlatformPluginV2PublicationModel.id).where(
                    PlatformPluginV2PublicationModel.nonce == replacement.envelope.nonce
                )
            )
            await session.execute(
                delete(PlatformPluginV2PublicationSourceModel).where(
                    PlatformPluginV2PublicationSourceModel.publication_id == publication_id
                )
            )
            await session.commit()
    elif fault == "changed-desired":
        await _advance(factory, scope)
    elif fault == "not-newer":
        replacement = replace(
            replacement,
            snapshot=outcome.snapshot,
            envelope=outcome.envelope,
            descriptor=PluginGenerationDescriptorV2(
                profile_id=outcome.snapshot.profile_id,
                generation=outcome.snapshot.generation,
                digest=outcome.snapshot.digest,
            ),
        )
    elif fault == "unknown-request":
        outcome = replace(outcome, envelope=replace(outcome.envelope, nonce="unknown-request"))
    elif fault == "distribution-mismatch":
        replacement = replace(
            replacement, descriptor=replace(replacement.descriptor, generation=999)
        )
    elif fault == "invalid-receipt":
        outcome = replace(outcome, receipt=replace(outcome.receipt, requested_version=999))
    before = await _authority_state(factory)
    with pytest.raises(PlatformPluginOutcomeSupersessionV2Error) as caught:
        await _record(factory, requested_scope, outcome, replacement, plane=plane)
    assert caught.value.code == code
    assert await _authority_state(factory) == before
    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(PlatformPluginV2OutcomeSupersessionModel)
            )
            == 0
        )


@pytest.mark.parametrize("audit_case", ["NACK"], indirect=True)
async def test_nack_unregistered_applied_identity_is_rejected(audit_case):
    factory, scope, outcome, replacement = audit_case
    invalid = replace(
        outcome,
        receipt=replace(
            outcome.receipt, applied_version=987654, applied_digest="sha256:" + "a" * 64
        ),
    )
    before = await _authority_state(factory)
    with pytest.raises(PlatformPluginOutcomeSupersessionV2Error) as caught:
        await _record(factory, scope, invalid, replacement)
    assert caught.value.code == "supersession_receipt_invalid"
    assert await _authority_state(factory) == before
    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(PlatformPluginV2OutcomeSupersessionModel)
            )
            == 0
        )
