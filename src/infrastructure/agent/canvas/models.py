"""Canvas data models for A2UI dynamic UI blocks.

Defines the core value objects for canvas blocks that agents can create,
update, and delete during conversation to provide rich interactive displays.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CanvasBlockType(str, Enum):
    """Supported canvas block types for A2UI rendering."""

    CODE = "code"
    TABLE = "table"
    CHART = "chart"
    FORM = "form"
    IMAGE = "image"
    MARKDOWN = "markdown"
    WIDGET = "widget"
    A2UI_SURFACE = "a2ui_surface"


@dataclass(frozen=True)
class CanvasBlock:
    """Immutable value object representing a single canvas block.

    Attributes:
        id: Unique block identifier (auto-generated UUID).
        block_type: The type of UI block to render.
        title: Human-readable title for the block.
        content: JSON-serialised content specific to block type.
        metadata: Arbitrary key-value metadata.
        version: Monotonically increasing version for optimistic updates.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    block_type: CanvasBlockType = CanvasBlockType.MARKDOWN
    title: str = ""
    content: str = ""
    metadata: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for SSE event payloads."""
        return {
            "id": self.id,
            "block_type": self.block_type.value,
            "title": self.title,
            "content": self.content,
            "metadata": dict(self.metadata),
            "version": self.version,
        }

    def with_content(self, content: str) -> CanvasBlock:
        """Return a new block with updated content and incremented version."""
        return CanvasBlock(
            id=self.id,
            block_type=self.block_type,
            title=self.title,
            content=content,
            metadata=self.metadata,
            version=self.version + 1,
        )

    def with_title(self, title: str) -> CanvasBlock:
        """Return a new block with updated title and incremented version."""
        return CanvasBlock(
            id=self.id,
            block_type=self.block_type,
            title=title,
            content=self.content,
            metadata=self.metadata,
            version=self.version + 1,
        )


class CanvasState:
    """Mutable container tracking all canvas blocks for a single conversation.

    Thread-safe via copy-on-read semantics.
    """

    def __init__(self) -> None:
        super().__init__()
        self._blocks: dict[str, CanvasBlock] = {}

    @property
    def block_count(self) -> int:
        """Return the number of active blocks."""
        return len(self._blocks)

    def get(self, block_id: str) -> CanvasBlock | None:
        """Return a block by ID, or None if not found."""
        return self._blocks.get(block_id)

    def add(self, block: CanvasBlock) -> None:
        """Add or replace a block."""
        self._blocks[block.id] = block

    def remove(self, block_id: str) -> CanvasBlock | None:
        """Remove and return a block, or None if not found."""
        return self._blocks.pop(block_id, None)

    def all_blocks(self) -> list[CanvasBlock]:
        """Return a snapshot list of all blocks (ordered by insertion)."""
        return list(self._blocks.values())

    def clear(self) -> None:
        """Remove all blocks."""
        self._blocks.clear()
