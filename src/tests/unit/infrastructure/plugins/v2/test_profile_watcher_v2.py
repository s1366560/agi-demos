"""Complete-candidate and last-good coverage for the protocol-v2 profile watcher."""

from __future__ import annotations

import asyncio
import base64
import json
import zipfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.domain.model.plugins.artifact_attestation_v2 import artifact_digest_v2
from src.domain.model.plugins.generated_v2 import (
    BundleArtifactV2,
    BundleManifestV2,
    BundleReferenceV2,
    DesiredBundleSetV2,
    PluginModuleV2,
    ProfileLayerKindV2,
    ProfileLayerV2,
    ProfileSourceReferenceV2,
    ProfileSourceV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.plugins.v2.artifacts import (
    PluginArtifactResolverV2,
    ResolvedPluginArtifactV2,
)
from src.infrastructure.plugins.v2.layer_composer import (
    bundle_manifest_digest_v2,
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.infrastructure.plugins.v2.profile_watcher import (
    BundleTrustPolicyV2,
    ProfileWatcherV2,
    ProfileWatchOutcomeV2,
)
from src.infrastructure.plugins.v2.protocol import (
    bundle_manifest_v2_to_payload,
    desired_bundle_set_v2_to_payload,
    parse_profile_snapshot_v2,
    profile_source_v2_to_payload,
)
from src.infrastructure.plugins.v2.runtime import PluginDefinitionV2
from src.tests.unit.infrastructure.plugins.v2.runtime_test_support import (
    RUNTIME_TEST_ARTIFACT_BYTES_V2,
    RuntimeTestArtifactResolverV2,
    target_catalog_from_snapshot_v2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_ZERO_DIGEST = f"sha256:{'0' * 64}"
_ROOT_SCOPE = ScopeV2(kind=ScopeKindV2.ROOT)


def _fixture_snapshot():
    payload = json.loads(
        (_ROOT / "shared/fixtures/platform-plugin-profile.v2.json").read_text(encoding="utf-8")
    )
    return parse_profile_snapshot_v2(payload)


def _candidate_inputs(
    signer: Ed25519PrivateKey,
    *,
    revision: int = 1,
    temperature: float = 0.7,
) -> tuple[BundleManifestV2, bytes, ProfileSourceV2, DesiredBundleSetV2]:
    snapshot = _fixture_snapshot()
    artifact_digest = artifact_digest_v2(RUNTIME_TEST_ARTIFACT_BYTES_V2)
    manifest = snapshot.manifests[0]
    modules = tuple(
        replace(module, artifact=replace(module.artifact, digest=artifact_digest))
        for module in manifest.modules
    )
    manifest = replace(manifest, modules=modules)
    root_entry = snapshot.entries[0]
    session_entry = replace(snapshot.entries[1], config={"temperature": temperature})
    targets = tuple(dict.fromkeys(target for module in modules for target in module.targets))
    artifacts = tuple(
        BundleArtifactV2(
            artifact_id=f"conformance-{target.value}",
            target=target,
            path=f"artifacts/{target.value}/conformance.bin",
            digest=artifact_digest,
            size_bytes=len(RUNTIME_TEST_ARTIFACT_BYTES_V2),
            media_type="application/octet-stream",
        )
        for target in targets
    )
    bundle = BundleManifestV2(
        schema_version=2,
        bundle_id="conformance-v2",
        version="1.0.0",
        manifests=(manifest,),
        layers=(
            ProfileLayerV2(
                layer_id="conformance-base",
                kind=ProfileLayerKindV2.BUNDLE,
                scope=_ROOT_SCOPE,
                entries=(root_entry,),
                replacements=(),
                disabled_entry_ids=(),
            ),
        ),
        artifacts=artifacts,
        digest=_ZERO_DIGEST,
        signature=None,
        provenance="tests",
    )
    bundle = replace(bundle, digest=bundle_manifest_digest_v2(bundle))
    signature = base64.b64encode(signer.sign(bundle.digest.encode("ascii"))).decode("ascii")
    bundle = replace(bundle, signature=signature)

    source = ProfileSourceV2(
        schema_version=2,
        source_id="conformance-source",
        profile_id="conformance-v2",
        revision=revision,
        digest=_ZERO_DIGEST,
        provenance="tests",
        layers=(
            ProfileLayerV2(
                layer_id=f"session-{revision}",
                kind=ProfileLayerKindV2.SESSION,
                scope=session_entry.scope,
                entries=(session_entry,),
                replacements=(),
                disabled_entry_ids=(),
            ),
        ),
    )
    source = replace(source, digest=profile_source_digest_v2(source))
    desired = DesiredBundleSetV2(
        schema_version=2,
        desired_set_id="conformance-desired",
        revision=revision,
        bundles=(
            BundleReferenceV2(
                bundle_id=bundle.bundle_id,
                version=bundle.version,
                digest=bundle.digest,
                source="memory://conformance-v2.mspkg",
            ),
        ),
        profile_source=ProfileSourceReferenceV2(
            source_id=source.source_id,
            revision=source.revision,
            digest=source.digest,
        ),
        digest=_ZERO_DIGEST,
    )
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    return bundle, _archive(bundle), source, desired


def _archive(bundle: BundleManifestV2) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bundle.json", json.dumps(bundle_manifest_v2_to_payload(bundle)))
        for artifact in bundle.artifacts:
            archive.writestr(artifact.path, RUNTIME_TEST_ARTIFACT_BYTES_V2)
    return output.getvalue()


def _public_key_pem(signer: Ed25519PrivateKey) -> str:
    return (
        signer.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )


def _json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _definitions(bundle: BundleManifestV2, events: list[str]) -> tuple[PluginDefinitionV2, ...]:
    modules = {module.module_ref: module for module in bundle.manifests[0].modules}

    def provider(context, config):
        label = str(config["label"])
        events.append(f"apply:provider:{label}")
        context.provide("service:clock", 7)
        return lambda: events.append(f"dispose:provider:{label}")

    def consumer(context, config):
        temperature = str(config["temperature"])
        assert context.require("clock") == 7
        events.append(f"apply:consumer:{temperature}")
        return lambda: events.append(f"dispose:consumer:{temperature}")

    return (
        PluginDefinitionV2(
            module_ref="builtin://conformance/root-provider",
            contract_digest=modules["builtin://conformance/root-provider"].contract_digest,
            apply=provider,
        ),
        PluginDefinitionV2(
            module_ref="builtin://conformance/session-consumer",
            contract_digest=modules["builtin://conformance/session-consumer"].contract_digest,
            apply=consumer,
        ),
    )


def _watcher(
    *,
    state: dict[str, object],
    signer: Ed25519PrivateKey,
    bundle: BundleManifestV2,
    events: list[str],
    reject_health: list[bool],
    execution_artifact_resolver: PluginArtifactResolverV2 | None = None,
) -> ProfileWatcherV2:
    async def load_desired() -> bytes:
        desired = state["desired"]
        assert isinstance(desired, DesiredBundleSetV2)
        return _json_bytes(desired_bundle_set_v2_to_payload(desired))

    async def fetch_bundle(_reference: BundleReferenceV2) -> bytes:
        events.append("fetch:bundle")
        raw = state["archive"]
        assert isinstance(raw, bytes)
        return raw

    async def fetch_profile(_reference: ProfileSourceReferenceV2) -> bytes:
        events.append("fetch:profile")
        source = state["source"]
        assert isinstance(source, ProfileSourceV2)
        return _json_bytes(profile_source_v2_to_payload(source))

    async def health_check(generation) -> None:
        events.append(f"health:{generation.generation}")
        if reject_health[0]:
            raise RuntimeError("candidate is unhealthy")

    return ProfileWatcherV2(
        desired_set_loader=load_desired,
        bundle_fetcher=fetch_bundle,
        profile_source_fetcher=fetch_profile,
        definitions=_definitions(bundle, events),
        target_catalog=target_catalog_from_snapshot_v2(_fixture_snapshot()),
        execution_artifact_resolver=(
            execution_artifact_resolver or RuntimeTestArtifactResolverV2()
        ),
        scope=ScopeV2(
            kind=ScopeKindV2.SESSION,
            tenant_id="tenant-a",
            project_id="project-a",
            session_id="session-a",
        ),
        trust_policy=BundleTrustPolicyV2(
            trusted_public_keys=(_public_key_pem(signer),),
            approved_permissions=frozenset({"service.clock.read"}),
            require_signature=True,
            require_provenance=True,
        ),
        health_checks=(health_check,),
    )


async def test_poll_builds_and_health_checks_complete_candidate_before_publish() -> None:
    signer = Ed25519PrivateKey.generate()
    bundle, archive, source, desired = _candidate_inputs(signer)
    state: dict[str, object] = {"archive": archive, "source": source, "desired": desired}
    events: list[str] = []
    watcher = _watcher(
        state=state,
        signer=signer,
        bundle=bundle,
        events=events,
        reject_health=[False],
    )

    applied = await watcher.poll_once()

    assert applied is not None
    assert applied.outcome is ProfileWatchOutcomeV2.APPLIED
    assert watcher.last_good is not None
    assert watcher.last_good.snapshot.generation == 1
    assert events == [
        "fetch:bundle",
        "fetch:profile",
        "apply:provider:根",
        "apply:consumer:0.7",
        "health:1",
    ]
    assert await watcher.poll_once() is None

    await watcher.close()

    assert events[-2:] == ["dispose:consumer:0.7", "dispose:provider:根"]


async def test_failed_health_disposes_candidate_keeps_last_good_and_retries() -> None:
    signer = Ed25519PrivateKey.generate()
    bundle, archive, source, desired = _candidate_inputs(signer)
    state: dict[str, object] = {"archive": archive, "source": source, "desired": desired}
    old_disposed = asyncio.Event()

    class DisposalEvents(list[str]):
        def append(self, event: str) -> None:
            super().append(event)
            if self[-2:] == ["dispose:consumer:0.7", "dispose:provider:根"]:
                old_disposed.set()

    events: list[str] = DisposalEvents()
    reject_health = [False]
    watcher = _watcher(
        state=state,
        signer=signer,
        bundle=bundle,
        events=events,
        reject_health=reject_health,
    )
    first = await watcher.poll_once()
    assert first is not None
    first_generation = watcher.host.manager.current

    _, _, changed_source, changed_desired = _candidate_inputs(
        signer,
        revision=2,
        temperature=0.9,
    )
    state.update(source=changed_source, desired=changed_desired)
    reject_health[0] = True

    rejected = await watcher.poll_once()

    assert rejected is not None
    assert rejected.outcome is ProfileWatchOutcomeV2.REJECTED
    assert rejected.error_code == "publication_staging_failed"
    assert watcher.host.manager.current is first_generation
    assert watcher.last_good is not None
    assert watcher.last_good.snapshot.generation == 1
    assert events[-5:] == [
        "apply:provider:根",
        "apply:consumer:0.9",
        "health:2",
        "dispose:consumer:0.9",
        "dispose:provider:根",
    ]

    reject_health[0] = False
    recovered = await watcher.poll_once()

    assert recovered is not None
    assert recovered.outcome is ProfileWatchOutcomeV2.APPLIED
    assert watcher.host.manager.current is not first_generation
    assert watcher.last_good is not None
    assert watcher.last_good.snapshot.generation == 2
    assert first_generation is not None
    await asyncio.wait_for(old_disposed.wait(), timeout=2)
    assert events[-3:] == [
        "health:2",
        "dispose:consumer:0.7",
        "dispose:provider:根",
    ]

    await watcher.close()


async def test_untrusted_bundle_is_rejected_before_any_fiber_activation() -> None:
    signer = Ed25519PrivateKey.generate()
    bundle, archive, source, desired = _candidate_inputs(signer)
    state: dict[str, object] = {"archive": archive, "source": source, "desired": desired}
    events: list[str] = []
    watcher = _watcher(
        state=state,
        signer=Ed25519PrivateKey.generate(),
        bundle=bundle,
        events=events,
        reject_health=[False],
    )

    rejected = await watcher.poll_once()

    assert rejected is not None
    assert rejected.outcome is ProfileWatchOutcomeV2.REJECTED
    assert rejected.error_code == "bundle_signature_invalid"
    assert watcher.host.manager.current is None
    assert events == ["fetch:bundle"]

    await watcher.close()


async def test_bundle_bytes_must_match_the_executable_artifact() -> None:
    signer = Ed25519PrivateKey.generate()
    bundle, archive, source, desired = _candidate_inputs(signer)
    state: dict[str, object] = {"archive": archive, "source": source, "desired": desired}
    events: list[str] = []

    class MismatchedResolver:
        def resolve(self, module: PluginModuleV2) -> ResolvedPluginArtifactV2:
            resolved = RuntimeTestArtifactResolverV2().resolve(module)
            return replace(resolved, canonical_bytes=b"different executable bytes")

    watcher = _watcher(
        state=state,
        signer=signer,
        bundle=bundle,
        events=events,
        reject_health=[False],
        execution_artifact_resolver=MismatchedResolver(),
    )

    rejected = await watcher.poll_once()

    assert rejected is not None
    assert rejected.outcome is ProfileWatchOutcomeV2.REJECTED
    assert rejected.error_code == "staging_failed"
    assert "executable bytes differ from its verified bundle" in (rejected.error_message or "")
    assert watcher.host.manager.current is None
    assert events == ["fetch:bundle", "fetch:profile"]

    await watcher.close()
