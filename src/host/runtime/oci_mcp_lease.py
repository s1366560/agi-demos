"""Reclaim expired OCI workers owned by this deployment after a provisioner crash."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from docker.client import from_env
from docker.errors import APIError, DockerException, NotFound

from src.configuration.config import Settings, get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from docker.client import DockerClient
    from docker.models.containers import Container

logger = logging.getLogger(__name__)
_PREFIX = "memstack.oci-worker."
_LABELS = ("tenant", "project", "release", "deadline")
_LIFETIME = (
    120  # Covers container startup, MCP initialize/discovery, and the capped 30s guest call.
)


def _deployment_key() -> bytes:
    secret = get_settings().secret_key
    if secret != Settings.model_fields["secret_key"].default and secret:
        return hmac.digest(secret.encode(), b"memstack:oci-worker-ownership:v1", "sha256")
    # A development installation with the public example API secret needs its own recovery key.
    directory = Path(os.getenv("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "memstack"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / "oci-worker-ownership.key"
    if not path.exists():
        with tempfile.NamedTemporaryFile(dir=directory) as target:
            target.write(secrets.token_bytes(32))
            target.flush()
            os.fsync(target.fileno())
            with contextlib.suppress(FileExistsError):
                os.link(target.name, path)
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError("invalid worker deployment ownership key")
    return key


def _mac(key: bytes, daemon: str, name: str, labels: Mapping[str, str]) -> str:
    fields = [daemon, name, *(labels.get(_PREFIX + field, "") for field in _LABELS)]
    return hmac.new(key, json.dumps(fields).encode(), hashlib.sha256).hexdigest()


def worker_ownership(
    daemon: str, tenant: str, project: str, release: str
) -> tuple[str, dict[str, str]]:
    key = _deployment_key()
    name = "memstack-worker-" + uuid4().hex
    labels = {
        _PREFIX + "tenant": tenant,
        _PREFIX + "project": project,
        _PREFIX + "release": release,
        _PREFIX + "deadline": str(int(time.time()) + _LIFETIME),
        _PREFIX + "owner": hmac.digest(key, daemon.encode(), "sha256").hex(),
    }
    labels[_PREFIX + "mac"] = _mac(key, daemon, name, labels)
    return name, labels


def remove_worker_container(container: Container) -> None:
    try:
        try:
            container.remove(force=True, v=True)
        except APIError as exc:
            if exc.status_code != 409 or "already in progress" not in str(exc.explanation):
                raise
        container.wait(condition="removed", timeout=5)
    except NotFound:
        pass


def reclaim_expired_workers(client: DockerClient) -> int:
    key = _deployment_key()
    daemon = client.info()["ID"]
    owner = hmac.digest(key, daemon.encode(), "sha256").hex()
    candidates = client.containers.list(
        all=True, filters={"label": _PREFIX + "owner=" + owner}, ignore_removed=True
    )
    removed = 0
    for container in candidates:
        labels = container.labels
        mac = labels.get(_PREFIX + "mac", "")
        if not container.name or not hmac.compare_digest(
            _mac(key, daemon, container.name, labels), mac
        ):
            continue
        if int(labels[_PREFIX + "deadline"]) <= time.time():
            remove_worker_container(container)
            removed += 1
    return removed


def _recover() -> None:
    client = from_env(timeout=10)
    try:
        reclaim_expired_workers(client)
    finally:
        client.close()


@contextlib.asynccontextmanager
async def worker_recovery(enabled: bool) -> AsyncIterator[None]:
    async def reap() -> None:
        while True:
            try:
                await asyncio.to_thread(_recover)
            except (DockerException, OSError, ValueError):
                logger.warning("Worker lease recovery unavailable", exc_info=True)
            await asyncio.sleep(30)

    task = asyncio.create_task(reap()) if enabled else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
