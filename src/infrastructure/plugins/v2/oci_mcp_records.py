"""Bound an OCI worker's immutable records to its approved tool, release and project."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.platform_plugin_namespace_model_v2 import (
    PlatformPluginNamespaceRecordModelV2 as Namespace,
)
from src.infrastructure.plugins.v2.plugin_namespace_store_v2 import (
    NamespaceKeyV2,
    NamespaceRecordV2,
    SqlPluginNamespaceStoreV2,
    assert_supported_schema_v2,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
        ScopeBindingV2,
        SignedPackageBytesV2,
    )


type RecordCall = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
# Raw namespace REST keys already exclude slashes.
_PREFIX = "records/"
_KEY = re.compile(r"[A-Za-z0-9_-]{1,96}\Z")
_current: ContextVar[WorkerRecords | None] = ContextVar("worker_records", default=None)


def _size(name: str, document: dict[str, Any]) -> int:
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return len(name.encode()) + len(raw.encode())


async def check_storage_quota(
    db: AsyncSession, key: NamespaceKeyV2, document: dict[str, Any], limit: int
) -> None:
    """Count ordinary data and immutable worker records under the same project write lock."""
    used = _size(key.item_key, document)
    others = await db.stream(
        select(Namespace.item_key, Namespace.document).where(
            Namespace.tenant_id == key.tenant_id,
            Namespace.project_id == key.project_id,
            Namespace.plugin_id == key.plugin_id,
            Namespace.item_key != key.item_key,
        )
    )
    try:
        async for name, value in others:
            used += _size(name, value)
            if used > limit:
                break
    finally:
        await others.close()
    if used > limit:
        raise OptionalBusinessError("quota_exceeded", "package storage quota exceeded")


@dataclass(kw_only=True)
class WorkerRecords:
    db: AsyncSession
    scope: ScopeBindingV2
    package: SignedPackageBytesV2
    authorize_write: Callable[[], Awaitable[None]]
    write_attempted: bool = False

    def _key(self, name: object) -> NamespaceKeyV2:
        if not isinstance(name, str) or not _KEY.fullmatch(name):
            raise OptionalBusinessError("storage_key", "invalid worker record key")
        return NamespaceKeyV2(
            plugin_id=self.package.plugin_id,
            tenant_id=self.scope.tenant_id,
            project_id=self.scope.project_id,
            item_key=_PREFIX + name,
        )

    async def _get(self, key: NamespaceKeyV2) -> NamespaceRecordV2 | None:
        row = await self.db.run_sync(lambda session: SqlPluginNamespaceStoreV2(session).get(key))
        if row:
            assert_supported_schema_v2(row)
        return row

    async def _list(self, after: object, limit: object) -> dict[str, Any]:
        start = self._key(after).item_key if after is not None else _PREFIX
        if type(limit) is not int or not 1 <= limit <= 16:
            raise OptionalBusinessError("storage_key", "invalid worker record page size")
        found = (
            await self.db.scalars(
                select(Namespace.item_key)
                .where(
                    Namespace.tenant_id == self.scope.tenant_id,
                    Namespace.project_id == self.scope.project_id,
                    Namespace.plugin_id == self.package.plugin_id,
                    Namespace.item_key.startswith(_PREFIX),
                    Namespace.item_key > start,
                )
                .order_by(Namespace.item_key)
                .limit(limit + 1)
            )
        ).all()
        keys = [name[len(_PREFIX) :] for name in found[:limit]]
        return {"keys": keys, "next_cursor": keys[-1] if len(found) > limit else None}

    async def call(
        self, permissions: frozenset[str], method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        storage = self.package.contribution.storage
        required = "storage.write" if method == "memstack/records/create" else "storage.read"
        if not storage or required not in (
            permissions & storage.permissions & self.package.approved_permissions
        ):
            raise OptionalBusinessError("forbidden", "worker record operation was not approved")
        if method == "memstack/records/list" and params.keys() <= {"after", "limit"}:
            return await self._list(params.get("after"), params.get("limit", 16))
        if method == "memstack/records/get" and params.keys() == {"key"}:
            row = await self._get(self._key(params["key"]))
            return {"document": row.document if row else None}
        if method != "memstack/records/create" or params.keys() != {"key", "document"}:
            raise OptionalBusinessError("forbidden", "unknown worker record operation")
        key = self._key(params["key"])
        document = params["document"]
        if self.write_attempted or not isinstance(document, dict):
            raise OptionalBusinessError("forbidden", "expected one immutable record per invocation")
        self.write_attempted = True
        row = NamespaceRecordV2(schema_version=storage.schema_version, document=document)
        assert_supported_schema_v2(row)
        await self.authorize_write()
        if await self._get(key) is not None:
            return {"created": False}
        await check_storage_quota(self.db, key, document, self.package.storage_limit)
        await self.db.run_sync(lambda session: SqlPluginNamespaceStoreV2(session).put(key, row))
        return {"created": True}


@contextmanager
def bind_worker_records(records: WorkerRecords) -> Iterator[None]:
    token = _current.set(records)
    try:
        yield
    finally:
        _current.reset(token)


def worker_record_call(
    package: SignedPackageBytesV2, scope: ScopeBindingV2, permissions: frozenset[str]
) -> RecordCall | None:
    records = _current.get()
    if not records or records.package is not package or records.scope != scope:
        return None
    return lambda method, params: records.call(permissions, method, params)
