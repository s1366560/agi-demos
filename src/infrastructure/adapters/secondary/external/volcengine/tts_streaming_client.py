"""Async streaming TTS client for Volcengine V3 bidirectional speech synthesis.

Connects to the Volcengine TTS V3 bidirectional WebSocket endpoint, sends
text, and yields synthesized audio chunks as they arrive.

The TTS protocol uses an *event-based* binary framing scheme where each
frame carries a 4-byte header followed by event-specific fields.  The frame
layout varies per event type -- see ``_write_message`` for details.

Usage::

    client = AsyncTTSStreamingClient(
        access_key="...", app_key="...",
    )
    await client.connect()
    async for audio_chunk in client.synthesize("Hello world"):
        play(audio_chunk)
    await client.close()

Reference: https://www.volcengine.com/docs/6561/1354869
Reference impl: ai-app-lab/arkitect/core/component/tts/
"""

from __future__ import annotations

import gzip
import json
import logging
import struct
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol constants (TTS-specific, matching reference constants.py)
# ---------------------------------------------------------------------------

PROTOCOL_VERSION: int = 0b0001
HEADER_SIZE: int = 0b0001  # header_size in units of 4 bytes -> 4 bytes total

# Message types (upper nibble of byte 1)
FULL_CLIENT: int = 0b0001
AUDIO_ONLY_SERVER: int = 0b0100
ERROR_SERVER: int = 0b0110

# Message-type-specific flags (lower nibble of byte 1)
WITH_EVENT: int = 0b0100

# Serialization (upper nibble of byte 2)
JSON_SERIALIZATION: int = 0b0001
NO_SERIALIZATION: int = 0b0000

# Compression (lower nibble of byte 2)
GZIP_COMPRESSION: int = 0b0001
NO_COMPRESSION: int = 0b0000

# ---------------------------------------------------------------------------
# Event codes (matching reference constants.py)
# ---------------------------------------------------------------------------

EventStartConnection: int = 1
EventFinishConnection: int = 2

EventConnectionStarted: int = 50
EventConnectionFailed: int = 51
EventConnectionFinished: int = 52

EventStartSession: int = 100
EventFinishSession: int = 102

EventSessionStarted: int = 150
EventSessionFinished: int = 152
EventSessionFailed: int = 153

EventTaskRequest: int = 200

EventTTSSentenceStart: int = 350
EventTTSSentenceEnd: int = 351

NAMESPACE: str = "BidirectionalTTS"
DEFAULT_SPEAKER: str = "zh_female_tianmeixiaoyuan_moon_bigtts"

_DEFAULT_WS_URL = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
_RESOURCE_ID = "volc.service_type.10029"

# Events whose server responses carry a connection_id (NOT session_id)
_CONNECTION_EVENTS = frozenset(
    {
        EventStartConnection,
        EventFinishConnection,
        EventConnectionStarted,
        EventConnectionFailed,
        EventConnectionFinished,
    }
)


class TTSConnectionError(Exception):
    """Raised when the TTS WebSocket connection or session setup fails."""


# ---------------------------------------------------------------------------
# Low-level frame construction (matches reference model.py _write_message)
# ---------------------------------------------------------------------------


def _build_header() -> bytes:
    """Build the 4-byte TTS protocol header.

    Always uses JSON serialization with NO compression, matching the
    reference implementation.
    """
    byte0 = (PROTOCOL_VERSION << 4) | HEADER_SIZE
    byte1 = (FULL_CLIENT << 4) | WITH_EVENT
    byte2 = (JSON_SERIALIZATION << 4) | NO_COMPRESSION
    byte3 = 0x00
    return bytes([byte0, byte1, byte2, byte3])


def _write_message(
    event: int,
    payload: str,
    connection_id: str | None = None,
    session_id: str | None = None,
) -> bytes:
    """Encode event-specific body (everything after the 4-byte header).

    Matches the reference ``_write_message`` in model.py exactly::

        event_code (4B)
        [connection_id_len (4B) + connection_id]   -- only if connection_id is not None
        [session_id_len (4B) + session_id]         -- only if session_id is not None
        payload_len (4B) + payload (raw UTF-8)

    Which fields are included depends on the event type -- the caller is
    responsible for passing the correct combination.
    """
    frame = struct.pack(">I", event)
    if connection_id is not None:
        cid_bytes = connection_id.encode("utf-8")
        frame += struct.pack(">I", len(cid_bytes)) + cid_bytes
    if session_id is not None:
        sid_bytes = session_id.encode("utf-8")
        frame += struct.pack(">I", len(sid_bytes)) + sid_bytes
    payload_bytes = payload.encode("utf-8")
    frame += struct.pack(">I", len(payload_bytes)) + payload_bytes
    return frame


