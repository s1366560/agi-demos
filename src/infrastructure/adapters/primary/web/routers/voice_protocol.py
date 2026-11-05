"""Closed voice protocol modes and provider-issued utterance boundaries."""

from dataclasses import asdict
from typing import Any

from src.domain.model.audio_session import AudioMode, TranscriptSegment


def voice_mode(config: dict[str, Any]) -> AudioMode:
    """Legacy clients fail safe to transcription until they explicitly select voice."""
    return AudioMode(config.get("mode", "dictation"))


def transcript_events(
    response: dict[str, Any], stream_id: str, revision: int
) -> list[dict[str, Any]]:
    """Preserve provider timestamps/speaker scope; never infer end-of-turn from text."""
    result = response.get("payload_msg", {}).get("result", {})
    utterances = result.get("utterances")
    events: list[dict[str, Any]] = []
    if isinstance(utterances, list) and utterances:
        for ordinal, item in enumerate(utterances):
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                continue
            start, end = item.get("start_time"), item.get("end_time")
            if type(start) is not int or type(end) is not int or start < 0 or end < start:
                start = end = None
            speaker = item.get("speaker_id", item.get("additions", {}).get("speaker"))
            segment = TranscriptSegment(
                segment_id=f"{stream_id}:{start if start is not None else ordinal}",
                text=item["text"],
                final=item.get("definite") is True or response.get("is_last_package") is True,
                start_ms=start,
                end_ms=end,
                speaker_id=f"{stream_id}:{speaker}" if speaker is not None else None,
                stream_id=stream_id,
                revision=revision,
            )
            events.append(
                {"type": "asr_final" if segment.final else "asr_interim", **asdict(segment)}
            )
    elif isinstance(result.get("text"), str) and result["text"]:
        segment = TranscriptSegment(
            segment_id=f"{stream_id}:stream",
            text=result["text"],
            final=response.get("is_last_package") is True,
            stream_id=stream_id,
            revision=revision,
        )
        events.append({"type": "asr_final" if segment.final else "asr_interim", **asdict(segment)})
    return events
