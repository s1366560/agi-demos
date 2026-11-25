"""Verify an SDK-signed worker against an ephemeral OCI registry and a real Docker daemon."""

import asyncio
import json
import os
import secrets
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import docker
from src.infrastructure.plugins.sdk_path import ensure_plugin_sdk_path
from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
from src.infrastructure.plugins.v2.oci_mcp_worker import OciWorkerSession, OciWorkerSpec
from src.infrastructure.plugins.v2.signed_optional_business_v2 import ScopeBindingV2

ensure_plugin_sdk_path()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("OCI_WORKER_DOCKER_TESTS") != "1", reason="requires Docker daemon"
    ),
]

INPUT = {
    "type": "object",
    "properties": {"wait": {"type": "boolean"}},
    "additionalProperties": False,
}
OUTPUT = {
    "type": "object",
    "properties": {
        "uid": {"type": "integer"},
        "writable": {"type": "boolean"},
        "connected": {"type": "boolean"},
        "inherited": {"type": "boolean"},
    },
    "required": ["uid", "writable", "connected", "inherited"],
}
DOC = {
    "schema": "memstack.plugin.contributions/1",
    "tools": [
        {
            "name": "probe",
            "abi": "mcp.stdio",
            "input_schema": INPUT,
            "output_schema": OUTPUT,
            "permissions": ["tools.execute"],
        }
    ],
}

GUEST = """#!/usr/local/bin/python
import json, os, socket, sys, time
def send(obj):
    print(json.dumps({"jsonrpc": "2.0", **obj}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    params = req.get("params", {})
    method = req["method"]
    if method == "initialize":
        result = {"protocolVersion": params["protocolVersion"], "capabilities": {"tools": {}}}
    elif method == "tools/list":
        result = {"tools":[{"name":"probe","inputSchema":INPUT,"outputSchema":OUTPUT}]}
    elif method == "tools/call":
        if "_meta" in params:
            send({"method":"notifications/progress","params":{"progressToken":params["_meta"]["progressToken"],"progress":1,"total":2.5,"message":"working"}})
        if params["arguments"].get("wait"):
            time.sleep(60)
        try:
            with open("/tmp/probe", "w") as f:
                f.write("test")
            writable = True
        except OSError:
            writable = False
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            routed = probe.connect_ex(("192.0.2.1", 9)) == 0
        result = {"structuredContent":{"uid":os.getuid(),"writable":writable,
            "connected": routed,
            "inherited":"TEST_WORKER_CONTROL_TOKEN" in os.environ or os.path.exists("/var/run/docker.sock")}}
    else:
        continue
    send({"id":req["id"], "result":result})
"""


def _registry_address(registry):
    # The daemon pushes from its own VM on Docker Desktop. Let the registry bind
    # port zero on that VM's loopback and read the address of the open listener.
    marker = "listening on 127.0.0.1:"
    for _ in range(80):
        registry.reload()
        logs = registry.logs(tail=20).decode()
        if registry.status == "exited":
            pytest.fail(f"dedicated QA registry exited: {logs}")
        for line in logs.splitlines():
            if line.startswith("{"):
                message = json.loads(line).get("msg", "")
                if message.startswith(marker) and (port := message.removeprefix(marker)).isdigit():
                    return f"127.0.0.1:{int(port)}"
        time.sleep(0.1)
    pytest.fail("dedicated QA registry did not report its listening address")


@contextmanager
def disposable_worker_registry():
    engine = docker.from_env(timeout=60)
    registry = engine.containers.run(
        "registry:2",
        detach=True,
        network_mode="host",
        environment={"REGISTRY_HTTP_ADDR": "127.0.0.1:0", "REGISTRY_LOG_FORMATTER": "json"},
    )
    repos = []
    try:
        host = _registry_address(registry)
        url = f"http://{host}"

        def publish(source):
            repo = f"{host}/qa/worker-{uuid4().hex}"
            repos.append(repo)
            engine.images.build(path=str(source), tag=repo, rm=True)
            events = list(engine.images.push(repo, tag="latest", stream=True, decode=True))
            assert not any("error" in event for event in events), [
                e.get("error") for e in events if "error" in e
            ]
            # Registry inspection works with both Docker image stores, including push
            # implementations that omit the optional aux event from the progress stream.
            digest = engine.images.get_registry_data(repo + ":latest").id
            image = f"{repo}@{digest}"
            engine.images.remove(repo + ":latest")
            return image

        yield publish, url, engine
    finally:
        for repo in repos:
            for img in engine.images.list(name=repo):
                for tag in img.tags:
                    if tag.startswith(repo + ":"):
                        engine.images.remove(tag)
            for img in engine.images.list():
                for name in img.attrs.get("RepoDigests", []) or []:
                    if name.split("@")[0] == repo:
                        engine.images.remove(name)
        registry.remove(force=True, v=True)
        engine.close()


@pytest.fixture
def worker_image(tmp_path):
    with disposable_worker_registry() as (publish, url, engine):
        (tmp_path / "Dockerfile").write_text("FROM python:3.12-alpine\nCOPY worker /app/worker\n")
        worker = tmp_path / "worker"
        worker.write_text(GUEST.replace("INPUT", repr(INPUT)).replace("OUTPUT", repr(OUTPUT)))
        worker.chmod(0o755)
        yield publish(tmp_path), url, engine


