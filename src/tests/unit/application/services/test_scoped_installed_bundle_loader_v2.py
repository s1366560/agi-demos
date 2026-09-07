"""Real SQL governance, OCI MockTransport and signed archives share no open session."""

import asyncio
import hashlib
import json
from dataclasses import replace

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.installed_verified_bundle_loader_v2 import (
    MarketplacePublicationV2Error,
)
from src.application.services.scoped_installed_bundle_loader_v2 import ScopedInstalledBundleLoaderV2
from src.infrastructure.adapters.secondary.persistence.models import PlatformPluginPackageModel
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.plugins.package_registry import (
    MEMSTACK_ARTIFACT_TYPE,
    MEMSTACK_LAYER_MEDIA_TYPE,
    OCI_MANIFEST_MEDIA_TYPE,
    PluginRegistryError,
)
from src.infrastructure.plugins.v2.production_bundle import ProductionBundleSourcesV2
from src.infrastructure.plugins.v2.protocol import bundle_manifest_v2_to_payload
from src.tests.unit.infrastructure.plugins.v2.test_profile_watcher_v2 import (
    _candidate_inputs,
    _public_key_pem,
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def bundle_inputs(db_session):
    signer = Ed25519PrivateKey.generate()
    bundle, raw, source, desired = _candidate_inputs(signer)
    layer_digest = hashlib.sha256(raw).hexdigest()
    manifest = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": OCI_MANIFEST_MEDIA_TYPE,
            "artifactType": MEMSTACK_ARTIFACT_TYPE,
            "layers": [
                {
                    "mediaType": MEMSTACK_LAYER_MEDIA_TYPE,
                    "digest": f"sha256:{layer_digest}",
                    "size": len(raw),
                }
            ],
        }
    ).encode()
    manifest_digest = hashlib.sha256(manifest).hexdigest()
    sessions = []
    closed = []

    class Session(AsyncSession):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sessions.append(self)

        async def close(self):
            await super().close()
            closed.append(self)

    factory = async_sessionmaker(db_session.bind, class_=Session, expire_on_commit=False)
    async with factory() as session:
        session.add(
            PlatformPluginPackageModel(
                plugin_id=bundle.bundle_id,
                version=bundle.version,
                publisher="fixture",
                artifact_digest=layer_digest,
                artifact_registry="https://registry.example",
                artifact_repository="plugins/clock",
                oci_manifest_digest=manifest_digest,
                install_status="installed",
                manifest=bundle_manifest_v2_to_payload(bundle),
                security_scan_status="approved",
                revoked=False,
            )
        )
        await PlatformPluginGovernanceRepository(session).grant_permission(
            plugin_id=bundle.bundle_id, permission="service.clock.read"
        )
        await session.commit()
    sessions.clear()
    closed.clear()
    reference = replace(
        desired.bundles[0], source=f"marketplace://{bundle.bundle_id}/{bundle.version}"
    )
    options = {
        "session_factory": factory,
        "production_sources": ProductionBundleSourcesV2(
            bundle=bundle, bundle_archive=raw, profile_source=source, desired_set=desired
        ),
        "trusted_public_keys": (_public_key_pem(signer),),
        "allowed_registries": frozenset({"https://registry.example"}),
    }
    return reference, manifest, raw, options, sessions, closed


def client_factory(handler, clients):
    def create():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    return create


async def test_signed_archive_and_new_governance_each_call(bundle_inputs):
    reference, manifest, raw, options, sessions, closed = bundle_inputs
    clients = []
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=manifest if "/manifests/" in request.url.path else raw)

    loader = ScopedInstalledBundleLoaderV2(
        **options, http_client_factory=client_factory(handler, clients)
    )
    verified = await loader(reference)
    assert verified.manifest.digest == reference.digest
    assert len(requests) == 2
    assert sessions == closed and len(sessions) == 1
    assert clients[0].is_closed
    async with options["session_factory"]() as session:
        package = await session.get(
            PlatformPluginPackageModel, (reference.bundle_id, reference.version)
        )
        package.revoked = True
        await session.commit()
    with pytest.raises(MarketplacePublicationV2Error) as failure:
        await loader(reference)
    assert failure.value.code == "marketplace_bundle_unavailable"
    assert len(requests) == 2
    assert sessions == closed and len(sessions) == 3
    assert len(clients) == 2 and all(client.is_closed for client in clients)


async def test_http_failure_closes_both_resources(bundle_inputs):
    reference, _, _, options, sessions, closed = bundle_inputs
    clients = []
    loader = ScopedInstalledBundleLoaderV2(
        **options, http_client_factory=client_factory(lambda request: httpx.Response(503), clients)
    )
    with pytest.raises(PluginRegistryError):
        await loader(reference)
    assert sessions == closed and len(sessions) == 1
    assert clients[0].is_closed


async def test_cancellation_during_fetch_closes_both_resources(bundle_inputs):
    reference, _, _, options, sessions, closed = bundle_inputs
    clients = []
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def handler(request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    loader = ScopedInstalledBundleLoaderV2(
        **options, http_client_factory=client_factory(handler, clients)
    )
    task = asyncio.create_task(loader(reference))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
    assert sessions == closed and len(sessions) == 1
    assert clients[0].is_closed


async def test_empty_registry_set_denies_before_network_and_closes(bundle_inputs):
    reference, _, _, options, sessions, closed = bundle_inputs
    options["allowed_registries"] = frozenset()
    clients = []
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(500)

    loader = ScopedInstalledBundleLoaderV2(
        **options, http_client_factory=client_factory(handler, clients)
    )
    with pytest.raises(MarketplacePublicationV2Error) as failure:
        await loader(reference)
    assert failure.value.code == "marketplace_registry_forbidden"
    assert not requests
    assert sessions == closed and clients[0].is_closed
