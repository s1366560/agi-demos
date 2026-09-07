"""Original partial online command identity, separate from its materialized snapshot."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.domain.model.knowledge_sync.contracts import (
    MAX_REVISION,
    KnowledgeSyncError,
    MemorySyncContent,
    require_identifier,
)


@dataclass(frozen=True, kw_only=True)
class MemoryOnlinePatch:
    memory_id: str
    expected_revision: int
    fields_json: str

    def __post_init__(self) -> None:
        require_identifier(self.memory_id)
        if (
            type(self.expected_revision) is not int
            or not 1 <= self.expected_revision < MAX_REVISION
        ):
            raise KnowledgeSyncError("knowledge_sync_input_invalid")
        try:
            fields = json.loads(self.fields_json)
            if not isinstance(fields, dict) or not fields.keys() <= {
                "title",
                "content",
                "tags",
                "metadata",
            }:
                raise ValueError("unsupported patch fields")
            if None in fields.values():
                raise ValueError("explicit null is not an omitted field")
            if "tags" in fields and not isinstance(fields["tags"], list):
                raise ValueError("tags must be an array")
            # Validate present fields without copying values from mutable state.
            _ = self.apply(MemorySyncContent(title="Patch", content=""))
            encoded = json.dumps(fields, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (ValueError, TypeError, KeyError) as error:
            raise KnowledgeSyncError("knowledge_sync_input_invalid") from error
        object.__setattr__(self, "fields_json", encoded)

    def apply(self, current: MemorySyncContent) -> MemorySyncContent:
        return MemorySyncContent.from_dict({**current.to_dict(), **json.loads(self.fields_json)})

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "expected_revision": self.expected_revision,
            "fields": json.loads(self.fields_json),
        }