def signed_worker(
    directory: Path,
    image: str,
    scope: ScopeBindingV2,
    *,
    plugin_id="qa-worker",
    command=None,
    contribution=None,
    quotas=None,
):
    from memstack_plugin_sdk.pack import build

    descriptor = {
        "schema": "memstack.mcp-oci-worker/1",
        "image": image,
        "entrypoint": "/app/worker",
    }
    (directory / "worker.json").write_text(json.dumps(descriptor))
    contribution = DOC if contribution is None else contribution
    if command is not None:
        contribution = {**contribution, "commands": [command]}
    (directory / "contributions.json").write_text(json.dumps(contribution))
    config = directory / "package.json"
    config.write_text(
        json.dumps(
            {
                "plugin_id": plugin_id,
                "version": "1.0.0",
                "target": "python",
                "tool_name": "probe",
                "quotas": quotas or {},
                "contribution": "contributions.json",
                "worker": "worker.json",
                "provenance": "repo://qa",
            }
        )
    )
    signer = Ed25519PrivateKey.generate()
    key = (
        signer.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    raw = build(config, signer)
    archive = parse_bundle_archive_v2(
        raw,
        source="qa",
        trusted_public_keys=[key],
        approved_permissions=frozenset({"tools.execute"}),
        require_signature=True,
    )
    descriptor_id = next(
        a.artifact_id for a in archive.manifest.artifacts if a.path == "artifacts/worker.json"
    )
    spec = OciWorkerSpec.from_archive(archive, raw=archive.artifacts[descriptor_id], scope=scope)
    return spec, archive.manifest.digest, descriptor, raw, key


async def test_signed_release_probes_runs_cancels_and_removes_isolated_worker(
    worker_image, tmp_path, monkeypatch
):
    image, registry, engine = worker_image
    scope = ScopeBindingV2(tenant_id="tenant-qa", project_id="project-qa")
    spec, digest, descriptor, _, _ = signed_worker(tmp_path, image, scope)
    from memstack_plugin_sdk.contract import parse_contribution

    tools = parse_contribution(DOC).tools
    monkeypatch.setenv("TEST_WORKER_CONTROL_TOKEN", "test-only")
    options = {
        "scope": scope,
        "release_digest": digest,
        "allowed_registries": frozenset({registry}),
        "wall_time_ms": 5000,
        "max_output_bytes": 1024,
    }
    for candidate, overrides in (
        (OciWorkerSpec.parse(json.dumps(descriptor).encode()), {}),
        (spec, {"scope": ScopeBindingV2(tenant_id=scope.tenant_id, project_id="other")}),
        (spec, {"allowed_registries": frozenset()}),
        (spec, {"release_digest": "other"}),
    ):
        with pytest.raises(ValueError):
            async with OciWorkerSession.open(candidate, **(options | overrides)):
                pytest.fail("an unapproved invocation reached Docker")
    async with OciWorkerSession.open(spec, **options) as worker:
        await worker.prepare(tools)
        classes = engine.containers.list(filters={"label": f"memstack.release={digest}"})
        assert len(classes) == 1
        host_config = classes[0].attrs["HostConfig"]
        assert host_config["ReadonlyRootfs"] and host_config["NetworkMode"] == "none"
        assert host_config["CapDrop"] == ["ALL"] and host_config["PidsLimit"] == 32
        assert "no-new-privileges:true" in host_config["SecurityOpt"]
        assert not classes[0].attrs["Mounts"]
        assert await worker.invoke("probe", {}) == {
            "uid": 65532,
            "writable": False,
            "connected": False,
            "inherited": False,
        }
        progressed = asyncio.Event()

        async def progress(update):
            assert update == {"progress": 1, "total": 2.5, "message": "working"}
            progressed.set()

        task = asyncio.create_task(worker.invoke("probe", {"wait": True}, progress))
        await asyncio.wait_for(progressed.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not engine.containers.list(all=True, filters={"label": f"memstack.release={digest}"})


async def test_crash_recovery_authenticates_expired_container_name_and_deployment(
    worker_image, tmp_path, monkeypatch
):
    from src.host.runtime import oci_mcp_lease

    image, registry, engine = worker_image
    scope = ScopeBindingV2(tenant_id="tenant-qa", project_id="scope-qa")
    spec, digest, _, _, _ = signed_worker(tmp_path, image, scope)
    key = secrets.token_bytes(32)
    monkeypatch.setattr(oci_mcp_lease, "_deployment_key", lambda: key)
    monkeypatch.setattr(oci_mcp_lease, "_LIFETIME", -1)
    async with OciWorkerSession.open(
        spec,
        scope=scope,
        release_digest=digest,
        allowed_registries=frozenset({registry}),
        wall_time_ms=1000,
        max_output_bytes=1024,
    ):
        active = engine.containers.list(filters={"label": f"memstack.release={digest}"})[0]
        other = engine.containers.create(image, labels=active.labels)
        try:
            # A copied ownership label on another container does not authorize deletion.
            assert await asyncio.to_thread(oci_mcp_lease.reclaim_expired_workers, engine) == 1
            other.reload()
            assert other.status == "created"
            assert await asyncio.to_thread(oci_mcp_lease.reclaim_expired_workers, engine) == 0
        finally:
            other.remove(force=True, v=True)
