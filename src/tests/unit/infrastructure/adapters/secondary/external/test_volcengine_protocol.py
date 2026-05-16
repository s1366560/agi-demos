"""Unit tests for Volcengine binary protocol parsing."""

from __future__ import annotations

import gzip
import json
import struct

import pytest

from src.infrastructure.adapters.secondary.external.volcengine import binary_protocol
from src.infrastructure.adapters.secondary.external.volcengine.binary_protocol import (
    FULL_SERVER_RESPONSE,
    GZIP_COMPRESSION,
    JSON_SERIALIZATION,
    LAST_PACKAGE,
    POS_SEQUENCE,
    SERVER_ACK,
    SERVER_ERROR_RESPONSE,
    ProtocolError,
    generate_header,
    parse_response,
)
from src.infrastructure.adapters.secondary.external.volcengine.tts_streaming_client import (
    HEADER_SIZE,
    JSON_SERIALIZATION as TTS_JSON_SERIALIZATION,
    NO_COMPRESSION,
    PROTOCOL_VERSION,
    WITH_EVENT,
    AsyncTTSStreamingClient,
    EventConnectionStarted,
    EventSessionFinished,
)


def test_parse_response_decodes_gzip_json_full_response() -> None:
    payload = gzip.compress(json.dumps({"result": {"text": "hello"}}).encode("utf-8"))
    frame = (
        generate_header(
            message_type=FULL_SERVER_RESPONSE,
            message_type_specific_flags=POS_SEQUENCE | LAST_PACKAGE,
            serialization=JSON_SERIALIZATION,
            compression=GZIP_COMPRESSION,
        )
        + (3).to_bytes(4, "big", signed=True)
        + len(payload).to_bytes(4, "big", signed=True)
        + payload
    )

    result = parse_response(frame)

    assert result == {
        "is_last_package": True,
        "payload_sequence": 3,
        "payload_msg": {"result": {"text": "hello"}},
        "payload_size": len(payload),
    }


def test_parse_response_decodes_ack_without_payload() -> None:
    frame = generate_header(message_type=SERVER_ACK) + (7).to_bytes(4, "big", signed=True)

    result = parse_response(frame)

    assert result == {"is_last_package": False, "seq": 7}


def test_parse_response_raises_protocol_error_for_server_error() -> None:
    payload = gzip.compress(json.dumps({"message": "denied"}).encode("utf-8"))
    frame = (
        generate_header(
            message_type=SERVER_ERROR_RESPONSE,
            serialization=JSON_SERIALIZATION,
            compression=GZIP_COMPRESSION,
        )
        + (403).to_bytes(4, "big", signed=False)
        + len(payload).to_bytes(4, "big", signed=False)
        + payload
    )

    with pytest.raises(ProtocolError, match="Server error \\(code=403\\): denied"):
        parse_response(frame)


def _tts_server_header(*, compression: int = NO_COMPRESSION) -> bytes:
    return bytes(
        [
            (PROTOCOL_VERSION << 4) | HEADER_SIZE,
            (binary_protocol.FULL_SERVER_RESPONSE << 4) | WITH_EVENT,
            (TTS_JSON_SERIALIZATION << 4) | compression,
            0x00,
        ]
    )


def _tts_event_frame(
    event_code: int,
    *,
    connection_id: str | None = None,
    session_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> bytes:
    body = struct.pack(">I", event_code)
    if connection_id is not None:
        encoded_connection_id = connection_id.encode("utf-8")
        body += struct.pack(">I", len(encoded_connection_id)) + encoded_connection_id
    if session_id is not None:
        encoded_session_id = session_id.encode("utf-8")
        body += struct.pack(">I", len(encoded_session_id)) + encoded_session_id
    encoded_payload = json.dumps(payload or {}).encode("utf-8")
    body += struct.pack(">I", len(encoded_payload)) + encoded_payload
    return _tts_server_header() + body


def test_tts_parse_frame_decodes_connection_event_id() -> None:
    client = AsyncTTSStreamingClient("access-key", "app-key")

    frame = client._parse_frame(
        _tts_event_frame(
            EventConnectionStarted,
            connection_id="conn-1",
            payload={"ok": True},
        )
    )

    assert frame == {
        "kind": "event",
        "data": {
            "event": EventConnectionStarted,
            "connection_id": "conn-1",
            "payload": {"ok": True},
        },
    }


def test_tts_parse_frame_marks_session_finished() -> None:
    client = AsyncTTSStreamingClient("access-key", "app-key")

    frame = client._parse_frame(
        _tts_event_frame(
            EventSessionFinished,
            session_id="session-1",
            payload={"done": True},
        )
    )

    assert frame == {
        "kind": "event",
        "data": {
            "event": EventSessionFinished,
            "session_finished": True,
            "session_id": "session-1",
            "payload": {"done": True},
        },
    }
