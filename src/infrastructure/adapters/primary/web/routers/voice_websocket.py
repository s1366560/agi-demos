"""Voice WebSocket endpoint for real-time ASR/TTS streaming pipeline.

Receives PCM audio from browser, streams to Volcengine ASR for transcription,
feeds transcriptions into the agent pipeline, streams agent response text
through Volcengine TTS, and sends synthesized audio back to browser.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, cast

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.config import get_settings
from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.primary.web.websocket.auth import authenticate_websocket
from src.infrastructure.adapters.secondary.persistence.database import get_db

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])
logger = logging.getLogger(__name__)

# Sentence boundary pattern for TTS chunking
_SENTENCE_BOUNDARY = re.compile(r"[.!?\u3002\uff01\uff1f]")

# Maximum buffer size before forcing a TTS flush
_MAX_BUFFER_CHARS = 100

# Silence threshold (seconds) -- when no new ASR text arrives for this
# long, treat the accumulated buffer as a complete utterance.  Matches the
# reference implementation's ASRInterval=2000ms approach.
_ASR_SILENCE_THRESHOLD = 1.5


@router.websocket("/chat")
async def voice_chat_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    project_id: str = Query(...),
    conversation_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Voice chat WebSocket endpoint.

    Protocol:
    - Client sends initial JSON config: {type: "voice_config", sample_rate, speaker}
    - Client sends binary frames (PCM audio)
    - Server sends binary frames (TTS audio)
    - Server sends JSON text frames for control messages
    """
    # 1. Authenticate
    auth_result = await authenticate_websocket(token, db)
    if not auth_result:
        await websocket.close(code=4003, reason="Authentication failed")
        return
    user_id, tenant_id = auth_result

    # 2. Accept WebSocket
    await websocket.accept()
    logger.info(
        "[Voice WS] Connected user=%s tenant=%s conv=%s",
        user_id[:8],
        tenant_id[:8],
        conversation_id[:8],
    )

    # 3. Receive initial config message
    try:
        config_msg = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning("[Voice WS] Failed to receive config: %s", e)
        await _send_error(websocket, "Expected voice_config message within 10 seconds")
        await websocket.close(code=4000)
        return

    if config_msg.get("type") != "voice_config":
        await _send_error(websocket, "First message must be type 'voice_config'")
        await websocket.close(code=4000)
        return

    _sample_rate: int = config_msg.get("sample_rate", 16000)
    speaker: str = config_msg.get("speaker", "zh_female_tianmeixiaoyuan_moon_bigtts")

    # 4. Resolve Volcengine Speech Console credentials (DB first, env fallback)
    settings = get_settings()
    speech_access_token: str | None = settings.speech_access_token
    speech_app_id: str | None = settings.speech_app_id

    try:
        from src.infrastructure.persistence.llm_providers_models import (
            LLMProvider as LLMProviderORM,
        )

        result = await db.execute(
            select(LLMProviderORM)
            .where(LLMProviderORM.provider_type.like("volcengine%"))
            .where(LLMProviderORM.is_active.is_(True))
            .limit(1)
        )
        provider = result.scalar_one_or_none()
        if provider and provider.config:
            db_cfg: dict[str, Any] = provider.config
            speech_access_token = db_cfg.get("speech_access_token") or speech_access_token
            speech_app_id = db_cfg.get("speech_app_id") or speech_app_id
            logger.info(
                "[Voice WS] Resolved Speech credentials from DB: "
                "access_token=%s app_id=%s",
                bool(speech_access_token),
                bool(speech_app_id),
            )
    except Exception:
        logger.warning(
            "[Voice WS] Failed to read provider config from DB, using env vars",
            exc_info=True,
        )
    if not speech_access_token or not speech_app_id:
        await _send_error(
            websocket,
            "Volcengine Speech credentials not configured "
            "(set speech_app_id + speech_access_token in provider config "
            "or SPEECH_APP_ID + SPEECH_ACCESS_TOKEN env vars)",
        )
        await websocket.close(code=4000)
        return

    from src.infrastructure.adapters.secondary.external.volcengine.asr_streaming_client import (
        AsyncASRStreamingClient,
    )
    from src.infrastructure.adapters.secondary.external.volcengine.tts_streaming_client import (
        AsyncTTSStreamingClient,
    )

    asr_client = AsyncASRStreamingClient(
        speech_access_token,
        speech_app_id,
    )
    tts_client: AsyncTTSStreamingClient | None = None

    # 5. Build agent service (same pattern as chat_handler.py)
    from src.configuration.factories import create_llm_client

    base_container = cast(DIContainer, websocket.app.state.container)
    container = base_container.with_db(db)

    llm = await create_llm_client(tenant_id)
    agent_service = container.agent_service(llm)

    # Shared state between tasks
    asr_final_queue: asyncio.Queue[str] = asyncio.Queue()
    tts_text_queue: asyncio.Queue[str | None] = asyncio.Queue()
    shutdown_event = asyncio.Event()
    tasks: list[asyncio.Task[None]] = []

    try:
        # Connect ASR client
        await asr_client.connect()

        # 6. Launch concurrent tasks
        tasks = [
            asyncio.create_task(
                _audio_receiver(websocket, asr_client, shutdown_event),
                name="audio_receiver",
            ),
            asyncio.create_task(
                _asr_processor(websocket, asr_client, asr_final_queue, shutdown_event),
                name="asr_processor",
            ),
            asyncio.create_task(
                _agent_bridge(
                    websocket,
                    agent_service,
                    asr_final_queue,
                    tts_text_queue,
                    conversation_id,
                    project_id,
                    user_id,
                    tenant_id,
                    shutdown_event,
                ),
                name="agent_bridge",
            ),
            asyncio.create_task(
                _tts_sender(
                    websocket,
                    tts_text_queue,
                    speech_access_token,
                    speech_app_id,
                    speaker,
                    shutdown_event,
                ),
                name="tts_sender",
            ),
        ]

        # Wait for any task to complete (usually means disconnect or error)
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        # Check for exceptions in completed tasks
        for task in done:
            if task.exception() and not isinstance(
                task.exception(), (asyncio.CancelledError, WebSocketDisconnect)
            ):
                logger.error(
                    "[Voice WS] Task %s failed: %s",
                    task.get_name(),
                    task.exception(),
                    exc_info=task.exception(),
                )

    except WebSocketDisconnect:
        logger.info("[Voice WS] Client disconnected conv=%s", conversation_id[:8])
    except Exception as e:
        logger.error("[Voice WS] Unexpected error: %s", e, exc_info=True)
    finally:
        # 8. Cleanup
        shutdown_event.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        # Wait for cancellation to propagate
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Close ASR client
        try:
            await asr_client.close()
        except Exception:
            pass

        # Close TTS client if it was created inline
        if tts_client is not None:
            try:
                await tts_client.close()
            except Exception:
                pass

        logger.info("[Voice WS] Cleanup complete conv=%s", conversation_id[:8])


