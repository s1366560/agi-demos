"""Scoped snapshot registry and transaction leases for explicit cloud cache cleanup."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import shlex
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.ports.services.sandbox_resource_port import SandboxResourcePort
from src.infrastructure.adapters.secondary.persistence.models import MCPServer
from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)

logger = logging.getLogger(__name__)

PREFLIGHT_TTL_SECONDS = 24 * 60 * 60


def preflight_expiry(now: float | None = None) -> float:
    return (time.time() if now is None else now) + PREFLIGHT_TTL_SECONDS


def require_fresh_preflight(payload: dict[str, Any], now: float | None = None) -> None:
    expiry = payload.get("expires_at")
    if not isinstance(expiry, (int, float)) or expiry <= (time.time() if now is None else now):
        raise ValueError("Preflight expired; review the current package again")


def validate_runtime_root(root: str) -> str:
    prefix = "/workspace/.memstack/plugins/"
    if not root.startswith(prefix):
        raise ValueError("Snapshot directory is outside the managed cache")
    pieces = root[len(prefix) :].split("/")
    if len(pieces) != 2 or str(UUID(pieces[0])) != pieces[0]:
        raise ValueError("Invalid snapshot installation directory")
    if len(pieces[1]) != 64 or any(char not in "0123456789abcdef" for char in pieces[1]):
        raise ValueError("Invalid snapshot content digest")
    return root


def snapshot_removal_script(root: str) -> str:
    """Remote Linux guard also protects calls surviving loss of the API database lease."""
    validate_runtime_root(root)
    return "\n".join(
        [
            "import os, pathlib, shutil, stat",
            f"p = pathlib.Path({root!r})",
            "for q in [*p.parents, p]:",
            "    if q.exists() or q.is_symlink():",
            '        if stat.S_ISLNK(q.lstat().st_mode): raise RuntimeError("symlink cache boundary")',
            'proc = pathlib.Path("/proc")',
            'if not proc.is_dir(): raise RuntimeError("process ownership cannot be verified")',
            'def owned(value): return value == str(p) or value.startswith(str(p) + "/")',
            "for process in proc.iterdir():",
            "    if not process.name.isdecimal() or int(process.name) == os.getpid(): continue",
            "    try:",
            '        if owned(os.readlink(process / "cwd")): raise RuntimeError("snapshot process is active")',
            '        for argument in (process / "cmdline").read_bytes().split(b"\\0"):',
            '            text = argument.decode("utf-8", "surrogateescape")',
            '            value = text.partition("=")[2] if text.startswith("--") and "=" in text else text',
            '            if owned(value): raise RuntimeError("snapshot command is active")',
            '        for descriptor in (process / "fd").iterdir():',
            "            try:",
            '                if owned(os.readlink(descriptor)): raise RuntimeError("snapshot file is open")',
            "            except FileNotFoundError: pass",
            "    except (FileNotFoundError, ProcessLookupError): pass",
            "if p.exists(): shutil.rmtree(p)",
        ]
    )


class MarketplaceSnapshotCache:
    """Use the existing scoped JSON record migration; never enumerate unowned directories."""

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str,
        project_id: str | None,
        sandbox: SandboxResourcePort | None = None,
    ) -> None:
        self.db, self.tenant_id, self.project_id = db, tenant_id, project_id or ""
        self.sandbox = sandbox

    def query(self, kind: str) -> Select[tuple[MarketplaceRecordV3]]:
        return select(MarketplaceRecordV3).where(
            MarketplaceRecordV3.tenant_id == self.tenant_id,
            MarketplaceRecordV3.project_id == self.project_id,
            MarketplaceRecordV3.kind == kind,
        )

    async def register(
        self,
        package: dict[str, Any],
        runtime_root: str | None = None,
        *,
        owner_id: str | None = None,
    ) -> str:
        if runtime_root:
            validate_runtime_root(runtime_root)
        digest = str(package["digest"])
        key = hashlib.sha256(json.dumps([digest, runtime_root]).encode()).hexdigest()
        row = await self.db.scalar(
            self.query("snapshot").where(MarketplaceRecordV3.record_key == key).with_for_update()
        )
        if row is None:
            row = MarketplaceRecordV3(
                id=str(uuid4()),
                tenant_id=self.tenant_id,
                project_id=self.project_id,
                kind="snapshot",
                record_key=key,
                payload={},
            )
            self.db.add(row)
        size = sum(
            len(base64.b64decode(value, validate=True))
            for value in package.get("files", {}).values()
        )
        row.payload = {
            "digest": digest,
            "runtime_root": runtime_root,
            "installation_id": owner_id,
            "size_bytes": size,
            "state": "retained",
            "created_at": row.payload.get("created_at", time.time()),
        }
        await self.db.flush()
        return row.id

    async def protected(self) -> tuple[set[str], set[str]]:
        digests, roots = set(), set()
        # Lock references before evaluating eligibility. Mutation/preflight registration uses
        # the same transaction, so cleanup cannot race an uncommitted version switch.
        for kind in ("installation", "preflight"):
            all_ids = set(
                await self.db.scalars(self.query(kind).with_only_columns(MarketplaceRecordV3.id))
            )
            rows = list(
                await self.db.scalars(self.query(kind).with_for_update(read=True, skip_locked=True))
            )
            if all_ids - {row.id for row in rows}:
                snapshots = list(await self.db.scalars(self.query("snapshot")))
                return (
                    {row.payload["digest"] for row in snapshots},
                    {
                        row.payload["runtime_root"]
                        for row in snapshots
                        if row.payload.get("runtime_root")
                    },
                )
            for row in rows:
                data = row.payload
                if kind == "installation" and data.get("status") == "uninstalled":
                    continue
                if kind == "preflight":
                    try:
                        require_fresh_preflight(data)
                    except ValueError:
                        continue
                package = data.get("package", {})
                if package.get("digest"):
                    digests.add(package["digest"])
                if data.get("runtime_root"):
                    roots.add(data["runtime_root"])
        return digests, roots

    @staticmethod
    def eligible(payload: dict[str, Any], digests: set[str], roots: set[str]) -> bool:
        root = payload.get("runtime_root")
        return root not in roots if root else payload.get("digest") not in digests

    async def stats(self) -> dict[str, int]:
        digests, roots = await self.protected()
        rows = list(await self.db.scalars(self.query("snapshot")))
        return {
            "entries": len(rows),
            "total_bytes": sum(row.payload["size_bytes"] for row in rows),
            "reclaimable_bytes": sum(
                row.payload["size_bytes"]
                for row in rows
                if self.eligible(row.payload, digests, roots)
            ),
        }

    async def cleanup(self, key: str, *, remember: bool = True) -> dict[str, int]:
        previous = await self.db.scalar(
            self.query("cache_cleanup").where(MarketplaceRecordV3.record_key == key)
        )
        if previous:
            return previous.payload
        digests, roots = await self.protected()
        rows = list(await self.db.scalars(self.query("snapshot").with_for_update(skip_locked=True)))
        removed_bytes = removed_entries = 0
        for row in rows:
            if not self.eligible(row.payload, digests, roots):
                continue
            row.payload = {**row.payload, "state": "pending_reclamation"}
            await self.db.flush()
            root = row.payload.get("runtime_root")
            if root:
                if self.sandbox is None:
                    continue
                await self.remove_registered_directory(row, root)
                for installation in await self.db.scalars(
                    self.query("installation").with_for_update(skip_locked=True)
                ):
                    if installation.payload.get("runtime_root") == root:
                        installation.payload = {
                            **installation.payload,
                            "runtime_snapshot_removed": True,
                        }
            else:
                # Expired previews and uninstalled records retain metadata, never cached bytes.
                for kind in ("preflight", "installation"):
                    for reference in await self.db.scalars(self.query(kind).with_for_update()):
                        package = reference.payload.get("package", {})
                        if package.get("digest") == row.payload["digest"]:
                            reference.payload = {
                                **reference.payload,
                                "package": {**package, "files": {}},
                            }
            removed_bytes += row.payload["size_bytes"]
            removed_entries += 1
            await self.db.delete(row)
        await self.db.flush()
        await self.cleanup_credentials()
        result = {
            **await self.stats(),
            "removed_bytes": removed_bytes,
            "removed_entries": removed_entries,
        }
        if not remember:
            return result
        self.db.add(
            MarketplaceRecordV3(
                id=str(uuid4()),
                tenant_id=self.tenant_id,
                project_id=self.project_id,
                kind="cache_cleanup",
                record_key=key,
                payload=result,
            )
        )
        await self.db.flush()
        return result

    async def remove_registered_directory(self, row: MarketplaceRecordV3, root: str) -> None:
        row.payload = {
            **row.payload,
            "cleanup_attempts": row.payload.get("cleanup_attempts", 0) + 1,
            "last_cleanup_attempt_at": time.time(),
        }
        try:
            await self.remove_directory(root)
        except Exception:
            row.payload = {**row.payload, "cleanup_error": "snapshot_cleanup_deferred"}
            await self.db.flush()
            raise

    async def cleanup_credentials(self) -> None:
        """Purge only dedicated OAuth state after owned runtime snapshots are gone.

        Legacy unregistered runtime directories cannot prove reclamation and retain grants.
        An installation locked by a running operation is skipped for the next cleanup retry.
        """
        snapshots = list(await self.db.scalars(self.query("snapshot")))
        installations = await self.db.scalars(
            self.query("installation").with_for_update(skip_locked=True)
        )
        owners = set()
        for row in installations:
            if row.payload.get("status") != "uninstalled":
                continue
            if any(
                snapshot.payload.get("installation_id") == row.id
                and snapshot.payload.get("runtime_root")
                for snapshot in snapshots
            ):
                continue
            if row.payload.get("runtime_root") and not row.payload.get("runtime_snapshot_removed"):
                continue
            owners.add(row.id)
        for kind in ("oauth_grant", "oauth_challenge", "oauth_request"):
            for row in await self.db.scalars(self.query(kind).with_for_update(skip_locked=True)):
                if row.payload.get("installation_id") in owners:
                    await self.db.delete(row)
        await self.db.flush()

    async def remove_directory(self, root: str) -> None:
        validate_runtime_root(root)
        # Validate every ancestor without resolving symlinks; rmtree does not follow nested
        # symlinks. Only this installation/digest root can be removed, never its parent.
        script = snapshot_removal_script(root)
        result = await self.sandbox.execute_tool(
            project_id=self.project_id,
            tool_name="bash",
            arguments={"command": "python3 -c " + shlex.quote(script), "timeout": 30},
            timeout=30.0,
        )
        if (
            result.get("isError")
            or result.get("is_error")
            or result.get("metadata", {}).get("exit_code", 0) != 0
        ):
            raise ValueError("Snapshot cleanup failed; cache registration was retained")


async def _lock_snapshot_rows(
    db: AsyncSession,
    tenant_id: str,
    project_id: str,
    server_name: str | None,
    runtime_root: str | None,
) -> None:
    cache = MarketplaceSnapshotCache(db, tenant_id, project_id)
    roots = {runtime_root} if runtime_root else set()
    if server_name is not None:
        server = await db.scalar(
            select(MCPServer).where(
                MCPServer.tenant_id == tenant_id,
                MCPServer.project_id == project_id,
                MCPServer.name == server_name,
            )
        )
        if server is not None:
            rows = await db.scalars(cache.query("installation"))
            roots.update(
                row.payload["runtime_root"]
                for row in rows
                if server.id in row.payload.get("owned_servers", [])
                and row.payload.get("runtime_root")
            )
    if roots:
        rows = await db.scalars(cache.query("snapshot").with_for_update(read=True))
        # Consuming scalars materializes the shared locks; legacy unregistered directories
        # are intentionally not eligible for cleanup and need no inferred filesystem ownership.
        for row in rows:
            if (
                row.payload.get("runtime_root") in roots
                and row.payload.get("state") == "pending_reclamation"
            ):
                raise ValueError("Snapshot is being reclaimed; retry the current plugin version")


async def reclaim_marketplace_cache(
    db: AsyncSession, tenant_id: str, project_id: str, sandbox: SandboxResourcePort | None = None
) -> None:
    """Best-effort independent retry after a commit or final running-call lease release."""
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    async with factory() as cleanup_db:
        try:
            await MarketplaceSnapshotCache(cleanup_db, tenant_id, project_id, sandbox).cleanup(
                f"automatic:{uuid4()}", remember=False
            )
            await cleanup_db.commit()
        except ValueError as exc:
            await cleanup_db.commit()
            logger.warning("Marketplace cache cleanup retained for retry: %s", type(exc).__name__)
        except Exception as exc:
            await cleanup_db.rollback()
            logger.warning("Marketplace cache cleanup deferred: %s", type(exc).__name__)


_credential_cleanup_tasks: set[asyncio.Task[None]] = set()


def _retry_credentials_after_transaction(db: AsyncSession, tenant_id: str, project_id: str) -> None:
    """Retry dedicated secret deletion only after the caller releases any grant row lock."""
    marker = (tenant_id, project_id)
    registered = db.info.setdefault("marketplace_credential_cleanup", set())
    if marker in registered:
        return
    registered.add(marker)
    loop = asyncio.get_running_loop()
    factory = async_sessionmaker(db.bind, expire_on_commit=False)

    async def cleanup() -> None:
        async with factory() as session:
            try:
                await MarketplaceSnapshotCache(session, tenant_id, project_id).cleanup_credentials()
                await session.commit()
            except Exception as exc:
                logger.warning("Marketplace credential cleanup deferred: %s", type(exc).__name__)

    def schedule() -> None:
        event.remove(db.sync_session, "after_transaction_end", finished)
        registered.discard(marker)
        task = loop.create_task(cleanup())
        _credential_cleanup_tasks.add(task)
        task.add_done_callback(_credential_cleanup_tasks.discard)

    def finished(session: object, transaction: Any) -> None:  # noqa: ANN401
        if transaction.parent is None:
            loop.call_soon(schedule)

    event.listen(db.sync_session, "after_transaction_end", finished)
    if not db.in_transaction():
        loop.call_soon(schedule)


@asynccontextmanager
async def lease_marketplace_snapshots(
    db: AsyncSession,
    tenant_id: str,
    project_id: str,
    server_name: str | None = None,
    runtime_root: str | None = None,
    *,
    sandbox: SandboxResourcePort | None = None,
) -> AsyncIterator[None]:
    """Independent transaction pins immutable roots and releases before automatic cleanup.

    PostgreSQL connection/transaction termination releases the shared locks after a crash.
    Cleanup skips busy rows, so it never waits on the caller's mutation transaction.
    """
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    try:
        if db.info.get("marketplace_transaction_owned"):
            # Installation verification may already own exclusive locks on its staged
            # snapshot. Reacquiring them on another connection would deadlock the caller.
            # Keep these locks in the mutation transaction; the route reclaims after commit.
            await _lock_snapshot_rows(db, tenant_id, project_id, server_name, runtime_root)
            yield
            return
        async with factory() as lease_db:
            await _lock_snapshot_rows(lease_db, tenant_id, project_id, server_name, runtime_root)
            try:
                yield
            finally:
                await lease_db.commit()
    finally:
        if sandbox is not None:
            _retry_credentials_after_transaction(db, tenant_id, project_id)
            await reclaim_marketplace_cache(db, tenant_id, project_id, sandbox)
