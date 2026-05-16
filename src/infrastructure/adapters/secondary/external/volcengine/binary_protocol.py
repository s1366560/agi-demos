"""Binary framing utilities for Volcengine ASR V3 WebSocket protocol.

Implements the binary header, sequence, and response parsing for the ASR
streaming protocol described at:
  https://www.volcengine.com/docs/6561/1354870

The 4-byte header layout is:
  byte 0: (protocol_version << 4) | header_size
  byte 1: (message_type     << 4) | message_type_specific_flags
  byte 2: (serialization    << 4) | compression
  byte 3: reserved (0x00)
"""

from __future__ import annotations

import gzip
import json
import logging
import struct
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

PROTOCOL_VERSION: int = 0b0001
HEADER_SIZE: int = 0b0001

# Message types (upper nibble of byte 1)
FULL_CLIENT_REQUEST: int = 0b0001
AUDIO_ONLY_REQUEST: int = 0b0010
FULL_SERVER_RESPONSE: int = 0b1001
SERVER_ACK: int = 0b1011
SERVER_ERROR_RESPONSE: int = 0b1111

# Message-type-specific flags (lower nibble of byte 1)
NO_SEQUENCE: int = 0b0000
POS_SEQUENCE: int = 0b0001
NEG_SEQUENCE: int = 0b0010
NEG_WITH_SEQUENCE: int = 0b0011
LAST_PACKAGE: int = 0b0010  # Alias used for audio-only last packet

# Serialization (upper nibble of byte 2)
JSON_SERIALIZATION: int = 0b0001
NO_SERIALIZATION: int = 0b0000

# Compression (lower nibble of byte 2)
GZIP_COMPRESSION: int = 0b0001
NO_COMPRESSION: int = 0b0000

# ---------------------------------------------------------------------------
# Header construction
# ---------------------------------------------------------------------------


def generate_header(
    message_type: int = FULL_CLIENT_REQUEST,
    message_type_specific_flags: int = NO_SEQUENCE,
    serialization: int = JSON_SERIALIZATION,
    compression: int = GZIP_COMPRESSION,
) -> bytes:
    """Build a 4-byte protocol header.

    Returns:
        4 bytes packed as ``[version<<4|header_size, msg_type<<4|flags,
        serialization<<4|compression, 0x00]``.
    """
    byte0 = (PROTOCOL_VERSION << 4) | HEADER_SIZE
    byte1 = (message_type << 4) | message_type_specific_flags
    byte2 = (serialization << 4) | compression
    byte3 = 0x00
    return bytes([byte0, byte1, byte2, byte3])


def generate_before_payload(sequence: int = 1) -> bytes:
    """Encode a 4-byte big-endian sequence number.

    Args:
        sequence: Sequence counter (typically starts at 1).

    Returns:
        4 bytes representing *sequence* in big-endian order.
    """
    return struct.pack(">I", sequence)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


class ProtocolError(Exception):
    """Raised when the server response cannot be decoded."""


def parse_response(data: bytes) -> dict[str, Any]:
    """Parse a binary server response into a structured dict.

    Follows the reference implementation from ai-app-lab:
    - Uses bitwise flag checks (``& 0x01``, ``& 0x02``) instead of equality
    - Handles ``FULL_SERVER_RESPONSE``, ``SERVER_ACK``, and ``SERVER_ERROR_RESPONSE``
      each with their own payload layout
    - Explicit UTF-8 decoding before ``json.loads``

    The returned dict always contains:
      * ``is_last_package``  -- ``True`` when the server signals end-of-stream.

    Conditionally contains:
      * ``payload_msg``      -- parsed JSON body.
      * ``payload_sequence`` -- the sequence number embedded in the frame.
      * ``payload_size``     -- declared payload size.
      * ``seq``             -- ack sequence (for ``SERVER_ACK``).
      * ``code``            -- error code (for ``SERVER_ERROR_RESPONSE``).

    Raises:
        ProtocolError: If the frame is too short or the message type is
            ``SERVER_ERROR_RESPONSE``.
    """
    if len(data) < 4:
        raise ProtocolError(f"Response too short ({len(data)} bytes)")

    msg_type, msg_flags, serialization, compression, payload = _split_response_frame(data)
    result: dict[str, Any] = {
        "is_last_package": False,
    }

    payload = _consume_optional_sequence(payload, msg_flags, result)
    if msg_flags & 0x02:
        result["is_last_package"] = True

    payload_msg, payload_size = _extract_response_payload(msg_type, payload, result)
    if payload_msg is not None:
        result["payload_msg"] = _decode_payload_message(
            payload_msg,
            serialization,
            compression,
        )
        result["payload_size"] = payload_size

    if msg_type == SERVER_ERROR_RESPONSE:
        _raise_server_error(result)

    return result


