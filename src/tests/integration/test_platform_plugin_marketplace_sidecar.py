"""Live Python-control-plane to Rust-sidecar marketplace lifecycle test."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import io
import json
import queue
import secrets
import subprocess
import threading
import time
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.application.schemas.plugin_marketplace import (
    MarketplaceArtifactSource,
    MarketplacePackageProvenance,
    MarketplacePackageRequest,
    MarketplacePackageSignature,
)
from src.application.services.platform_plugin_profile_service import (
    PlatformPluginProfileService,
)
from src.application.services.plugin_marketplace_catalog_service import (
    PluginMarketplaceCatalogService,
)
from src.application.services.plugin_marketplace_install_service import (
    PluginMarketplaceInstallService,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers import platform_plugins
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginApplyStateModel,
    PlatformPluginPackageModel,
    User,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)
from src.infrastructure.plugins.governance import canonical_plugin_json, sha256_hex
from src.infrastructure.plugins.package_registry import OciPluginArtifactClient

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SIDECAR_BINARY = REPOSITORY_ROOT / "agi-stack/target/debug/agistack-desktop-sidecar"
WORKSPACE_CORE_BINARY = (
    REPOSITORY_ROOT / "agi-stack/apps/desktop/build/workspace-core/memstack-workspace-core"
)
OCI_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
MEMSTACK_ARTIFACT_TYPE = "application/vnd.memstack.plugin.v1"
MEMSTACK_LAYER_MEDIA_TYPE = "application/vnd.memstack.plugin.bundle.v1+zip"


@dataclass
class PackageFixture:
    manifest: dict[str, Any]
    archive: bytes
    manifest_digest: str
    layer_digest: str


@dataclass
class ControlPlaneServer:
    url: str
    thread: threading.Thread
    server: uvicorn.Server


class SidecarProcess:
    def __init__(
        self,
        process: subprocess.Popen[Any],
        lines: queue.Queue[dict[str, Any]],
        diagnostics: list[str],
    ) -> None:
        self.process = process
        self.lines = lines
        self.diagnostics = diagnostics
        self.next_id = 0
        self.ready: dict[str, Any] | None = None

    @property
    def api_base_url(self) -> str:
        assert self.ready is not None
        return str(self.ready["apiBaseUrl"])

    @property
    def launch_token(self) -> str:
        assert self.ready is not None
        return str(self.ready["apiToken"])

    def request(self, command: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.process.stdin is not None
        self.next_id += 1
        request_id = f"python-{self.next_id}"
        payload = {
            "type": "request",
            "id": request_id,
            "command": command,
            **({"args": args} if args is not None else {}),
        }
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                response = self.lines.get(timeout=deadline - time.monotonic())
            except queue.Empty as exc:
                raise AssertionError(f"sidecar command timed out: {command}") from exc
            if response.get("id") != request_id:
                continue
            if not response.get("ok"):
                raise AssertionError(str(response.get("error")))
            return response.get("result")
        raise AssertionError(f"sidecar command timed out: {command}")

    def stop(self) -> None:
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)


def normalized_manifest() -> dict[str, Any]:
    from src.domain.model.plugins import parse_plugin_manifest

    return parse_plugin_manifest(
        {
            "schemaVersion": 1,
            "id": "cross-language-subprocess",
            "version": "1.0.0",
            "runtime": "subprocess",
            "trust": "signed",
            "provides": [
                {
                    "kind": "tool",
                    "id": "demo",
                    "contract": "tool:cross-language-demo",
                    "permissions": ["tools.execute"],
                }
            ],
        }
    ).to_payload()


def package_fixture() -> PackageFixture:
    manifest = normalized_manifest()
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode()
    runtime = json.dumps(
        {
            "command": ["/usr/bin/printf", "cross-language-subprocess-ok"],
            "timeout_ms": 1_000,
        },
        separators=(",", ":"),
    ).encode()
    checksums = {
        "plugin.manifest.json": hashlib.sha256(manifest_bytes).hexdigest(),
        "runtime/plugin.json": hashlib.sha256(runtime).hexdigest(),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("plugin.manifest.json", manifest_bytes)
        archive.writestr("runtime/plugin.json", runtime)
        archive.writestr(
            "checksums.json",
            json.dumps(checksums, separators=(",", ":")),
        )
    layer = output.getvalue()
    manifest_payload = {
        "schemaVersion": 2,
        "mediaType": OCI_MANIFEST_MEDIA_TYPE,
        "artifactType": MEMSTACK_ARTIFACT_TYPE,
        "layers": [
            {
                "mediaType": MEMSTACK_LAYER_MEDIA_TYPE,
                "digest": f"sha256:{sha256_hex(layer)}",
                "size": len(layer),
            }
        ],
    }
    manifest_bytes = json.dumps(manifest_payload, separators=(",", ":")).encode()
    return PackageFixture(
        manifest=manifest,
        archive=layer,
        manifest_digest=sha256_hex(manifest_bytes),
        layer_digest=sha256_hex(layer),
    )


def start_control_plane(
    app: FastAPI,
) -> ControlPlaneServer:
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise AssertionError("Python plugin control plane failed to start")
    sockets = server.servers
    assert sockets is not None and sockets
    address = sockets[0].sockets[0].getsockname()
    return ControlPlaneServer(
        url=f"http://{address[0]}:{address[1]}",
        thread=thread,
        server=server,
    )


def start_sidecar(data_directory: Path, workspace_root: Path) -> SidecarProcess:
    secret = secrets.token_bytes(32)
    nonce = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    encoded_secret = base64.urlsafe_b64encode(secret).rstrip(b"=").decode()
    process = subprocess.Popen(
        [str(SIDECAR_BINARY)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None and process.stdin is not None
    lines: queue.Queue[dict[str, Any]] = queue.Queue()
    diagnostics: list[str] = []

    def read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            with contextlib.suppress(json.JSONDecodeError):
                lines.put(json.loads(line))

    threading.Thread(target=read_stdout, daemon=True).start()
    if process.stderr is not None:

        def read_stderr() -> None:
            assert process.stderr is not None
            for line in process.stderr:
                diagnostics.append(line.rstrip())

        threading.Thread(target=read_stderr, daemon=True).start()
    initialize = {
        "type": "initialize",
        "protocolVersion": 1,
        "nonce": nonce,
        "secret": encoded_secret,
        "dataDirectory": str(data_directory),
        "workspaceRoot": str(workspace_root),
        "workspaceCoreBinaryPath": str(WORKSPACE_CORE_BINARY),
        "legacyDataDirectories": [],
    }
    process.stdin.write(json.dumps(initialize, separators=(",", ":")) + "\n")
    process.stdin.flush()
    sidecar = SidecarProcess(process, lines, diagnostics)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            ready = lines.get(timeout=max(0.1, deadline - time.monotonic()))
        except queue.Empty as exc:
            raise AssertionError("sidecar handshake timed out") from exc
        if ready.get("type") != "ready":
            continue
        message = "\n".join(
            [
                str(ready["protocolVersion"]),
                str(ready["nonce"]),
                str(ready["pid"]),
                str(ready["apiBaseUrl"]),
                str(ready["apiToken"]),
            ]
        ).encode()
        expected = hmac.new(secret, message, hashlib.sha256).digest()
        received = base64.urlsafe_b64decode(str(ready["proof"]) + "===")
        assert hmac.compare_digest(received, expected)
        sidecar.ready = ready
        return sidecar
    raise AssertionError("sidecar handshake timed out")


async def wait_for_receipt(
    session_factory: async_sessionmaker[Any],
    diagnostics: list[str],
    *,
    version: int,
    status: str,
    timeout: float = 95.0,
) -> PlatformPluginApplyStateModel:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with session_factory() as session:
            result = await session.execute(
                select(PlatformPluginApplyStateModel).where(
                    PlatformPluginApplyStateModel.data_plane_id == "desktop-local"
                )
            )
            state = result.scalar_one_or_none()
        if state is not None and state.requested_version == version:
            if state.status == status:
                return state
            raise AssertionError(
                f"sidecar receipt for {version} is {state.status}: {state.error_message}"
            )
        await asyncio.sleep(0.25)
    raise AssertionError(
        f"sidecar receipt did not converge to {version}/{status}; diagnostics={diagnostics[-20:]}"
    )


@pytest.mark.integration
async def test_marketplace_package_moves_through_live_control_plane_and_sidecar(  # noqa: PLR0915
    tmp_path: Path,
) -> None:
    if not SIDECAR_BINARY.is_file() or not WORKSPACE_CORE_BINARY.is_file():
        pytest.skip("sidecar and Workspace Core binaries must be built for this integration test")

    fixture = package_fixture()
    database_path = tmp_path / "control-plane.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        poolclass=NullPool,
    )
    from src.infrastructure.adapters.secondary.persistence.models import Base

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    current_user = User(
        id="cross-language-admin",
        email="cross-language-admin@example.test",
        hashed_password="hashed",
        full_name="Cross Language Admin",
        is_active=True,
        is_superuser=True,
    )

    async def override_db() -> AsyncIterator[Any]:
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(platform_plugins.router)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: current_user

    @app.get("/v2/plugins/manifests/{manifest_digest}")
    async def oci_manifest(manifest_digest: str) -> Response:
        assert manifest_digest == f"sha256:{fixture.manifest_digest}"
        return Response(
            content=json.dumps(
                {
                    "schemaVersion": 2,
                    "mediaType": OCI_MANIFEST_MEDIA_TYPE,
                    "artifactType": MEMSTACK_ARTIFACT_TYPE,
                    "layers": [
                        {
                            "mediaType": MEMSTACK_LAYER_MEDIA_TYPE,
                            "digest": f"sha256:{fixture.layer_digest}",
                            "size": len(fixture.archive),
                        }
                    ],
                },
                separators=(",", ":"),
            ).encode(),
            media_type=OCI_MANIFEST_MEDIA_TYPE,
        )

    @app.get("/v2/plugins/blobs/{layer_digest}")
    async def oci_blob(layer_digest: str) -> Response:
        assert layer_digest == f"sha256:{fixture.layer_digest}"
        return Response(
            content=fixture.archive,
            media_type=MEMSTACK_LAYER_MEDIA_TYPE,
        )

    control_plane = start_control_plane(app)
    try:
        private_key = Ed25519PrivateKey.generate()
        public_pem = (
            private_key.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )
        canonical = json.dumps(fixture.manifest, sort_keys=True, separators=(",", ":")).encode()
        signature_payload = canonical_plugin_json(
            {
                "manifest_digest": sha256_hex(canonical),
                "artifact_digest": fixture.layer_digest,
            }
        )
        request = MarketplacePackageRequest(
            plugin_id="cross-language-subprocess",
            version="1.0.0",
            publisher="memstack",
            tenant_id="cross-language-tenant",
            artifact=MarketplaceArtifactSource(
                registry=control_plane.url,
                repository="plugins",
                manifest_sha256=fixture.manifest_digest,
            ),
            artifact_sha256=fixture.layer_digest,
            manifest=fixture.manifest,
            signature=MarketplacePackageSignature(
                public_key_pem=public_pem,
                signature_base64=base64.b64encode(private_key.sign(signature_payload)).decode(),
            ),
            provenance=MarketplacePackageProvenance(
                predicate_type="https://slsa.dev/provenance/v1",
                builder_id="https://builder.memstack.test",
                subject_name="cross-language-subprocess",
            ),
            approved_permissions=frozenset({"tools.execute"}),
            tenant_admin_approved=True,
            security_scan_passed=True,
        )
        async with session_factory() as session, httpx.AsyncClient() as client:
            install = PluginMarketplaceInstallService(
                PlatformPluginGovernanceRepository(session),
                PlatformPluginRepository(session),
                OciPluginArtifactClient(client),
                trusted_public_keys=(public_pem,),
            )
            decision = await install.request_install(request=request)
            await session.commit()
        assert decision.status == "approved", decision.reason

        async with session_factory() as session:
            publication = await PlatformPluginProfileService(
                PlatformPluginRepository(session)
            ).publish(version=101, nonce="cross-language-install-101")
            await session.commit()

        sidecar = start_sidecar(tmp_path / "sidecar", tmp_path / "workspace")
        try:
            sidecar.request(
                "trusted_session_save",
                {
                    "input": {
                        "version": 1,
                        "api_base_url": f"{control_plane.url}/api/v1",
                        "runtime_mode": "cloud",
                        "credential_kind": "cloud_bearer",
                        "credential": "cross-language-cloud-bearer",
                        "expires_at": None,
                    }
                },
            )
            receipt = await wait_for_receipt(
                session_factory,
                diagnostics=sidecar.diagnostics,
                version=101,
                status="ack",
            )
            assert receipt.error_message is None

            async with httpx.AsyncClient() as client:
                local_session = await client.post(
                    f"{sidecar.api_base_url}/api/v1/auth/local-session",
                    headers={"X-Agistack-Launch": sidecar.launch_token},
                    json={"trusted_device": True},
                )
                local_session.raise_for_status()
                access_token = local_session.json()["access_token"]
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "X-Agistack-Launch": sidecar.launch_token,
                }
                apply_state = await client.get(
                    f"{sidecar.api_base_url}/api/v1/platform-plugins/apply-state",
                    headers=headers,
                )
                apply_state.raise_for_status()
                assert apply_state.json()["active_plugins"][0]["plugin_id"] == (
                    "cross-language-subprocess"
                )
                invocation = await client.post(
                    f"{sidecar.api_base_url}/api/v1/platform-plugins/tools/invoke",
                    headers=headers,
                    json={
                        "plugin_id": "cross-language-subprocess",
                        "tool_id": "demo",
                        "input": {},
                    },
                )
                invocation.raise_for_status()
                assert invocation.json()["stdout"] == "cross-language-subprocess-ok"

            async with session_factory() as session:
                catalog = PluginMarketplaceCatalogService(
                    PlatformPluginGovernanceRepository(session),
                    PlatformPluginRepository(session),
                )
                uninstall = await catalog.uninstall(
                    plugin_id="cross-language-subprocess",
                    version="1.0.0",
                )
                assert uninstall.desired_removed is True
                await PlatformPluginProfileService(PlatformPluginRepository(session)).publish(
                    version=102, nonce="cross-language-uninstall-102"
                )
                await session.commit()
            await wait_for_receipt(
                session_factory,
                diagnostics=sidecar.diagnostics,
                version=102,
                status="ack",
            )

            async with httpx.AsyncClient() as client:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "X-Agistack-Launch": sidecar.launch_token,
                }
                apply_state = await client.get(
                    f"{sidecar.api_base_url}/api/v1/platform-plugins/apply-state",
                    headers=headers,
                )
                apply_state.raise_for_status()
                assert all(
                    plugin["plugin_id"] != "cross-language-subprocess"
                    for plugin in apply_state.json()["active_plugins"]
                )
                removed = await client.post(
                    f"{sidecar.api_base_url}/api/v1/platform-plugins/tools/invoke",
                    headers=headers,
                    json={
                        "plugin_id": "cross-language-subprocess",
                        "tool_id": "demo",
                        "input": {},
                    },
                )
                assert removed.status_code == 404

            async with session_factory() as session:
                catalog = PluginMarketplaceCatalogService(
                    PlatformPluginGovernanceRepository(session),
                    PlatformPluginRepository(session),
                )
                revoke = await catalog.revoke(
                    plugin_id="cross-language-subprocess",
                    reason="cross-language lifecycle complete",
                )
                await session.commit()
            assert revoke.revoked_versions == ("1.0.0",)
            async with session_factory() as session:
                package = await session.get(
                    PlatformPluginPackageModel,
                    ("cross-language-subprocess", "1.0.0"),
                )
                assert package is not None and package.revoked is True
        finally:
            sidecar.stop()
        assert publication.envelope.version == 101
    finally:
        control_plane.server.should_exit = True
        control_plane.thread.join(timeout=10)
        await engine.dispose()
