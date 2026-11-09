"""Host-mediated plugin storage. Plugins never receive a database connection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

MAX_VALUE_BYTES = 16 * 1024
SUPPORTED_SCHEMA_VERSION = 1


class PluginStorageError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, kw_only=True)
class NamespaceKeyV2:
    plugin_id: str
    tenant_id: str
    project_id: str
    item_key: str


@dataclass
class NamespaceRecordV2:
    schema_version: int
    document: dict[str, object]


class PluginNamespaceStoreV2(Protocol):
    def get(self, key: NamespaceKeyV2) -> NamespaceRecordV2 | None: ...

    def put(self, key: NamespaceKeyV2, record: NamespaceRecordV2) -> None: ...

    def delete(self, key: NamespaceKeyV2) -> None: ...

    def list_keys(self, *, plugin_id: str, tenant_id: str, project_id: str) -> tuple[str, ...]: ...

    def purge(self, *, plugin_id: str, tenant_id: str, project_id: str) -> int: ...


class MemoryPluginNamespaceStoreV2:
    """Process-local store used by tests and single-process deployments."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str, str], NamespaceRecordV2] = {}

    def get(self, key: NamespaceKeyV2) -> NamespaceRecordV2 | None:
        return self._rows.get(_identity(key))

    def put(self, key: NamespaceKeyV2, record: NamespaceRecordV2) -> None:
        self._rows[_identity(key)] = record

    def delete(self, key: NamespaceKeyV2) -> None:
        self._rows.pop(_identity(key), None)

    def list_keys(self, *, plugin_id: str, tenant_id: str, project_id: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                item_key
                for stored_plugin, stored_tenant, stored_project, item_key in self._rows
                if (stored_plugin, stored_tenant, stored_project)
                == (plugin_id, tenant_id, project_id)
            )
        )

    def purge(self, *, plugin_id: str, tenant_id: str, project_id: str) -> int:
        doomed = [
            identity
            for identity in self._rows
            if identity[0] == plugin_id and identity[1] == tenant_id and identity[2] == project_id
        ]
        for identity in doomed:
            del self._rows[identity]
        return len(doomed)


def assert_supported_schema_v2(record: NamespaceRecordV2) -> None:
    if record.schema_version > SUPPORTED_SCHEMA_VERSION:
        raise PluginStorageError(
            "storage_schema_too_new",
            "stored schema is newer than this host and was left unchanged",
        )
    if record.schema_version < 1:
        raise PluginStorageError("storage_schema_invalid", "stored schema version is invalid")
    encoded = json.dumps(record.document).encode("utf-8")
    if len(encoded) > MAX_VALUE_BYTES:
        raise PluginStorageError("storage_value_too_large", "stored document exceeds the byte cap")


def _identity(key: NamespaceKeyV2) -> tuple[str, str, str, str]:
    return (key.plugin_id, key.tenant_id, key.project_id, key.item_key)
