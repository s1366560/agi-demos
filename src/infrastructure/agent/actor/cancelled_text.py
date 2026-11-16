"""Close unfinished protocol text blocks when an actor stream is cancelled."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, cast

from src.infrastructure.agent.events.converter import normalize_event_dict

_TEXT_SCOPE_FIELDS = (
    "conversation_id",
    "run_id",
    "message_id",
    "stream_id",
    "subagent_id",
    "agent_id",
)


@dataclass
class _OpenTextBlock:
    """One text_start boundary and the deltas actually emitted after it."""

    metadata: dict[str, Any]
    parts: list[str] = field(default_factory=list[str])
    closed: bool = False

    def append_delta(self, payload: Mapping[str, Any]) -> None:
        if "plugin_generation" in payload and "plugin_generation" not in self.metadata:
            self.metadata["plugin_generation"] = deepcopy(payload["plugin_generation"])
        delta = payload.get("delta")
        if isinstance(delta, str):
            self.parts.append(delta)


def cancelled_text_end_events(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return text_end snapshots for only the unfinished text blocks in this run.

    This consumes the actor's current-run event collection, not conversation
    history. Missing text_start is tolerated for delta-only transports. Starts
    form explicit block boundaries; no content, tool names or prose is used to
    infer which text belongs together. The actor assigns fresh event cursors to
    the returned events before persisting and publishing them.
    """
    blocks: list[_OpenTextBlock] = []
    by_scope: dict[tuple[str | None, ...], list[_OpenTextBlock]] = {}
    seen_cursors: set[tuple[int, int]] = set()
    for event in events:
        if event.get("type") not in {"text_start", "text_delta", "text_end"}:
            continue
        cursor = (event.get("event_time_us"), event.get("event_counter"))
        if all(type(value) is int for value in cursor):
            typed_cursor = cast(tuple[int, int], cursor)
            if typed_cursor in seen_cursors:
                continue
            seen_cursors.add(typed_cursor)
        normalized = normalize_event_dict(event)
        if normalized is None:
            continue
        payload = normalized["data"]
        scope = tuple(
            value if isinstance(value := payload.get(key), str) else None
            for key in _TEXT_SCOPE_FIELDS
        )
        scoped_blocks = by_scope.setdefault(scope, [])
        event_type = normalized["type"]
        if event_type == "text_end":
            # Processor defers accepted text_end events until model completion,
            # so multiple starts can precede their corresponding ends.
            for block in scoped_blocks:
                if not block.closed:
                    block.closed = True
                    break
            continue
        open_block = next((block for block in reversed(scoped_blocks) if not block.closed), None)
        if event_type == "text_start" or open_block is None:
            metadata = {
                key: deepcopy(payload[key])
                for key in (*_TEXT_SCOPE_FIELDS, "plugin_generation")
                if key in payload
            }
            open_block = _OpenTextBlock(metadata=metadata)
            blocks.append(open_block)
            scoped_blocks.append(open_block)
        if event_type == "text_delta":
            open_block.append_delta(payload)

    return _unfinished_snapshots(blocks)


def _unfinished_snapshots(blocks: Sequence[_OpenTextBlock]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for block in blocks:
        full_text = "".join(block.parts)
        if block.closed or not full_text.strip():
            continue
        snapshots.append(
            {
                "type": "text_end",
                "data": {
                    **block.metadata,
                    "full_text": full_text,
                    "partial": True,
                    "status": "cancelled",
                },
            }
        )
    return snapshots