class AsyncTTSStreamingClient:
    """Bidirectional streaming TTS client for Volcengine V3.

    Args:
        access_key: Volcengine API access key (speech_access_token).
        app_key: Application key for the TTS resource (speech_app_id).
        speaker: Voice speaker identifier.
        ws_url: WebSocket endpoint URL.
    """

    def __init__(
        self,
        access_key: str,
        app_key: str,
        speaker: str = DEFAULT_SPEAKER,
        ws_url: str = _DEFAULT_WS_URL,
        proxy: str | None = None,
    ) -> None:
        super().__init__()
        self._access_key = access_key
        self._app_key = app_key
        self._speaker = speaker
        self._ws_url = ws_url
        self._proxy: str | bool = proxy if proxy is not None else True
        self._ws: ClientConnection | None = None
        self._connect_id = str(uuid.uuid4())
        self._session_id = ""

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open WebSocket connection, start connection and session.

        The handshake follows three steps:

        1. TCP + TLS WebSocket upgrade with auth headers.
        2. ``EventStartConnection`` (1) -> wait ``EventConnectionStarted`` (50).
        3. ``EventStartSession`` (100) -> wait ``EventSessionStarted`` (150).

        Raises:
            TTSConnectionError: On any connection / handshake failure.
        """
        headers = {
            "X-Api-Resource-Id": _RESOURCE_ID,
            "X-Api-Access-Key": self._access_key,
            "X-Api-App-Key": self._app_key,
            "X-Api-Connect-Id": self._connect_id,
            "X-Tt-Logid": str(uuid.uuid4()),
        }

        logger.info(
            "TTS connecting to %s (connect_id=%s)",
            self._ws_url,
            self._connect_id,
        )

        try:
            self._ws = await connect(
                self._ws_url,
                additional_headers=headers,
                max_size=None,
                open_timeout=10,
                proxy=self._proxy,
            )
        except Exception as exc:
            raise TTSConnectionError(f"Failed to connect to TTS endpoint: {exc}") from exc

        # Step 1 -- EventStartConnection
        # Reference: msg.write_start_connection() -> _write_message(event=1, payload="{}")
        # NO connection_id, NO session_id
        frame = _build_header() + _write_message(event=EventStartConnection, payload="{}")
        await self._send_frame(frame)
        resp = await self._read_event()
        event_code = resp.get("event", -1)
        if event_code == EventConnectionFailed:
            raise TTSConnectionError(f"TTS EventConnectionFailed: {resp}")
        if event_code != EventConnectionStarted:
            raise TTSConnectionError(f"Expected EventConnectionStarted(50), got event={event_code}")
        logger.debug("TTS connection started")

        # Step 2 -- EventStartSession
        # Reference: msg.write_start_tts_session() -> _write_message(
        #     event=100, connection_id=conn_id, payload=json.dumps(session_config))
        # WITH connection_id, NO session_id
        session_config: dict[str, Any] = {
            "event": EventStartSession,
            "namespace": NAMESPACE,
            "req_params": {
                "audio_params": {
                    "format": "mp3",
                    "sample_rate": 24000,
                },
                "speaker": self._speaker,
            },
        }
        frame = _build_header() + _write_message(
            event=EventStartSession,
            connection_id=self._connect_id,
            payload=json.dumps(session_config, ensure_ascii=False),
        )
        await self._send_frame(frame)
        resp = await self._read_event()
        event_code = resp.get("event", -1)
        if event_code != EventSessionStarted:
            raise TTSConnectionError(
                f"Expected EventSessionStarted(150), got event={event_code}, resp={resp}"
            )
        self._session_id = resp.get("session_id", "")
        logger.info("TTS session started (session_id=%s)", self._session_id)

    async def close(self) -> None:
        """Send ``EventFinishSession`` and close the WebSocket."""
        if self._ws is not None:
            try:
                # FinishSession: WITH session_id, NO connection_id
                frame = _build_header() + _write_message(
                    event=EventFinishSession,
                    session_id=self._session_id,
                    payload=json.dumps({}),
                )
                await self._send_frame(frame)
            except (ConnectionClosed, TTSConnectionError):
                pass
            try:
                await self._ws.close()
            except ConnectionClosed:
                pass
            finally:
                self._ws = None
                logger.info(
                    "TTS connection closed (connect_id=%s)",
                    self._connect_id,
                )

    @property
    def is_connected(self) -> bool:
        """Return ``True`` when the underlying WebSocket is open."""
        return self._ws is not None and self._ws.state.name == "OPEN"

    # ------------------------------------------------------------------
    # Text -> Audio streaming
    # ------------------------------------------------------------------

    async def synthesize(self, text: str) -> AsyncGenerator[bytes, None]:
        """Send *text* for synthesis and yield audio chunks.

        Args:
            text: Plain text to synthesize.

        Yields:
            Raw audio bytes (MP3 by default, determined by session params).

        Raises:
            TTSConnectionError: If not connected.
        """
        if self._ws is None:
            raise TTSConnectionError("Not connected -- call connect() first")

        # TaskRequest: WITH session_id, NO connection_id
        # Reference: msg.write_text_request() with TTSRequest payload
        req_params: dict[str, Any] = {
            "audio_params": {
                "format": "mp3",
                "sample_rate": 24000,
            },
            "speaker": self._speaker,
            "text": text,
        }
        task_payload: dict[str, Any] = {
            "event": EventTaskRequest,
            "namespace": NAMESPACE,
            "req_params": req_params,
        }
        frame = _build_header() + _write_message(
            event=EventTaskRequest,
            session_id=self._session_id,
            payload=json.dumps(task_payload, ensure_ascii=False),
        )
        await self._send_frame(frame)

        # Signal end of text so server will send EventSessionFinished
        # Reference: after sending all text, _send_finish_session() is called
        finish_frame = _build_header() + _write_message(
            event=EventFinishSession,
            session_id=self._session_id,
            payload=json.dumps({}),
        )
        await self._send_frame(finish_frame)
        # Read response frames until the task or session finishes
        while True:
            raw = await self._recv_raw()
            if raw is None:
                return

            frame_result = self._parse_frame(raw)
            if frame_result is None:
                continue

            kind = frame_result["kind"]
            if kind == "audio":
                audio: bytes = frame_result["data"]
                yield audio
            elif kind == "event":
                event_data: dict[str, Any] = frame_result["data"]
                evt = event_data.get("event", -1)
                if evt in (
                    EventSessionFinished,
                    EventFinishConnection,
                    EventConnectionFinished,
                ):
                    logger.debug("TTS synthesis finished (event=%s)", evt)
                    return
                if evt == EventTTSSentenceStart:
                    logger.debug(
                        "TTS sentence start: %s",
                        event_data.get("payload", ""),
                    )
                elif evt == EventTTSSentenceEnd:
                    logger.debug(
                        "TTS sentence end: %s",
                        event_data.get("payload", ""),
                    )
                else:
                    logger.debug("TTS event %s received", evt)

    # ------------------------------------------------------------------
    # Low-level I/O
    # ------------------------------------------------------------------

    async def _send_frame(self, frame: bytes) -> None:
        """Send a binary frame over the WebSocket."""
        if self._ws is None:
            raise TTSConnectionError("WebSocket not open")
        await self._ws.send(frame)

    async def _recv_raw(self) -> bytes | None:
        """Receive the next binary WebSocket message.

        Returns ``None`` when the connection is closed.
        """
        if self._ws is None:
            return None
        try:
            data = await self._ws.recv(decode=False)
        except ConnectionClosed:
            logger.info("TTS connection closed by server")
            self._ws = None
            return None
        return data

    async def _read_event(self) -> dict[str, Any]:
        """Convenience wrapper: receive and parse a JSON event frame.

        Raises:
            TTSConnectionError: If the connection closes before an event
                arrives or the frame cannot be parsed as a JSON event.
        """
        raw = await self._recv_raw()
        if raw is None:
            raise TTSConnectionError("Connection closed while waiting for TTS event")
        frame = self._parse_frame(raw)
        if frame is None or frame["kind"] != "event":
            raise TTSConnectionError(f"Expected JSON event frame, got: {frame}")
        result: dict[str, Any] = frame["data"]
        return result

    # ------------------------------------------------------------------
    # Frame parsing (matches reference utils.py parse_response)
    # ------------------------------------------------------------------

    def _parse_frame(self, data: bytes) -> dict[str, Any] | None:
        """Decode a server frame into either an audio or event dict.

        Returns:
            ``{"kind": "audio", "data": <bytes>}`` for audio frames, or
            ``{"kind": "event", "data": <dict>}`` for JSON event frames.
            Returns ``None`` when the frame is too short.
        """
        if len(data) < 4:
            logger.warning("TTS frame too short (%d bytes)", len(data))
            return None

        header_size_field = data[0] & 0x0F
        msg_type = (data[1] >> 4) & 0x0F
        msg_flags = data[1] & 0x0F
        serialization = (data[2] >> 4) & 0x0F
        compression = data[2] & 0x0F

        offset = header_size_field * 4

        # Audio-only server response
        if msg_type == AUDIO_ONLY_SERVER or serialization == NO_SERIALIZATION:
            return self._parse_audio_frame(data, offset, compression)

        # Error response (msg_type=0b0110 = 6)
        if msg_type == ERROR_SERVER:
            return self._parse_error_frame(data, offset, serialization, compression)

        # JSON event frame (FULL_SERVER or similar)
        return self._parse_json_event_frame(data, offset, msg_flags, serialization, compression)

    def _parse_audio_frame(
        self,
        data: bytes,
        offset: int,
        compression: int,
    ) -> dict[str, Any] | None:
        """Extract raw audio bytes from an audio-only frame."""
        if len(data) <= offset:
            return None

        # Audio frames have: payload_size(4B) + payload
        if len(data) >= offset + 4:
            (declared_size,) = struct.unpack(">I", data[offset : offset + 4])
            remaining = len(data) - offset - 4
            if declared_size == remaining:
                offset += 4
                audio_bytes = data[offset : offset + declared_size]
            else:
                audio_bytes = data[offset:]
        else:
            audio_bytes = data[offset:]

        if compression == GZIP_COMPRESSION and audio_bytes:
            try:
                audio_bytes = gzip.decompress(audio_bytes)
            except gzip.BadGzipFile:
                pass  # Already decompressed or raw

        return {"kind": "audio", "data": audio_bytes}

    def _parse_error_frame(
        self,
        data: bytes,
        offset: int,
        serialization: int,
        compression: int,
    ) -> dict[str, Any]:
        """Parse an error frame (msg_type=0b0110).

        Error frames contain: event_code(4B) + payload_len(4B) + payload
        No connection_id or session_id fields.
        """
        result: dict[str, Any] = {"error": True}

        # event_code
        if len(data) >= offset + 4:
            (event_code,) = struct.unpack(">I", data[offset : offset + 4])
            offset += 4
            result["event"] = event_code

        # payload_len + payload
        if len(data) >= offset + 4:
            (payload_len,) = struct.unpack(">I", data[offset : offset + 4])
            offset += 4
            if payload_len > 0 and len(data) >= offset + payload_len:
                payload_bytes = data[offset : offset + payload_len]
                payload_bytes = self._decompress(payload_bytes, compression)
                if serialization == JSON_SERIALIZATION:
                    try:
                        parsed: dict[str, Any] = json.loads(payload_bytes)
                        result["payload"] = parsed
                        logger.error(
                            "TTS server error event=%s: %s",
                            result.get("event"),
                            parsed,
                        )
                    except json.JSONDecodeError:
                        result["payload_raw"] = payload_bytes.decode("utf-8", errors="replace")

        return {"kind": "event", "data": result}

    def _parse_json_event_frame(
        self,
        data: bytes,
        offset: int,
        msg_flags: int,
        serialization: int,
        compression: int,
    ) -> dict[str, Any] | None:
        """Decode a JSON event frame following reference parse_response.

        The layout after the header depends on the event type:

        - Connection events (1, 2, 50, 51, 52): have connection_id
        - Session/task events (others): have session_id
        - EventSessionFinished (152) sets session_finished flag

        Layout::
            event_code (4B)
            [session_id_len (4B) + session_id]  -- for non-connection events
            [connection_id_len (4B) + connection_id]  -- for connection events
            payload_len (4B) + payload
        """
        result: dict[str, Any] = {}

        has_event = (msg_flags & 0x04) != 0  # WITH_EVENT flag

        if not has_event:
            # No event field, just payload
            return self._parse_bare_payload(data, offset, serialization, compression)

        # event_code (4B)
        if len(data) < offset + 4:
            return self._fallback_json_parse(data, offset, compression)

        (event_code,) = struct.unpack(">I", data[offset : offset + 4])
        offset += 4
        result["event"] = event_code

        if event_code == EventSessionFinished:
            result["session_finished"] = True

        # Determine which ID field follows based on event type
        # Reference utils.py: connection events have connection_id,
        # others (except StartConnection/FinishConnection) have session_id
        if event_code in _CONNECTION_EVENTS:
            # Connection-level events
            # StartConnection(1)/FinishConnection(2) in client->server
            # don't carry IDs but server responses (50/51/52) carry
            # connection_id
            if event_code in (
                EventConnectionStarted,
                EventConnectionFailed,
                EventConnectionFinished,
            ):
                # connection_id_len + connection_id
                if len(data) >= offset + 4:
                    (cid_len,) = struct.unpack(">I", data[offset : offset + 4])
                    offset += 4
                    if cid_len > 0 and len(data) >= offset + cid_len:
                        result["connection_id"] = data[offset : offset + cid_len].decode(
                            "utf-8", errors="replace"
                        )
                        offset += cid_len
        else:
            # Session/task events have session_id
            if len(data) >= offset + 4:
                (sid_len,) = struct.unpack(">I", data[offset : offset + 4])
                offset += 4
                if sid_len > 0 and len(data) >= offset + sid_len:
                    result["session_id"] = data[offset : offset + sid_len].decode(
                        "utf-8", errors="replace"
                    )
                    offset += sid_len

        # payload_len (4B) + payload
        if len(data) >= offset + 4:
            (payload_len,) = struct.unpack(">I", data[offset : offset + 4])
            offset += 4
            if payload_len > 0 and len(data) >= offset + payload_len:
                payload_bytes = data[offset : offset + payload_len]
                payload_bytes = self._decompress(payload_bytes, compression)
                if serialization == JSON_SERIALIZATION:
                    try:
                        parsed: dict[str, Any] = json.loads(payload_bytes)
                        result["payload"] = parsed
                    except json.JSONDecodeError:
                        result["payload_raw"] = payload_bytes.decode("utf-8", errors="replace")

        return {"kind": "event", "data": result}

    def _parse_bare_payload(
        self,
        data: bytes,
        offset: int,
        serialization: int,
        compression: int,
    ) -> dict[str, Any] | None:
        """Parse a frame with no event field (just payload)."""
        if len(data) < offset + 4:
            return None
        (payload_len,) = struct.unpack(">I", data[offset : offset + 4])
        offset += 4
        result: dict[str, Any] = {}
        if payload_len > 0 and len(data) >= offset + payload_len:
            payload_bytes = data[offset : offset + payload_len]
            payload_bytes = self._decompress(payload_bytes, compression)
            if serialization == JSON_SERIALIZATION:
                try:
                    parsed: dict[str, Any] = json.loads(payload_bytes)
                    result["payload"] = parsed
                except json.JSONDecodeError:
                    result["payload_raw"] = payload_bytes.decode("utf-8", errors="replace")
        return {"kind": "event", "data": result}

    @staticmethod
    def _decompress(data: bytes, compression: int) -> bytes:
        """Decompress payload if GZIP, otherwise return as-is."""
        if compression == GZIP_COMPRESSION:
            try:
                return gzip.decompress(data)
            except gzip.BadGzipFile:
                return data
        return data

    def _fallback_json_parse(
        self,
        data: bytes,
        offset: int,
        compression: int,
    ) -> dict[str, Any] | None:
        """Last-resort: try to treat the remainder as bare JSON."""
        raw = data[offset:]
        if compression == GZIP_COMPRESSION:
            try:
                raw = gzip.decompress(raw)
            except gzip.BadGzipFile:
                pass
        try:
            parsed: dict[str, Any] = json.loads(raw)
            return {"kind": "event", "data": parsed}
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("TTS could not parse frame (%d bytes)", len(data))
            return None
