"""Verified archives bind the actual scoped Loader and remain candidate-local."""

import asyncio
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
from src.infrastructure.plugins.v2.protocol import build_profile_snapshot_v2, control_envelope_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.scoped_runtime_registry import ScopedRuntimeRegistryV2
from src.tests.unit.infrastructure.plugins.v2.runtime_test_support import (
    RuntimeTestArtifactResolverV2,
    target_catalog_from_snapshot_v2,
)
from src.tests.unit.infrastructure.plugins.v2.test_profile_watcher_v2 import (
    _candidate_inputs,
    _definitions,
    _fixture_snapshot,
    _public_key_pem,
)
from src.tests.unit.infrastructure.plugins.v2.test_scoped_runtime_registry import _scope

pytestmark = pytest.mark.unit


def _inputs(scope, generation=1):
    signer = Ed25519PrivateKey.generate()
    bundle, raw, _, desired = _candidate_inputs(signer)
    archive = parse_bundle_archive_v2(
        raw,
        source=desired.bundles[0].source,
        trusted_public_keys=(_public_key_pem(signer),),
        approved_permissions=frozenset(
            permission for manifest in bundle.manifests for permission in manifest.permissions
        ),
        require_signature=True,
        require_provenance=True,
    )
    entries = _fixture_snapshot().entries
    snapshot = build_profile_snapshot_v2(
        profile_id="verified-scoped",
        generation=generation,
        manifests=bundle.manifests,
        entries=(entries[0], replace(entries[1], scope=scope)),
    )
    return bundle, archive, snapshot


@pytest.mark.parametrize("missing", [True, False])
async def test_missing_or_different_executable_bytes_never_apply(missing):
    scope = _scope()
    bundle, archive, snapshot = _inputs(scope)
    events = []

    class WrongBytes(RuntimeTestArtifactResolverV2):
        def resolve(self, module):
            return replace(super().resolve(module), canonical_bytes=b"different execution")

    registry = ScopedRuntimeRegistryV2(
        _definitions(bundle, events),
        artifact_resolver=RuntimeTestArtifactResolverV2() if missing else WrongBytes(),
        target_catalog=target_catalog_from_snapshot_v2(snapshot),
    )
    try:
        publication = await registry.publish(
            scope,
            snapshot,
            control_envelope_v2(snapshot, version=1),
            verified_archives=() if missing else (archive,),
        )
        assert not publication.accepted
        assert events == []
        with pytest.raises(RuntimeV2Error):
            await registry.acquire(scope)
    finally:
        await registry.close()


async def test_verified_slot_cannot_be_downgraded_and_nack_retains_last_good():
    scope = _scope()
    bundle, archive, snapshot = _inputs(scope)
    events = []
    registry = ScopedRuntimeRegistryV2(
        _definitions(bundle, events),
        artifact_resolver=RuntimeTestArtifactResolverV2(),
        target_catalog=target_catalog_from_snapshot_v2(snapshot),
    )
    try:
        first = await registry.publish(
            scope, snapshot, control_envelope_v2(snapshot, version=1), verified_archives=(archive,)
        )
        assert first.accepted
        with pytest.raises(RuntimeV2Error, match="trust mode"):
            await registry.publish(scope, snapshot, control_envelope_v2(snapshot, version=2))
        with pytest.raises(RuntimeV2Error, match="no verified"):
            await registry.publish(
                scope, snapshot, control_envelope_v2(snapshot, version=2), verified_archives=()
            )
        repeated = await registry.publish(
            scope, snapshot, control_envelope_v2(snapshot, version=2), verified_archives=(archive,)
        )
        assert repeated.accepted
        assert len(events) == 2
        next_snapshot = build_profile_snapshot_v2(
            profile_id=snapshot.profile_id,
            generation=2,
            manifests=snapshot.manifests,
            entries=snapshot.entries,
        )
        failed = await registry.publish(
            scope,
            next_snapshot,
            control_envelope_v2(next_snapshot, version=3),
            verified_archives=(),
        )
        assert not failed.accepted
        async with await registry.acquire(scope) as current:
            assert current.generation == 1
            assert current.resolve("service:clock", scope) == 7
    finally:
        await registry.close()


async def test_concurrent_scope_archive_bindings_do_not_cross_candidates():
    scope = _scope()
    other = _scope("b")
    bundle, archive, snapshot = _inputs(scope)
    _, _, second = _inputs(other)
    entered, resume = asyncio.Event(), asyncio.Event()
    events = []
    definitions = _definitions(bundle, events)

    async def slow_provider(context, config):
        entered.set()
        await resume.wait()
        return definitions[0].apply(context, config)

    registry = ScopedRuntimeRegistryV2(
        (replace(definitions[0], apply=slow_provider), definitions[1]),
        artifact_resolver=RuntimeTestArtifactResolverV2(),
        target_catalog=target_catalog_from_snapshot_v2(snapshot),
    )
    task = asyncio.create_task(
        registry.publish(
            scope, snapshot, control_envelope_v2(snapshot, version=1), verified_archives=(archive,)
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        failed = await registry.publish(
            other, second, control_envelope_v2(second, version=1), verified_archives=()
        )
        assert not failed.accepted
        resume.set()
        assert (await task).accepted
        assert len(events) == 2
    finally:
        resume.set()
        await task
        await registry.close()


async def test_plain_generation_cannot_be_relabelled_as_verified_by_fast_ack():
    scope = _scope()
    bundle, archive, snapshot = _inputs(scope)
    events = []
    registry = ScopedRuntimeRegistryV2(
        _definitions(bundle, events),
        artifact_resolver=RuntimeTestArtifactResolverV2(),
        target_catalog=target_catalog_from_snapshot_v2(snapshot),
    )
    try:
        assert (
            await registry.publish(scope, snapshot, control_envelope_v2(snapshot, version=1))
        ).accepted
        with pytest.raises(RuntimeV2Error, match="trust mode"):
            await registry.publish(
                scope,
                snapshot,
                control_envelope_v2(snapshot, version=2),
                verified_archives=(archive,),
            )
        assert len(events) == 2
    finally:
        await registry.close()
