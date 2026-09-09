"""Deterministic revision and receipt contracts shared by cloud sync adapters."""

from __future__ import annotations

import json
import math
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


MAX_GRAPH_ENTITIES = 200
MAX_GRAPH_RELATIONSHIPS = 500
MAX_GRAPH_PAYLOAD_BYTES = 262_144


def _require_score(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KnowledgeSyncError("knowledge_sync_input_invalid")
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise KnowledgeSyncError("knowledge_sync_input_invalid")


@dataclass(frozen=True, kw_only=True)
class GraphSyncEntity:
    """One derived entity. Identity is positional inside its projection record."""

    name: str
    kind: str

    def __post_init__(self) -> None:
        require_identifier(self.name)
        require_identifier(self.kind)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GraphSyncEntity:
        return cls(name=value["name"], kind=value["kind"])


@dataclass(frozen=True, kw_only=True)
class GraphSyncRelationship:
    """Endpoints are positions inside the same projection's entity list."""

    source_index: int
    target_index: int
    relation_type: str
    fact: str
    score: float

    def __post_init__(self) -> None:
        require_identifier(self.relation_type)
        require_identifier(self.fact)
        if (
            type(self.source_index) is not int
            or type(self.target_index) is not int
            or self.source_index < 0
            or self.target_index < 0
        ):
            raise KnowledgeSyncError("knowledge_sync_input_invalid")
        _require_score(self.score)
        object.__setattr__(self, "score", float(self.score))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_index": self.source_index,
            "target_index": self.target_index,
            "relation_type": self.relation_type,
            "fact": self.fact,
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GraphSyncRelationship:
        return cls(
            source_index=value["source_index"],
            target_index=value["target_index"],
            relation_type=value["relation_type"],
            fact=value["fact"],
            score=value["score"],
        )


@dataclass(frozen=True, kw_only=True)
class GraphSyncContent:
    """Derived entity/relationship records plus their extraction provenance.

    The provenance fields name the exact source accepted on the origin end:
    the source memory revision, the origin processing change sequence and the
    origin extraction audit attempt. They are references, not local cursors.
    """

    source_revision: int
    change_sequence: int
    audit_attempt: int
    entities: tuple[GraphSyncEntity, ...] = ()
    relationships: tuple[GraphSyncRelationship, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.source_revision) is not int
            or not 1 <= self.source_revision < MAX_REVISION
            or type(self.change_sequence) is not int
            or not 1 <= self.change_sequence <= 2**63 - 1
            or type(self.audit_attempt) is not int
            or not 1 <= self.audit_attempt < MAX_REVISION
            or len(self.entities) > MAX_GRAPH_ENTITIES
            or len(self.relationships) > MAX_GRAPH_RELATIONSHIPS
        ):
            raise KnowledgeSyncError("knowledge_sync_input_invalid")
        object.__setattr__(self, "entities", tuple(self.entities))
        object.__setattr__(self, "relationships", tuple(self.relationships))
        for relationship in self.relationships:
            if relationship.source_index >= len(self.entities) or relationship.target_index >= len(
                self.entities
            ):
                raise KnowledgeSyncError("knowledge_sync_input_invalid")
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        if len(canonical.encode("utf-8")) > MAX_GRAPH_PAYLOAD_BYTES:
            raise KnowledgeSyncError("knowledge_sync_input_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_revision": self.source_revision,
            "change_sequence": self.change_sequence,
            "audit_attempt": self.audit_attempt,
            "entities": [entity.to_dict() for entity in self.entities],
            "relationships": [relation.to_dict() for relation in self.relationships],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GraphSyncContent:
        return cls(
            source_revision=value["source_revision"],
            change_sequence=value["change_sequence"],
            audit_attempt=value["audit_attempt"],
            entities=tuple(GraphSyncEntity.from_dict(item) for item in value["entities"]),
            relationships=tuple(
                GraphSyncRelationship.from_dict(item) for item in value["relationships"]
            ),
        )


@dataclass(frozen=True, kw_only=True)
class GraphSyncMutation:
    """The object id is the stable source memory id already synced by memory sync."""

    operation: Literal["create", "update", "delete"]
    object_id: str
    expected_revision: int
    content: GraphSyncContent | None = None

    def __post_init__(self) -> None:
        require_identifier(self.object_id)
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
            "object_id": self.object_id,
            "expected_revision": self.expected_revision,
            "content": self.content.to_dict() if self.content is not None else None,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GraphSyncMutation:
        return cls(
            operation=value["operation"],
            object_id=value["object_id"],
            expected_revision=value["expected_revision"],
            content=GraphSyncContent.from_dict(value["content"])
            if value["content"] is not None
            else None,
        )


@dataclass(frozen=True, kw_only=True)
class GraphSyncVersion:
    object_id: str
    revision: int
    deleted: bool
    author_id: str
    created_at_ms: int
    content: GraphSyncContent

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "revision": self.revision,
            "deleted": self.deleted,
            "author_id": self.author_id,
            "created_at_ms": self.created_at_ms,
            "content": self.content.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GraphSyncVersion:
        return cls(
            object_id=value["object_id"],
            revision=value["revision"],
            deleted=value["deleted"],
            author_id=value["author_id"],
            created_at_ms=value["created_at_ms"],
            content=GraphSyncContent.from_dict(value["content"]),
        )


@dataclass(frozen=True, kw_only=True)
class GraphSyncResolution:
    conflict_id: str
    expected_current_revision: int
    decision: Literal["keep_current", "use_proposed", "merged", "keep_both"]
    content: GraphSyncContent | None = None

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
