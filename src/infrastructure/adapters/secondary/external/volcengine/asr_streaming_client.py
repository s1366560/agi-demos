"""Async streaming ASR client for Volcengine V3 BigModel speech recognition.

Connects to the Volcengine ASR V3 WebSocket endpoint and streams PCM audio
for real-time transcription.  Framing follows the binary protocol defined in
``binary_protocol.py``.

Usage::

    client = AsyncASRStreamingClient(
        access_key="...", app_key="...",
    )
    await client.connect()
    await client.send_audio(pcm_chunk)
    result = await client.receive()
    await client.send_audio(last_chunk, is_last=True)
    await client.close()

Reference: https://www.volcengine.com/docs/6561/1354870
"""

from __future__ import annotations

import gzip
import json
import logging
import struct
import uuid
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from src.infrastructure.adapters.secondary.external.volcengine.binary_protocol import (
    AUDIO_ONLY_REQUEST,
    FULL_CLIENT_REQUEST,
    GZIP_COMPRESSION,
    JSON_SERIALIZATION,
    LAST_PACKAGE,
    NO_SEQUENCE,
    POS_SEQUENCE,
    generate_before_payload,
    generate_header,
    parse_response,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

_DEFAULT_WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
_RESOURCE_ID = "volc.bigasr.sauc.duration"


class ASRConnectionError(Exception):
    """Raised when the ASR WebSocket connection or handshake fails."""


class AsyncASRStreamingClient:
    """Bidirectional streaming ASR client for Volcengine V3 BigModel.

    The client manages a single WebSocket session: connect, stream audio
    frames, receive incremental transcription results, and close.

    Args:
        access_key: Volcengine API access key.
        app_key: Application key for the ASR resource.
        ws_url: WebSocket endpoint URL.  Defaults to the BigModel ASR V3
            endpoint.
    """

    def __init__(
        self,
        access_key: str,
        app_key: str,
        ws_url: str = _DEFAULT_WS_URL,
    ) -> None:
        super().__init__()
        self._access_key = access_key
        self._app_key = app_key
        self._ws_url = ws_url
        self._ws: ClientConnection | None = None
        self._request_id = str(uuid.uuid4())
        self._sequence = 1

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the WebSocket and perform the full-client handshake.

        Raises:
            ASRConnectionError: If the connection or handshake fails.
        """
        headers = {
            "X-Api-Resource-Id": _RESOURCE_ID,
            "X-Api-Access-Key": self._access_key,
            "X-Api-App-Key": self._app_key,
            "X-Api-Request-Id": self._request_id,
        }

        logger.info(
            "ASR connecting to %s (request_id=%s)",
            self._ws_url,
            self._request_id,
        )

        try:
            self._ws = await connect(
                self._ws_url,
                additional_headers=headers,
                max_size=None,
                open_timeout=10,
            )
        except Exception as exc:
            raise ASRConnectionError(f"Failed to connect to ASR endpoint: {exc}") from exc

        await self._send_handshake()
        logger.info("ASR handshake completed (request_id=%s)", self._request_id)

    async def close(self) -> None:
        """Close the WebSocket gracefully."""
        if self._ws is not None:
            try:
                await self._ws.close()
            except ConnectionClosed:
                pass
            finally:
                self._ws = None
                logger.info("ASR connection closed (request_id=%s)", self._request_id)

    @property
    def is_connected(self) -> bool:
        """Return ``True`` when the underlying WebSocket is open."""
        return self._ws is not None and self._ws.state.name == "OPEN"

    # ------------------------------------------------------------------
    # Audio streaming
    # ------------------------------------------------------------------

    async def send_audio(self, audio_data: bytes, *, is_last: bool = False) -> None:
        """Send a PCM audio chunk to the server.

        Args:
            audio_data: Raw PCM-16 LE audio bytes (16 kHz, mono).
            is_last: When ``True`` the ``LAST_PACKAGE`` flag is set so the
                server knows no more audio will follow.

        Raises:
            ASRConnectionError: If no active connection exists.
        """
        if self._ws is None:
            raise ASRConnectionError("Not connected -- call connect() first")

        flags = LAST_PACKAGE if is_last else NO_SEQUENCE
        header = generate_header(
            message_type=AUDIO_ONLY_REQUEST,
            message_type_specific_flags=flags,
            serialization=JSON_SERIALIZATION,
            compression=GZIP_COMPRESSION,
        )

        compressed = gzip.compress(audio_data)
        payload_size = struct.pack(">I", len(compressed))
        frame = header + payload_size + compressed

        await self._ws.send(frame)
        self._sequence += 1
        if self._sequence == 2:
            logger.debug(
                "ASR first audio packet sent: %d bytes raw, %d bytes compressed",
                len(audio_data),
                len(compressed),
            )
        elif self._sequence % 100 == 0:
            logger.debug("ASR audio packets sent: seq=%d", self._sequence)
        if is_last:
            logger.info("ASR sent last audio packet (seq=%d)", self._sequence)

    # ------------------------------------------------------------------
    # Receive results
    # ------------------------------------------------------------------

    async def receive(self) -> dict[str, Any] | None:
        """Wait for the next transcription result from the server.

        Returns:
            A dict produced by :func:`parse_response`, or ``None`` when the
            connection is closed cleanly.
        """
        if self._ws is None:
            return None

        try:
            raw = await self._ws.recv(decode=False)
        except ConnectionClosed:
            logger.info("ASR connection closed by server")
            self._ws = None
            return None


        parsed = parse_response(raw)
        payload: dict[str, Any] = parsed.get("payload_msg", {})
        result: dict[str, Any] = payload.get("result", {})
        text = result.get("text", "")
        utterances: list[dict[str, Any]] = result.get("utterances", [])

        is_final = any(bool(u.get("definite")) for u in utterances)
        logger.debug(
            "ASR recv seq=%s final=%s text=%r",
            parsed.get("payload_sequence"),
            is_final,
            text[:80] if text else "",
        )
        return parsed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_handshake(self) -> None:
        """Send the initial ``FULL_CLIENT_REQUEST`` and validate the ack."""
        if self._ws is None:
            raise ASRConnectionError("WebSocket not open")

        handshake_payload: dict[str, Any] = {
            "user": {"uid": "memstack"},
            "audio": {
                "format": "pcm",
                "codec": "raw",
                "sample_rate": 16000,
                "channel": 1,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
            },
        }

        logger.debug("ASR handshake payload: %s", handshake_payload)

        payload_json = json.dumps(handshake_payload).encode("utf-8")
        compressed_payload = gzip.compress(payload_json)

        header = generate_header(
            message_type=FULL_CLIENT_REQUEST,
            message_type_specific_flags=POS_SEQUENCE,
            serialization=JSON_SERIALIZATION,
            compression=GZIP_COMPRESSION,
        )
        seq_bytes = generate_before_payload(sequence=self._sequence)
        payload_size = struct.pack(">I", len(compressed_payload))

        frame = header + seq_bytes + payload_size + compressed_payload
        await self._ws.send(frame)
        self._sequence += 1

        # Wait for handshake ack
        try:
            raw_resp = await self._ws.recv(decode=False)
        except ConnectionClosed as exc:
            raise ASRConnectionError("Connection closed during ASR handshake") from exc


        resp = parse_response(raw_resp)
        payload_msg: dict[str, Any] = resp.get("payload_msg", {})
        if payload_msg.get("code") and payload_msg["code"] != 0:
            raise ASRConnectionError(f"ASR handshake rejected: {payload_msg}")