def _split_response_frame(data: bytes) -> tuple[int, int, int, int, bytes]:
    """Return decoded header fields and payload bytes."""
    header_size = data[0] & 0x0F
    msg_type = (data[1] >> 4) & 0x0F
    msg_flags = data[1] & 0x0F
    serialization = (data[2] >> 4) & 0x0F
    compression = data[2] & 0x0F
    payload = data[header_size * 4 :]
    return msg_type, msg_flags, serialization, compression, payload


def _consume_optional_sequence(
    payload: bytes,
    msg_flags: int,
    result: dict[str, Any],
) -> bytes:
    """Extract optional sequence number from the payload area."""
    if msg_flags & 0x01 and len(payload) >= 4:
        result["payload_sequence"] = int.from_bytes(payload[:4], "big", signed=True)
        return payload[4:]
    return payload


def _extract_response_payload(
    msg_type: int,
    payload: bytes,
    result: dict[str, Any],
) -> tuple[bytes | None, int]:
    """Extract message-type-specific payload fields."""
    if msg_type == FULL_SERVER_RESPONSE:
        return _read_declared_payload(payload, signed=True)

    if msg_type == SERVER_ACK:
        if len(payload) < 4:
            return None, 0
        result["seq"] = int.from_bytes(payload[:4], "big", signed=True)
        return _read_declared_payload(payload[4:], signed=False)

    if msg_type == SERVER_ERROR_RESPONSE:
        if len(payload) < 4:
            return None, 0
        result["code"] = int.from_bytes(payload[:4], "big", signed=False)
        return _read_declared_payload(payload[4:], signed=False)

    return None, 0


def _read_declared_payload(payload: bytes, *, signed: bool) -> tuple[bytes | None, int]:
    """Read a 4-byte payload size followed by the payload body."""
    if len(payload) < 4:
        return None, 0
    payload_size = int.from_bytes(payload[:4], "big", signed=signed)
    return payload[4:], payload_size


def _decode_payload_message(
    payload_msg: bytes,
    serialization: int,
    compression: int,
) -> object:
    """Decompress and deserialize a server payload."""
    if compression == GZIP_COMPRESSION:
        try:
            payload_msg = gzip.decompress(payload_msg)
        except Exception:
            logger.warning("GZIP decompression failed, using raw bytes")

    if serialization == JSON_SERIALIZATION:
        try:
            return json.loads(str(payload_msg, "utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.error(
                "JSON parse failed (first 40 bytes hex): %s  error: %s",
                payload_msg[:40].hex() if payload_msg else "<empty>",
                exc,
            )
            return {}
    if serialization != NO_SERIALIZATION:
        return str(payload_msg, "utf-8")
    return payload_msg


def _raise_server_error(result: dict[str, Any]) -> None:
    """Raise a ProtocolError from a parsed server error frame."""
    error_code = result.get("code", -1)
    payload_msg = result.get("payload_msg", {})
    error_message = (payload_msg if isinstance(payload_msg, dict) else {}).get(
        "message", "unknown error"
    )
    logger.error("ASR server error %s: %s", error_code, error_message)
    raise ProtocolError(
        f"Server error (code={error_code}): {error_message}",
    )
