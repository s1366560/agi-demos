"""ROOT host candidate archive attestation without persistent resolver bindings."""

from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, compose_profile_v2
from src.infrastructure.plugins.v2.protocol import (
    control_envelope_v2,
    control_envelope_v2_to_payload,
    profile_snapshot_v2_to_payload,
)
from src.infrastructure.plugins.v2.runtime import LoaderV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
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

pytestmark = pytest.mark.unit


@pytest.fixture
async def candidate():
    signer = Ed25519PrivateKey.generate()
    bundle, raw, _source, _desired = _candidate_inputs(signer)
    archive = parse_bundle_archive_v2(
        raw,
        source="test-verified",
        trusted_public_keys=(_public_key_pem(signer),),
        require_signature=True,
        approved_permissions=frozenset({"service.clock.read"}),
    )
    base = _fixture_snapshot()
    snapshot = compose_profile_v2(
        ProfileDocumentV2(profile_id=base.profile_id, entries=base.entries),
        {manifest.plugin_id: manifest for manifest in bundle.manifests},
        generation=1,
    )
    events = []
    fault = {"wrong_bytes": False}

    class Resolver(RuntimeTestArtifactResolverV2):
        def resolve(self, module):
            resolved = super().resolve(module)
            return (
                replace(resolved, canonical_bytes=b"different executable bytes")
                if fault["wrong_bytes"]
                else resolved
            )

    host = PlatformPluginRuntimeHostV2(
        loader=LoaderV2(
            _definitions(bundle, events),
            target_catalog=target_catalog_from_snapshot_v2(snapshot),
            artifact_resolver=Resolver(),
        )
    )
    try:
        yield host, snapshot, archive, events, fault
    finally:
        await host.close()


def _next(snapshot, generation):
    return compose_profile_v2(
        ProfileDocumentV2(profile_id=snapshot.profile_id, entries=snapshot.entries),
        {manifest.plugin_id: manifest for manifest in snapshot.manifests},
        generation=generation,
    )


async def _apply(host, snapshot, *, version, archives, distribution):
    envelope = control_envelope_v2(snapshot, version=version)
    if distribution:
        return await host.apply_distribution(
            {
                "descriptor": {
                    "profile_id": snapshot.profile_id,
                    "generation": snapshot.generation,
                    "digest": snapshot.digest,
                },
                "snapshot": profile_snapshot_v2_to_payload(snapshot),
                "envelope": control_envelope_v2_to_payload(envelope),
            },
            verified_archives=archives,
        )
    return await host.apply(snapshot, envelope, verified_archives=archives)


@pytest.mark.parametrize("distribution", [False, True])
async def test_first_verified_apply_uses_real_archive_and_loader(candidate, distribution):
    host, snapshot, archive, events, _fault = candidate
    publication = await _apply(
        host, snapshot, version=1, archives=(archive,), distribution=distribution
    )
    assert publication.accepted
    assert host.manager.current.snapshot == snapshot
    assert any(event.startswith("apply:provider:") for event in events)
    lease = await host.acquire()
    await lease.release()


@pytest.mark.parametrize("distribution", [False, True])
@pytest.mark.parametrize("failure", ["empty", "wrong-bytes"])
async def test_invalid_verified_candidate_has_zero_apply(candidate, distribution, failure):
    host, snapshot, archive, events, fault = candidate
    fault["wrong_bytes"] = failure == "wrong-bytes"
    rejected = await _apply(
        host,
        snapshot,
        version=1,
        archives=() if failure == "empty" else (archive,),
        distribution=distribution,
    )
    assert not rejected.accepted
    assert rejected.receipt.error_code == "staging_failed"
    assert host.manager.current is None
    assert events == []
    fault["wrong_bytes"] = False
    accepted = await _apply(
        host, snapshot, version=2, archives=(archive,), distribution=distribution
    )
    assert accepted.accepted
    assert any(event.startswith("apply:provider:") for event in events)


@pytest.mark.parametrize("failure", ["empty", "wrong-bytes"])
async def test_same_digest_cannot_ack_invalid_archives_and_retains_old_lease(candidate, failure):
    host, snapshot, archive, events, fault = candidate
    accepted = await _apply(host, snapshot, version=1, archives=(archive,), distribution=False)
    assert accepted.accepted
    lease = await host.acquire()
    old = host.manager.current
    previous = list(events)
    try:
        fault["wrong_bytes"] = failure == "wrong-bytes"
        rejected = await _apply(
            host,
            snapshot,
            version=2,
            archives=() if failure == "empty" else (archive,),
            distribution=False,
        )
        assert not rejected.accepted
        assert rejected.receipt.error_code == "artifact_verification_failed"
        assert host.manager.current is old
        assert lease.generation is old
        assert not lease._released
        assert host.current_publication == accepted
        assert events == previous
        fault["wrong_bytes"] = False
        assert (
            await _apply(host, snapshot, version=3, archives=(archive,), distribution=False)
        ).accepted
        assert events == previous
    finally:
        await lease.release()


async def test_verified_startup_does_not_require_archives_for_later_plain_hmr(candidate):
    host, snapshot, archive, events, _fault = candidate
    assert (
        await _apply(host, snapshot, version=1, archives=(archive,), distribution=False)
    ).accepted
    newer = _next(snapshot, 2)
    plain = await host.apply(newer, control_envelope_v2(newer, version=2))
    assert plain.accepted
    assert host.manager.current.snapshot == newer
    third = _next(snapshot, 3)
    assert (await _apply(host, third, version=3, archives=(archive,), distribution=True)).accepted
    assert sum(event.startswith("apply:provider:") for event in events) == 3


@pytest.mark.parametrize("wrong_bytes", [False, True])
async def test_dynamic_load_consumes_the_exact_attested_resolved_object(candidate, wrong_bytes):
    _unused_host, snapshot, archive, _unused_events, _fault = candidate
    events = []
    definitions = {
        definition.module_ref: definition for definition in _definitions(archive.manifest, events)
    }
    resolved_objects = {}
    loaded_objects = []

    class DynamicResolver(RuntimeTestArtifactResolverV2):
        def resolve(self, module):
            assert module.module_ref not in resolved_objects, (
                "must not resolve again after attestation"
            )
            base = super().resolve(module)

            def load():
                assert resolved_objects[module.module_ref] is resolved
                loaded_objects.append(resolved)
                return definitions[module.module_ref]

            resolved = replace(
                base,
                load=load,
                canonical_bytes=b"wrong executable" if wrong_bytes else base.canonical_bytes,
            )
            resolved_objects[module.module_ref] = resolved
            return resolved

    host = PlatformPluginRuntimeHostV2(
        loader=LoaderV2(
            (),
            target_catalog=target_catalog_from_snapshot_v2(snapshot),
            artifact_resolver=DynamicResolver(),
        )
    )
    try:
        publication = await host.apply(
            snapshot, control_envelope_v2(snapshot, version=1), verified_archives=(archive,)
        )
        if wrong_bytes:
            assert not publication.accepted
            assert publication.receipt.error_code == "staging_failed"
            assert loaded_objects == []
            assert events == []
            assert host.manager.current is None
        else:
            assert publication.accepted
            enabled = {entry.module_ref for entry in snapshot.entries if entry.enabled}
            assert {resolved.module_ref for resolved in loaded_objects} == enabled
            assert all(
                resolved_objects[resolved.module_ref] is resolved for resolved in loaded_objects
            )
            assert any(event.startswith("apply:provider:") for event in events)
    finally:
        await host.close()