# =============================================================================
# Concurrent Task Functions
# =============================================================================


async def _audio_receiver(
    websocket: WebSocket,
    asr_client: Any,
    shutdown: asyncio.Event,
) -> None:
    """Receive binary PCM audio frames from browser and forward to ASR client."""
    frame_count = 0
    total_bytes = 0
    try:
        while not shutdown.is_set():
            data = await websocket.receive_bytes()
            if not data:
                continue
            frame_count += 1
            total_bytes += len(data)
            if frame_count == 1:
                logger.debug(
                    "[Voice WS] First audio frame received: %d bytes",
                    len(data),
                )
            elif frame_count % 100 == 0:
                logger.debug(
                    "[Voice WS] Audio frames received: count=%d total_bytes=%d",
                    frame_count,
                    total_bytes,
                )
            await asr_client.send_audio(data, is_last=False)
    except WebSocketDisconnect:
        logger.info(
            "[Voice WS] Audio receiver: client disconnected (frames=%d bytes=%d)",
            frame_count,
            total_bytes,
        )
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("[Voice WS] Audio receiver error: %s", e, exc_info=True)
    finally:
        logger.info(
            "[Voice WS] Audio receiver stopping (frames=%d bytes=%d)",
            frame_count,
            total_bytes,
        )
        # Signal end of audio to ASR
        try:
            await asr_client.send_audio(b"", is_last=True)
        except Exception:
            pass
        shutdown.set()

