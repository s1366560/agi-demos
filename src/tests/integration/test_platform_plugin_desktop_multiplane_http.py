"""Real Desktop processes report independent receipts through production HTTP and PostgreSQL."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import socket
import uuid
from collections.abc import AsyncIterator
from copy import deepcopy
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.domain.model.plugins.generated_v2 import PublicationStatusV2
from src.infrastructure.adapters.primary.web.routers import platform_plugins
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_data_plane_credential_repository_v2 import (
    PlatformPluginDataPlaneCredentialRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.protocol import (
    canonical_json_v2,
    control_envelope_v2,
    parse_profile_snapshot_v2,
    snapshot_apply_receipt_v2_to_payload,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]
_ROOT = Path(__file__).resolve().parents[3]
_RUNNER = _ROOT / "agi-stack/apps/desktop/tests/support/renderer-multiplane-runner.mjs"
_SIDECAR = "desktop-sidecar-v2"
_RENDERER = "desktop-renderer-v2"
_REFS = {
    "builtin://memstack/runtime/generation-boundary",
    "builtin://memstack/desktop-sidecar/http-routes",
    "builtin://memstack/desktop-sidecar/local-capability",
    "builtin://memstack/desktop/renderer-host",
}


@pytest.fixture
async def loopback_control_plane() -> AsyncIterator[tuple]:
    database_url = os.getenv("PLATFORM_PLUGIN_V2_POSTGRES_TEST_URL")
    required = [
        os.getenv(name) for name in ("AGISTACK_REAL_SIDECAR", "AGISTACK_REAL_WORKSPACE_CORE")
    ]
    if not database_url or not all(required) or not shutil.which("node") or not _RUNNER.is_file():
        pytest.skip(
            "Explicit isolated PostgreSQL URL and real Desktop binaries/runner are required"
        )
    if not all(Path(value).is_file() for value in required if value):
        pytest.skip("Real Desktop binary paths must exist")
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    app = FastAPI()
    app.include_router(platform_plugins.router)

    async def scoped_db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = scoped_db
    server = uvicorn.Server(
        uvicorn.Config(app, access_log=False, log_level="critical", lifespan="off")
    )
    serving = None
    try:
        async with engine.connect() as connection:
            assert connection.dialect.name == "postgresql"
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        async with asyncio.timeout(10):
            while not server.started:
                if serving.done():
                    await serving
                    raise AssertionError("Loopback control plane did not start")
                await asyncio.sleep(0.01)
        yield sessions, f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        server.should_exit = True
        if serving is not None:
            await asyncio.wait_for(serving, 10)
        listener.close()
        await engine.dispose()


def _snapshot(version: int, rejected_target: str | None):
    payload = json.loads((_ROOT / "shared/profiles/memstack-default-bootstrap.v2.json").read_text())
    payload["entries"] = [entry for entry in payload["entries"] if entry["module_ref"] in _REFS]
    payload["generation"] = version
    if rejected_target is not None:
        template_ref = (
            "builtin://memstack/desktop-sidecar/http-routes"
            if rejected_target == "desktop-sidecar"
            else "builtin://memstack/desktop/renderer-host"
        )
        entry = deepcopy(
            next(item for item in payload["entries"] if item["module_ref"] == template_ref)
        )
        manifest = next(
            item for item in payload["manifests"] if item["plugin_id"] == entry["plugin_ref"]
        )
        module = deepcopy(
            next(item for item in manifest["modules"] if item["module_ref"] == template_ref)
        )
        module["module_ref"] += "-integration-unknown"
        module["targets"] = [rejected_target]
        manifest["modules"].append(module)
        entry["module_ref"] = module["module_ref"]
        entry["entry_id"] += "-integration-unknown"
        entry["parent_entry_id"] = None
        payload["entries"].append(entry)
    payload.pop("digest")
    payload["digest"] = hashlib.sha256(canonical_json_v2(payload)).hexdigest()
    return parse_profile_snapshot_v2(payload)


async def _exchange(process, message):
    process.stdin.write(json.dumps(message).encode() + b"\n")
    await process.stdin.drain()
    async with asyncio.timeout(90):
        raw = await process.stdout.readline()
    # Never expose arbitrary child output: it may contain credential-bearing diagnostics.
    try:
        response = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise AssertionError("Desktop runner returned invalid protocol output") from None
    assert response.get("ok") is True, "Desktop runner rejected the operation (output suppressed)"
    return response


async def _discard_output(stream):
    while await stream.read(4096):
        pass


async def _wait_receipts(sessions, nonce, expected):
    async with asyncio.timeout(100):
        while True:
            async with sessions() as session:
                readiness = await PlatformPluginRepositoryV2(session).publication_readiness(nonce)
                await session.commit()
            actual = {
                plane.data_plane_id: None if plane.status is None else plane.status.value
                for plane in readiness.data_planes
            }
            if actual == expected:
                return readiness
            await asyncio.sleep(0.1)


async def test_real_sidecar_and_renderer_independently_ack_and_nack_over_http(  # noqa: PLR0912, PLR0915
    loopback_control_plane,
):
    sessions, base_url = loopback_control_plane
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    suffix = uuid.uuid4().hex
    policy = PlatformPluginPublicationPolicyV2(
        required_data_plane_ids=(PYTHON_API_DATA_PLANE_ID_V2, _SIDECAR, _RENDERER),
        ack_deadline_seconds=90,
    )
    process = None
    stderr_drain = None
    try:
        async with sessions() as session:
            latest = await session.scalar(
                select(
                    func.coalesce(func.max(PlatformPluginV2PublicationModel.requested_version), 0)
                )
            )
            initial_version = int(latest or 0) + 1
            credentials = PlatformPluginDataPlaneCredentialRepositoryV2(session)
            sidecar = await credentials.issue(
                data_plane_id=_SIDECAR, actor_id="isolated-http-fixture"
            )
            renderer = await credentials.issue(
                data_plane_id=_RENDERER, actor_id="isolated-http-fixture"
            )
            await session.commit()
        first_id = None
        first_digest = None
        previous_renderer_digest = None
        for offset, rejected_target, expected in (
            (0, None, {PYTHON_API_DATA_PLANE_ID_V2: "ack", _SIDECAR: "ack", _RENDERER: "ack"}),
            (
                1,
                "desktop-sidecar",
                {PYTHON_API_DATA_PLANE_ID_V2: "ack", _SIDECAR: "nack", _RENDERER: "ack"},
            ),
            (
                2,
                "desktop-renderer",
                {PYTHON_API_DATA_PLANE_ID_V2: "ack", _SIDECAR: "ack", _RENDERER: "nack"},
            ),
        ):
            version = initial_version + offset
            snapshot = _snapshot(version, rejected_target)
            nonce = f"desktop-http-{suffix}-{offset}"
            publication = await host.apply(
                snapshot, control_envelope_v2(snapshot, version=version, nonce=nonce)
            )
            assert publication.accepted, (
                "Python must accept a candidate rejected only by another target"
            )
            async with sessions() as session:
                ledger = await PlatformPluginRepositoryV2(session).record_publication_and_receipt(
                    publication, data_plane_id=PYTHON_API_DATA_PLANE_ID_V2, policy=policy
                )
                row = ledger.publication
                if offset == 0:
                    first_id, first_digest = row.id, snapshot.digest
                await session.commit()
            if process is None:
                async with AsyncClient(base_url=base_url) as client:
                    path = "/api/v1/platform-plugins/v2/distribution"
                    assert (await client.get(path)).status_code == 401
                    invalid = await client.get(
                        path, headers={"Authorization": "Bearer ms_dp_invalid-fixture"}
                    )
                    assert invalid.status_code == 401
                    forged = await client.post(
                        "/api/v1/platform-plugins/v2/data-plane-state",
                        headers={"Authorization": f"Bearer {sidecar.secret}"},
                        json={
                            "schema_version": 2,
                            "data_plane_id": _RENDERER,
                            "nonce": nonce,
                            "receipt": snapshot_apply_receipt_v2_to_payload(publication.receipt),
                        },
                    )
                    assert forged.status_code == 403
                    assert forged.json()["detail"]["code"] == "plugin_data_plane_identity_mismatch"
                process = await asyncio.create_subprocess_exec(
                    "node",
                    str(_RUNNER),
                    cwd=_ROOT,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stderr_drain = asyncio.create_task(_discard_output(process.stderr))
                await _exchange(
                    process,
                    {
                        "command": "init",
                        "base_url": base_url,
                        "renderer_credential": renderer.secret,
                    },
                )
            result = await _exchange(
                process,
                {
                    "command": "apply",
                    "version": version,
                    "expected_renderer_status": expected[_RENDERER],
                },
            )
            assert result["receipt"]["status"] == expected[_RENDERER]
            if offset == 0:
                renderer_only = await _wait_receipts(
                    sessions,
                    nonce,
                    {PYTHON_API_DATA_PLANE_ID_V2: "ack", _SIDECAR: None, _RENDERER: "ack"},
                )
                assert renderer_only.status is PublicationStatusV2.RECONCILING
                assert renderer_only.ready_at is None
                async with sessions() as session:
                    persisted = await session.get(PlatformPluginV2PublicationModel, first_id)
                    assert persisted is not None
                    assert persisted.status == PublicationStatusV2.RECONCILING.value
                    assert persisted.ready_at is None
                await _exchange(
                    process,
                    {
                        "command": "enable_sidecar",
                        "base_url": base_url,
                        "sidecar_credential": sidecar.secret,
                    },
                )
            readiness = await _wait_receipts(sessions, nonce, expected)
            assert readiness.status is (
                PublicationStatusV2.READY if offset == 0 else PublicationStatusV2.DEGRADED
            )
            assert set(readiness.required_data_plane_ids) == {
                PYTHON_API_DATA_PLANE_ID_V2,
                _SIDECAR,
                _RENDERER,
            }
            for plane in readiness.data_planes:
                assert plane.requested_version == version
                assert plane.requested_digest == snapshot.digest
                if plane.status.value == "ack":
                    assert plane.applied_version == version
                    assert plane.applied_digest == snapshot.digest
                else:
                    assert plane.error_code
                    assert plane.applied_version == initial_version + (1 if offset == 2 else 0)
            if offset == 2:
                assert result["active_digest"] == previous_renderer_digest
            else:
                previous_renderer_digest = snapshot.digest
            async with sessions() as session:
                last_ready = await session.scalar(
                    select(PlatformPluginV2PublicationModel)
                    .where(PlatformPluginV2PublicationModel.ready_at.is_not(None))
                    .order_by(PlatformPluginV2PublicationModel.requested_version.desc())
                    .limit(1)
                )
                assert last_ready is not None
                assert last_ready.id == first_id and last_ready.snapshot_digest == first_digest
    finally:
        if process is not None:
            try:
                await _exchange(process, {"command": "close"})
                await asyncio.wait_for(process.wait(), 15)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                if stderr_drain is not None:
                    await stderr_drain
        await host.close()
