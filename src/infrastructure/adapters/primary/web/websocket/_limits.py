"""WebSocket inbound size limits.

Bounded ``receive_json`` helper so a single misbehaving / malicious client
cannot exhaust server memory by sending an unbounded text frame. Audit
finding P2-20 — adopt 1 MiB cap per inbound JSON message across all
operator-facing WebSocket entry points.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket

# 1 MiB. Inbound JSON frames over this size are rejected with a 1009
# (Message Too Big) close. Operator commands fit comfortably; large
# payloads (file uploads, sandbox streams, voice) are routed through
# dedicated binary channels and do NOT use this helper.
MAX_INBOUND_MESSAGE_BYTES: int = 1 << 20


class InboundMessageTooLarge(Exception):
    """Raised when an inbound text frame exceeds ``MAX_INBOUND_MESSAGE_BYTES``."""

    def __init__(self, size: int, limit: int) -> None:
        super().__init__(f"Inbound message {size} bytes exceeds limit {limit}")
        self.size = size
        self.limit = limit


async def receive_json_with_limit(
    websocket: WebSocket,
    *,
    max_bytes: int = MAX_INBOUND_MESSAGE_BYTES,
) -> dict[str, Any]:
    """Receive a single JSON frame bounded to ``max_bytes``.

    Raises:
        InboundMessageTooLarge: When the encoded UTF-8 size of the received
            text frame exceeds ``max_bytes``. Callers are responsible for
            sending an error frame + closing the socket with code 1009.
        json.JSONDecodeError: When the frame is not valid JSON. Callers
            handle this to emit a structured error.
    """
    text = await websocket.receive_text()
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        raise InboundMessageTooLarge(size=size, limit=max_bytes)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        # Match the ergonomics of starlette's receive_json: only accept
        # JSON objects at the top level. Bare arrays / scalars are not a
        # valid command shape for our routers.
        raise json.JSONDecodeError("Top-level JSON must be an object", text, 0)
    return parsed