async def _asr_processor(
    websocket: WebSocket,
    asr_client: Any,
    asr_final_queue: asyncio.Queue[str],
    shutdown: asyncio.Event,
) -> None:
    """Receive transcription results from ASR and dispatch complete utterances.

    Uses a **silence-timeout** strategy (matching the Volcengine reference
    implementation) instead of relying on the ``definite`` flag which may not
    be reliably set in streaming mode.

    The algorithm:
    1. Accumulate ``asr_buffer`` from ``result.text``.
    2. Track when the buffer last *grew* (``last_growth_time``).
    3. When the buffer has content and silence exceeds
       ``_ASR_SILENCE_THRESHOLD``, treat the buffer as a complete sentence
       and enqueue it for the agent.
    4. ``definite=True`` is still honoured as an immediate flush trigger.
    """
    import time

    asr_buffer = ""
    last_growth_time: float = time.monotonic()
    pending_interim_sent = False

    try:
        while not shutdown.is_set():
            # Use a short timeout so we can check silence even when no
            # new ASR messages arrive.
            try:
                result = await asyncio.wait_for(
                    asr_client.receive(), timeout=0.3
                )
            except asyncio.TimeoutError:
                # No new ASR data -- check silence timeout
                if (
                    asr_buffer
                    and (time.monotonic() - last_growth_time)
                    > _ASR_SILENCE_THRESHOLD
                ):
                    logger.info(
                        "[Voice WS] ASR silence timeout, flushing: %s",
                        asr_buffer[:80],
                    )
                    await _send_json(
                        websocket, {"type": "asr_final", "text": asr_buffer}
                    )
                    await asr_final_queue.put(asr_buffer)
                    asr_buffer = ""
                    pending_interim_sent = False
                continue

            if result is None:
                break

            payload = result.get("payload_msg", {})
            asr_result = payload.get("result", {})
            text = asr_result.get("text", "")
            utterances = asr_result.get("utterances", [])
            is_definite = any(
                u.get("definite", False) for u in utterances
            )

            logger.debug(
                "[Voice WS] ASR recv text=%r definite=%s buf_len=%d",
                text[:80] if text else "",
                is_definite,
                len(asr_buffer),
            )

            if text:
                # Check if buffer grew (new speech detected)
                if len(text) > len(asr_buffer):
                    last_growth_time = time.monotonic()
                asr_buffer = text

                if is_definite:
                    # Immediate flush on definite utterance
                    logger.info(
                        "[Voice WS] ASR definite utterance: %s",
                        asr_buffer[:80],
                    )
                    await _send_json(
                        websocket,
                        {"type": "asr_final", "text": asr_buffer},
                    )
                    await asr_final_queue.put(asr_buffer)
                    asr_buffer = ""
                    pending_interim_sent = False
                elif not pending_interim_sent or len(text) > len(asr_buffer) - 2:
                    # Send interim update to browser for live display
                    await _send_json(
                        websocket,
                        {"type": "asr_interim", "text": text},
                    )
                    pending_interim_sent = True

            if result.get("is_last_package"):
                # Server signals end of stream -- flush remaining buffer
                if asr_buffer:
                    logger.info(
                        "[Voice WS] ASR last package, flushing: %s",
                        asr_buffer[:80],
                    )
                    await _send_json(
                        websocket,
                        {"type": "asr_final", "text": asr_buffer},
                    )
                    await asr_final_queue.put(asr_buffer)
                    asr_buffer = ""
                break

        # Flush any remaining buffer on normal exit
        if asr_buffer:
            logger.info(
                "[Voice WS] ASR processor exiting, flushing remaining: %s",
                asr_buffer[:80],
            )
            await _send_json(
                websocket, {"type": "asr_final", "text": asr_buffer}
            )
            await asr_final_queue.put(asr_buffer)

    except asyncio.CancelledError:
        # Flush on cancellation too
        if asr_buffer:
            await asr_final_queue.put(asr_buffer)
    except Exception as e:
        logger.error("[Voice WS] ASR processor error: %s", e, exc_info=True)
    finally:
        shutdown.set()

