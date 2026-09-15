"""Real retained lineage, loopback OCI, signature verification and RuntimeHost admission."""

import hashlib
import json
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.publication_archive_loader_v2 import (
    PublicationArchiveLoaderV2,
    load_agent_generation_archives_v2,
)
from src.application.services.scoped_installed_bundle_loader_v2 import ScopedInstalledBundleLoaderV2
from src.domain.model.plugins.generated_v2 import BundleReferenceV2, ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import PlatformPluginPackageModel
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.builtin_modules import (
    RUNTIME_BOUNDARY_MODULE_V2,
    builtin_runtime_definitions_v2,
)
from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import (
    build_profile_snapshot_v2,
    bundle_manifest_v2_to_payload,
    control_envelope_v2,
    profile_snapshot_v2_to_payload,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import DataPlaneGenerationAdmissionV2
from src.infrastructure.plugins.v2.tool_set import TOOL_SET_CATALOG_SERVICE_V2, TOOL_SET_MODULE_V2
from src.tests.unit.infrastructure.plugins.v2.test_external_wasm_admission import (
    FIXTURE,
)

ROOT = ScopeV2(kind=ScopeKindV2.ROOT)
SCOPE = ScopeV2(
    kind=ScopeKindV2.SESSION, tenant_id="tenant", project_id="project", session_id="session"
)


async def test_builtin_worker_needs_no_archive_repository_or_operator_keys():
    source = production_bundle_sources_v2()
    snapshot = build_profile_snapshot_v2(
        profile_id="builtin-worker",
        generation=1,
        manifests=source.bundle.manifests,
        entries=tuple(e for layer in source.bundle.layers for e in layer.entries),
    )
    assert (
        await load_agent_generation_archives_v2(
            {"snapshot": profile_snapshot_v2_to_payload(snapshot)}, SCOPE
        )
        is None
    )


@pytest.fixture
async def retained(db_session):
    raw = (FIXTURE / "marker.mspkg").read_bytes()
    verified = parse_bundle_archive_v2(
        raw,
        source="fixture://signed-marker",
        trusted_public_keys=((FIXTURE / "signer-public.pem").read_text(),),
        approved_permissions=frozenset({"tools.execute"}),
        require_signature=True,
        require_provenance=True,
    )
    layer = hashlib.sha256(raw).hexdigest()
    oci = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "artifactType": "application/vnd.memstack.plugin.v2",
            "layers": [
                {
                    "mediaType": "application/vnd.memstack.plugin.bundle.v2+zip",
                    "digest": "sha256:" + layer,
                    "size": len(raw),
                }
            ],
        }
    ).encode()
    oci_digest = hashlib.sha256(oci).hexdigest()
    requests = []
    paths = {
        "/v2/qa/marker/manifests/sha256:" + oci_digest: oci,
        "/v2/qa/marker/blobs/sha256:" + layer: raw,
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            content = paths.get(self.path)
            self.send_response(200 if content else 404)
            self.send_header("Content-Length", str(len(content or b"")))
            self.end_headers()
            self.wfile.write(content or b"")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    source = production_bundle_sources_v2()
    module_ids = {RUNTIME_BOUNDARY_MODULE_V2, TOOL_SET_MODULE_V2}
    entries = tuple(
        e for layer in source.bundle.layers for e in layer.entries if e.module_ref in module_ids
    )
    builtin = next(
        m
        for m in source.bundle.manifests
        if any(x.module_ref == TOOL_SET_MODULE_V2 for x in m.modules)
    )
    snapshot = build_profile_snapshot_v2(
        profile_id="external-worker",
        generation=1,
        manifests=(builtin, *verified.manifest.manifests),
        entries=(*entries, *verified.manifest.layers[0].entries),
    )
    envelope = control_envelope_v2(snapshot, version=1)
    reference = BundleReferenceV2(
        bundle_id=verified.manifest.bundle_id,
        version=verified.manifest.version,
        digest=verified.manifest.digest,
        source=f"marketplace://{verified.manifest.bundle_id}/{verified.manifest.version}",
    )
    desired = replace(source.desired_set, bundles=(*source.desired_set.bundles, reference))
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as db:
        db.add(
            PlatformPluginPackageModel(
                plugin_id=reference.bundle_id,
                version=reference.version,
                publisher="qa",
                artifact_digest=layer,
                artifact_registry=origin,
                artifact_repository="qa/marker",
                oci_manifest_digest=oci_digest,
                install_status="installed",
                manifest=bundle_manifest_v2_to_payload(verified.manifest),
                security_scan_status="passed",
                revoked=False,
            )
        )
        await PlatformPluginGovernanceRepository(db).grant_permission(
            plugin_id=reference.bundle_id, permission="tools.execute"
        )
        row = await PlatformPluginRepositoryV2(db).record_requested_distribution(snapshot, envelope)
        await PlatformPluginPublicationSourceRepositoryV2(db).record(
            scope=ROOT, publication_id=row.id, desired_set=desired
        )
        await db.commit()
        payload = row.distribution
    bundle_loader = ScopedInstalledBundleLoaderV2(
        session_factory=factory,
        production_sources=source,
        trusted_public_keys=((FIXTURE / "signer-public.pem").read_text(),),
        allowed_registries=frozenset({origin}),
    )
    loader = PublicationArchiveLoaderV2(session_factory=factory, bundle_loader=bundle_loader)
    try:
        yield loader, payload, requests, factory, reference
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


async def test_real_oci_archives_reach_real_runtime_host_and_failure_preserves_generation(retained):
    loader, payload, requests, _, _ = retained
    definitions = [
        d
        for d in builtin_runtime_definitions_v2()
        if d.module_ref in {RUNTIME_BOUNDARY_MODULE_V2, TOOL_SET_MODULE_V2}
    ]
    admission = DataPlaneGenerationAdmissionV2(definitions, archive_loader=loader)
    try:
        async with admission.admit(
            descriptor_payload=payload["descriptor"],
            distribution_payload=payload,
            operation_id="real-worker",
            scope=SCOPE,
        ) as operation:
            assert operation.require(TOOL_SET_CATALOG_SERVICE_V2) is not None
        original = admission.host.manager.current
        assert len(requests) == 2
        bad = payload | {"envelope": payload["envelope"] | {"nonce": "not-retained"}}
        with pytest.raises(RuntimeV2Error, match="not retained"):
            async with admission.admit(
                descriptor_payload=bad["descriptor"],
                distribution_payload=bad,
                operation_id="bad",
                scope=SCOPE,
            ):
                pass
        assert admission.host.manager.current is original
    finally:
        await admission.close()


async def test_worker_rechecks_governance_for_each_exact_generation_load(retained):
    loader, payload, requests, factory, reference = retained
    assert len(await loader(payload, SCOPE)) == 2
    async with factory() as db:
        package = await PlatformPluginGovernanceRepository(db).get_package_version(
            reference.bundle_id, reference.version
        )
        package.revoked = True
        await db.commit()
    with pytest.raises(ValueError, match="not installed"):
        await loader(payload, SCOPE)
    assert len(requests) == 2


async def test_payload_changed_after_publication_is_rejected_before_oci(retained):
    loader, payload, requests, _, _ = retained
    changed = payload | {"descriptor": payload["descriptor"] | {"generation": 99}}
    with pytest.raises(RuntimeV2Error, match="differs from retained"):
        await loader(changed, SCOPE)
    assert requests == []
