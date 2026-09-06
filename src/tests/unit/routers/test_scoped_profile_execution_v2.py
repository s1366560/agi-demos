"""Authenticated configuration reaches signed Bundle composition and real execution."""

from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.scoped_profile_publication_service_v2 import (
    ScopedProfilePublicationServiceV2,
)
from src.domain.model.plugins.generated_v2 import (
    ProfileLayerKindV2,
    ScopeKindV2,
    ScopeV2,
    ServiceRequiredV2,
)
from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
from src.infrastructure.plugins.v2.layer_composer import (
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.infrastructure.plugins.v2.protocol import (
    desired_bundle_set_v2_to_payload,
    profile_source_v2_to_payload,
)
from src.infrastructure.plugins.v2.scoped_publication_coordinator import (
    ScopedPublicationCoordinatorV2,
)
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
from src.tests.unit.routers.test_profile_source_v2_router import (  # noqa: F401
    PATH,
    authenticated_source,
)

pytestmark = pytest.mark.unit


async def test_authenticated_source_and_desired_are_composed_and_admitted(
    authenticated_source,  # noqa: F811
    db_session,
):
    client, keys = authenticated_source
    scope = ScopeV2(kind=ScopeKindV2.SESSION, tenant_id="t", project_id="p", session_id="s")
    signer = Ed25519PrivateKey.generate()
    bundle, archive, source, desired = _candidate_inputs(signer)
    root = bundle.layers[0].entries[0]
    layer = replace(
        source.layers[0],
        kind=ProfileLayerKindV2.PROFILE,
        scope=root.scope,
        entries=(),
        replacements=(replace(root, config={"label": "from-saved-source"}),),
    )
    source = replace(source, layers=(layer,))
    source = replace(source, digest=profile_source_digest_v2(source))
    desired = replace(desired, profile_source=replace(desired.profile_source, digest=source.digest))
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    scope_payload = {"kind": "session", "tenant_id": "t", "project_id": "p", "session_id": "s"}
    headers = {"Authorization": f"Bearer {keys['owner']}"}
    saved = await client.post(
        PATH,
        headers=headers,
        json={
            "scope": scope_payload,
            "source": profile_source_v2_to_payload(source),
            "expected_revision": None,
        },
    )
    assert saved.status_code == 200, saved.text
    configured = await client.put(
        "/api/v1/platform-plugins/v2/desired-bundle-sets/current",
        headers=headers,
        json={
            "schema_version": 2,
            "scope": scope_payload,
            "expected_revision": None,
            "desired_bundle_set": desired_bundle_set_v2_to_payload(desired),
        },
    )
    assert configured.status_code == 200, configured.text
    events = []
    registry = ScopedRuntimeRegistryV2(
        _definitions(bundle, events),
        target_catalog=target_catalog_from_snapshot_v2(_fixture_snapshot()),
        artifact_resolver=RuntimeTestArtifactResolverV2(),
    )
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    coordinator = ScopedPublicationCoordinatorV2(session_factory=factory, registry=registry)

    async def load(reference):
        return parse_bundle_archive_v2(
            archive,
            source=reference.source,
            trusted_public_keys=(_public_key_pem(signer),),
            approved_permissions=frozenset(
                permission for manifest in bundle.manifests for permission in manifest.permissions
            ),
            require_signature=True,
            require_provenance=True,
        )

    service = ScopedProfilePublicationServiceV2(
        session_factory=factory,
        coordinator=coordinator,
        load_verified_bundle=load,
        required_services=(
            ServiceRequiredV2(service="service:clock", version="1.0.0", alias="clock"),
        ),
    )
    try:
        result = await service.publish_current(scope)
        assert result.desired_revision == desired.revision
        assert result.publication.accepted
        assert events == ["apply:provider:from-saved-source"]
        async with await coordinator.acquire(scope) as generation:
            assert generation.resolve("service:clock", scope) == 7
    finally:
        await coordinator.close()