async def _agent_bridge(
    websocket: WebSocket,
    agent_service: Any,
    asr_final_queue: asyncio.Queue[str],
    tts_text_queue: asyncio.Queue[str | None],
    conversation_id: str,
    project_id: str,
    user_id: str,
    tenant_id: str,
    shutdown: asyncio.Event,
) -> None:
    """Process ASR final transcripts through the agent pipeline."""
    try:
        logger.info(
            "[Voice WS] Agent bridge started (conv=%s, project=%s, user=%s)",
            conversation_id,
            project_id,
            user_id,
        )
        while not shutdown.is_set():
            # Wait for a final transcript from ASR
            try:
                asr_text = await asyncio.wait_for(asr_final_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            logger.info(
                "[Voice WS] ASR final text received, sending to agent: %.80s...",
                asr_text,
            )
            # Stream agent response
            full_response = ""
            tts_buffer = ""
            event_count = 0
            async for event in agent_service.stream_chat_v2(
                conversation_id=conversation_id,
                user_message=asr_text,
                project_id=project_id,
                user_id=user_id,
                tenant_id=tenant_id,
                image_attachments=None,
            ):
                event_type = event.get("type")
                event_count += 1
                if event_count <= 3 or event_count % 20 == 0:
                    logger.info(
                        "[Voice WS] Agent event #%d: type=%s",
                        event_count,
                        event_type,
                    )
                if event_type == "error":
                    error_msg = event.get("data", {}).get("message", "Unknown agent error")
                    logger.error("[Voice WS] Agent error: %s", error_msg)
                    await _send_json(websocket, {"type": "error", "message": error_msg})
                    break


                if event_type == "token":
                    token_text = event.get("data", {}).get("content", "")
                    if token_text:
                        full_response += token_text
                        tts_buffer += token_text

                        # Send token to browser
                        await _send_json(
                            websocket,
                            {"type": "agent_token", "content": token_text},
                        )

                        # Check if we should flush to TTS
                        tts_buffer = await _flush_tts_buffer(
                            tts_buffer, tts_text_queue, force=False
                        )

                elif event_type == "complete":
                    complete_content = event.get("data", {}).get("content", "")
                    if complete_content:
                        full_response = complete_content

                    await _send_json(
                        websocket,
                        {"type": "agent_complete", "content": full_response},
                    )
                    logger.info(
                        "[Voice WS] Agent complete: %d events, response_len=%d",
                        event_count,
                        len(full_response),
                    )

            # Flush remaining TTS buffer
            if tts_buffer.strip():
                await tts_text_queue.put(tts_buffer.strip())
                tts_buffer = ""

            # Signal TTS that this response is done
            await tts_text_queue.put(None)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("[Voice WS] Agent bridge error: %s", e, exc_info=True)
        await _send_error(websocket, f"Agent error: {e}")
    finally:
        # Ensure TTS sender can exit
        await tts_text_queue.put(None)


async def _tts_sender(
    websocket: WebSocket,
    tts_text_queue: asyncio.Queue[str | None],
    access_key: str,
    app_key: str,
    speaker: str,
    shutdown: asyncio.Event,
) -> None:
    """Synthesize text chunks via TTS and send audio back to browser."""
    try:
        while not shutdown.is_set():
            try:
                text = await asyncio.wait_for(tts_text_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if text is None:
                # End-of-response marker; skip
                continue

            if not text.strip():
                continue

            # Create a fresh TTS client for this synthesis
            from src.infrastructure.adapters.secondary.external.volcengine.tts_streaming_client import (
                AsyncTTSStreamingClient,
            )

            tts_client = AsyncTTSStreamingClient(access_key, app_key, speaker=speaker)

            try:
                await tts_client.connect()
                await _send_json(websocket, {"type": "tts_start"})

                async for audio_chunk in tts_client.synthesize(text):
                    if audio_chunk:
                        await websocket.send_bytes(audio_chunk)

                await _send_json(websocket, {"type": "tts_end"})
            except Exception as e:
                logger.error("[Voice WS] TTS synthesis error: %s", e, exc_info=True)
                await _send_error(websocket, f"TTS error: {e}")
            finally:
                try:
                    await tts_client.close()
                except Exception:
                    pass

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("[Voice WS] TTS sender error: %s", e, exc_info=True)


# =============================================================================
# Helper Functions
# =============================================================================


async def _flush_tts_buffer(
    buffer: str,
    tts_text_queue: asyncio.Queue[str | None],
    force: bool = False,
) -> str:
    """Split buffer at sentence boundaries and enqueue chunks for TTS.

    Returns the remaining (unflushed) portion of the buffer.
    """
    if not buffer:
        return ""

    # Force flush if buffer exceeds max size
    if force or len(buffer) >= _MAX_BUFFER_CHARS:
        # Try to split at a sentence boundary
        match = _SENTENCE_BOUNDARY.search(buffer)
        if match:
            split_pos = match.end()
            chunk = buffer[:split_pos].strip()
            if chunk:
                await tts_text_queue.put(chunk)
            return buffer[split_pos:]
        elif force or len(buffer) >= _MAX_BUFFER_CHARS:
            # No boundary found, flush everything
            chunk = buffer.strip()
            if chunk:
                await tts_text_queue.put(chunk)
            return ""
    else:
        # Check for sentence boundaries
        match = _SENTENCE_BOUNDARY.search(buffer)
        if match:
            split_pos = match.end()
            chunk = buffer[:split_pos].strip()
            if chunk:
                await tts_text_queue.put(chunk)
            return buffer[split_pos:]

    return buffer


async def _send_json(websocket: WebSocket, data: dict[str, Any]) -> None:
    """Send JSON control message as text frame. Silently ignores send errors."""
    try:
        await websocket.send_json(data)
    except Exception:
        pass


async def _send_error(websocket: WebSocket, message: str) -> None:
    """Send error JSON message to browser."""
    try:
        await websocket.send_json({"type": "error", "message": message})
    except Exception:
        pass
