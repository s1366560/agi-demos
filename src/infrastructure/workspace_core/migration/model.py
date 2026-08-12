"""Value objects and canonical hashing for Workspace data migration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import cast
from uuid import UUID

MIGRATION_VERSION = "avernet-workspace-v1"


class MigrationCommand(StrEnum):
    """Supported offline migration operations."""

    DRY_RUN = "dry-run"
    EXECUTE = "execute"
    VALIDATE = "validate"
    REVERSE_EXPORT = "reverse-export"


class MigrationError(RuntimeError):
    """Raised when migration safety or parity checks fail."""


DatabaseRow = Mapping[str, object]
RowMapper = Callable[[DatabaseRow], dict[str, object]]


@dataclass(frozen=True, slots=True)
class MigrationScope:
    """Optional deterministic source scope applied to every mapping."""

    tenant_id: str | None = None
    project_id: str | None = None
    workspace_id: str | None = None


@dataclass(frozen=True, slots=True)
class MigrationSpec:
    """One source projection and its normalized Avernet target."""

    entity_type: str
    source_table: str
    target_table: str
    source_sql: str
    source_id_column: str
    target_columns: tuple[str, ...]
    key_columns: tuple[str, ...]
    json_columns: frozenset[str] = frozenset()
    mapper: RowMapper = dict
    reverse_mapper: RowMapper | None = None
    project_scoped: bool = False

    def target_id(self, values: Mapping[str, object]) -> str:
        """Return a stable ledger identifier for a possibly composite target key."""

        return "|".join(str(values[column]) for column in self.key_columns)


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    """One deterministic invalid-data query that must return zero rows."""

    code: str
    description: str
    sql: str


@dataclass(frozen=True, slots=True)
class PreflightIssue:
    code: str
    description: str
    count: int
    samples: tuple[str, ...] = ()


@dataclass(slots=True)
class EntityMigrationReport:
    entity_type: str
    source_table: str
    target_table: str
    source_count: int = 0
    verified_count: int = 0
    failed_count: int = 0
    primary_key_hash: str = field(default_factory=lambda: canonical_hash([]))
    content_hash: str = field(default_factory=lambda: canonical_hash([]))
    target_primary_key_hash: str | None = None
    target_content_hash: str | None = None


def _empty_entity_reports() -> list[EntityMigrationReport]:
    return []


def _empty_preflight_issues() -> list[PreflightIssue]:
    return []


@dataclass(slots=True)
class MigrationReport:
    command: MigrationCommand
    migration_run_id: str
    migration_version: str
    scope: MigrationScope
    entities: list[EntityMigrationReport] = field(default_factory=_empty_entity_reports)
    preflight_issues: list[PreflightIssue] = field(default_factory=_empty_preflight_issues)
    exported_records: int = 0

    @property
    def ok(self) -> bool:
        return not self.preflight_issues and all(
            entity.failed_count == 0 for entity in self.entities
        )

    def to_json(self) -> str:
        """Serialize without leaking connection configuration or credentials."""

        payload = asdict(self)
        payload["command"] = self.command.value
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def canonical_value(value: object) -> object:  # noqa: PLR0911
    """Normalize database and JSON values before hashing."""

    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            str(key): canonical_value(item)
            for key, item in sorted(mapping.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        sequence = cast(Sequence[object], value)
        return [canonical_value(item) for item in sequence]
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def canonical_json(value: object) -> str:
    """Return canonical UTF-8 JSON with stable keys and separators."""

    return json.dumps(
        canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(value: object) -> str:
    """Return a lowercase SHA-256 hash of canonical JSON."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def decode_json(value: object, *, default: object) -> object:
    """Decode a JSON database value while preserving valid scalar JSON."""

    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value
