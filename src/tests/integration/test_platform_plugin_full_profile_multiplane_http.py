"""Full production profile, real ROOT publication and independent Desktop receipts."""

import asyncio
import socket
from dataclasses import replace
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI

from src.domain.model.plugins.generated_v2 import (
    ProfileLayerKindV2,
    ProfileLayerV2,
    ProfileSourceReferenceV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_data_plane_credential_repository_v2 import (
    PlatformPluginDataPlaneCredentialRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.layer_composer import (
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.tests.integration import (
    test_platform_plugin_desktop_multiplane_http as transport,
    test_root_startup_postgres as root_support,
)
from src.tests.unit.application.services.test_root_admin_republish_v2 import (
    _install_http,
    _publisher,
)
from src.tests.unit.infrastructure.adapters.primary.web.startup.test_root_profile_startup_v2 import (
    exact_source,
)

root_sessions = root_support.root_sessions
pytestmark = pytest.mark.integration
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)
RUNNER = (
    Path(__file__).resolve().parents[3]
    / "agi-stack/apps/desktop/tests/support/renderer-production-multiplane-runner.mjs"
)


async def _disable_target_provider(sessions, original, entry_id):
    record, current = await exact_source(sessions)
    source = replace(
        original,
        revision=current.revision + 1,
        layers=(
            *original.layers,
            ProfileLayerV2(
                layer_id=f"full-profile-rejection-{current.revision}",
                kind=ProfileLayerKindV2.PROFILE,
                scope=ROOT,
                entries=(),
                replacements=(),
                disabled_entry_ids=(entry_id,),
            ),
        ),
    )
    source = replace(source, digest=profile_source_digest_v2(source))
    desired = replace(
        record.desired_set,
        revision=record.desired_set.revision + 1,
        profile_source=ProfileSourceReferenceV2(
            source_id=source.source_id, revision=source.revision, digest=source.digest
        ),
    )
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    async with sessions() as session:
        await PlatformPluginProfileSourceRepositoryV2(session).record_source(
            scope=ROOT, source=source, expected_revision=current.revision
        )
        await PlatformPluginDesiredBundleSetRepositoryV2(session).record_desired_set(
            scope=ROOT,
            desired_set=desired,
            expected_revision=record.desired_set.revision,
            actor_id="full-profile-acceptance",
        )
        await session.commit()


async def test_full_production_three_plane_http(root_sessions):  # noqa: PLR0912, PLR0915
    sessions = root_sessions
    app = FastAPI()
    _install_http(app, sessions)
    policy = PlatformPluginPublicationPolicyV2(
        required_data_plane_ids=("python-api-v2", "desktop-sidecar-v2", "desktop-renderer-v2"),
        ack_deadline_seconds=90,
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(
        uvicorn.Config(app, lifespan="off", access_log=False, log_level="critical")
    )
    serving = process = stderr_drain = None
    try:
        host = await initialize_plugin_runtime_v2(
            app, session_factory=sessions, publication_policy=policy
        )
        initial = host.current_publication
        assert initial is not None and initial.accepted
        expected = transport.json.loads(
            (transport._ROOT / "shared/profiles/memstack-default-bootstrap.v2.json").read_text()
        )
        assert {entry.entry_id for entry in initial.snapshot.entries} == {
            entry["entry_id"] for entry in expected["entries"]
        }
        _, original = await exact_source(sessions)
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        async with asyncio.timeout(10):
            while not server.started:
                if serving.done():
                    await serving
                await asyncio.sleep(0.01)
        async with sessions() as session:
            credentials = PlatformPluginDataPlaneCredentialRepositoryV2(session)
            sidecar = await credentials.issue(
                data_plane_id="desktop-sidecar-v2", actor_id="full-profile"
            )
            renderer = await credentials.issue(
                data_plane_id="desktop-renderer-v2", actor_id="full-profile"
            )
            await session.commit()
        process = await asyncio.create_subprocess_exec(
            "node",
            str(RUNNER),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stderr_drain = asyncio.create_task(transport._discard_output(process.stderr))
        await transport._exchange(
            process,
            {"command": "init", "base_url": base_url, "renderer_credential": renderer.secret},
        )
        await transport._exchange(
            process,
            {
                "command": "enable_sidecar",
                "base_url": base_url,
                "sidecar_credential": sidecar.secret,
            },
        )
        first_nonce = initial.envelope.nonce
        retained_renderer = None
        retained_planes = {}
        cases = (
            (None, "ack", "ack"),
            ("builtin-desktop-sidecar-http-routes", "nack", "ack"),
            ("builtin-desktop-renderer-contribution-registry", "ack", "nack"),
        )
        for entry_id, sidecar_status, renderer_status in cases:
            if entry_id:
                assert any(e.entry_id == entry_id for e in initial.snapshot.entries)
                await _disable_target_provider(sessions, original, entry_id)
                async with sessions() as session:
                    publication = (
                        await _publisher(app, host, session, sessions).publish_current()
                    ).publication
            else:
                publication = initial
            assert publication.accepted
            result = await transport._exchange(
                process,
                {
                    "command": "apply",
                    "version": publication.envelope.version,
                    "expected_renderer_status": renderer_status,
                },
            )
            assert result["receipt"]["status"] == renderer_status
            expected = {
                "python-api-v2": "ack",
                "desktop-sidecar-v2": sidecar_status,
                "desktop-renderer-v2": renderer_status,
            }
            readiness = await transport._wait_receipts(
                sessions, publication.envelope.nonce, expected
            )
            assert readiness.status.value == ("ready" if entry_id is None else "degraded")
            for plane in readiness.data_planes:
                assert plane.requested_digest == publication.snapshot.digest
                assert plane.requested_version == publication.envelope.version
                if plane.status.value == "ack":
                    assert (plane.applied_version, plane.applied_digest) == (
                        publication.envelope.version,
                        publication.snapshot.digest,
                    )
                    retained_planes[plane.data_plane_id] = (
                        plane.applied_version,
                        plane.applied_digest,
                    )
                else:
                    assert plane.error_code
                    assert (plane.applied_version, plane.applied_digest) == retained_planes[
                        plane.data_plane_id
                    ]
            if renderer_status == "nack":
                assert result["active_digest"] == retained_renderer
            else:
                retained_renderer = publication.snapshot.digest
            async with sessions() as session:
                first = await PlatformPluginRepositoryV2(session).publication_readiness(first_nonce)
                assert first.ready_at is not None
    finally:
        if process is not None:
            try:
                await transport._exchange(process, {"command": "close"})
                await asyncio.wait_for(process.wait(), 15)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                if stderr_drain is not None:
                    await stderr_drain
        server.should_exit = True
        if serving is not None:
            await asyncio.wait_for(serving, 10)
        listener.close()
        await shutdown_plugin_runtime_v2(app)
