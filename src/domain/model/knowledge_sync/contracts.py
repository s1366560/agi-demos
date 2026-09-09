"""Deterministic revision and receipt contracts shared by cloud sync adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

# Existing memories.version is a PostgreSQL signed INTEGER.
MAX_REVISION = 2**31 - 1


class KnowledgeSyncError(Exception):
    """A stable structural or authorization failure; never a merge verdict."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def require_identifier(value: object) -> None:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 512:
        raise KnowledgeSyncError("knowledge_sync_input_invalid")


def require_change_id(value: str) -> None:
    try:
        if str(UUID(value)) != value:
            raise ValueError("noncanonical UUID")
    except (ValueError, TypeError, AttributeError) as error:
        raise KnowledgeSyncError("knowledge_sync_change_id_invalid") from error


@dataclass(frozen=True, kw_only=True)
class KnowledgeSyncScope:
    tenant_id: str
    project_id: str
    actor_id: str

    def __post_init__(self) -> None:
        for value in (self.tenant_id, self.project_id, self.actor_id):
            require_identifier(value)


@dataclass(frozen=True, kw_only=True)
class MemorySyncContent:
    title: str
    content: str
    content_type: str = "text"
    tags: tuple[str, ...] = ()
    metadata_json: str = "{}"
    status: str = "ENABLED"

    def __post_init__(self) -> None:
        require_identifier(self.title)
        if (
            len(self.title) > 500
            or type(self.content) is not str
            or len(self.content.encode("utf-8")) > 1_048_576
            or self.content_type not in {"text", "document", "image", "video"}
            or self.status not in {"ENABLED", "DISABLED"}
            or len(self.tags) > 100
        ):
            raise KnowledgeSyncError("knowledge_sync_input_invalid")
        for tag in self.tags:
            require_identifier(tag)
        object.__setattr__(self, "tags", tuple(self.tags))
        try:
            metadata = json.loads(self.metadata_json)
            if not isinstance(metadata, dict):
                raise ValueError("metadata must be an object")
            canonical = json.dumps(metadata, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if len(canonical.encode("utf-8")) > 65_536:
                raise ValueError("metadata exceeds limit")
        except (ValueError, TypeError) as error:
            raise KnowledgeSyncError("knowledge_sync_input_invalid") from error
        object.__setattr__(self, "metadata_json", canonical)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "content_type": self.content_type,
            "tags": list(self.tags),
            "metadata": json.loads(self.metadata_json),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MemorySyncContent:
        return cls(
            title=value["title"],
            content=value["content"],
            content_type=value["content_type"],
            tags=tuple(value["tags"]),
            metadata_json=json.dumps(value["metadata"]),
            status=value["status"],
        )


@dataclass(frozen=True, kw_only=True)
class MemorySyncMutation:
    operation: Literal["create", "update", "delete"]
    memory_id: str
    expected_revision: int
    content: MemorySyncContent | None = None

    def __post_init__(self) -> None:
        require_identifier(self.memory_id)
        if (
            self.operation not in {"create", "update", "delete"}
            or type(self.expected_revision) is not int
            or not 0 <= self.expected_revision < MAX_REVISION
            or (self.operation == "create") != (self.expected_revision == 0)
            or (self.operation == "delete") != (self.content is None)
        ):
            raise KnowledgeSyncError("knowledge_sync_input_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "memory_id": self.memory_id,
            "expected_revision": self.expected_revision,
            "content": self.content.to_dict() if self.content is not None else None,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MemorySyncMutation:
        return cls(
            operation=value["operation"],
            memory_id=value["memory_id"],
            expected_revision=value["expected_revision"],
            content=MemorySyncContent.from_dict(value["content"])
            if value["content"] is not None
            else None,
        )


@dataclass(frozen=True, kw_only=True)
class MemorySyncVersion:
    memory_id: str
    revision: int
    deleted: bool
    author_id: str
    created_at_ms: int
    content: MemorySyncContent

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "revision": self.revision,
            "deleted": self.deleted,
            "author_id": self.author_id,
            "created_at_ms": self.created_at_ms,
            "content": self.content.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MemorySyncVersion:
        return cls(
            memory_id=value["memory_id"],
            revision=value["revision"],
            deleted=value["deleted"],
            author_id=value["author_id"],
            created_at_ms=value["created_at_ms"],
            content=MemorySyncContent.from_dict(value["content"]),
        )


@dataclass(frozen=True, kw_only=True)
class KnowledgeSyncResolution:
    conflict_id: str
    expected_current_revision: int
    decision: Literal["keep_current", "use_proposed", "merged", "keep_both"]
    content: MemorySyncContent | None = None

    def __post_init__(self) -> None:
        require_change_id(self.conflict_id)
        if (
            type(self.expected_current_revision) is not int
            or not 0 <= self.expected_current_revision <= MAX_REVISION
            or self.decision not in {"keep_current", "use_proposed", "merged", "keep_both"}
            or (self.decision == "merged") != (self.content is not None)
        ):
            raise KnowledgeSyncError("knowledge_sync_input_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "expected_current_revision": self.expected_current_revision,
            "decision": self.decision,
            "content": self.content.to_dict() if self.content is not None else None,
        }


@dataclass(frozen=True, kw_only=True)
class KnowledgeSyncOutcome:
    """Receipt JSON is immutable and replays exactly after later object changes."""

    receipt_json: str
    replayed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"receipt": json.loads(self.receipt_json), "replayed": self.replayed}


@dataclass(frozen=True, kw_only=True)
class KnowledgeSyncPage:
    changes_json: str
    next_cursor: int
    has_more: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "changes": json.loads(self.changes_json),
            "next_cursor": self.next_cursor,
            "has_more": self.has_more,
        }
