"""Text chunking with line tracking and overlap.

Ported from Moltbot's internal.ts chunkMarkdown() algorithm.
Character-based chunking with configurable overlap and SHA256 hashing.
"""

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    """A chunk of text with position and hash metadata."""

    text: str
    start_line: int
    end_line: int
    content_hash: str
    chunk_index: int


def _hash_text(text: str) -> str:
    """Compute SHA256 hex digest of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _split_line_into_segments(line: str, max_chars: int) -> list[str]:
    """Split a single line into segments that fit within max_chars."""
    if not line:
        return [""]
    return [line[start : start + max_chars] for start in range(0, len(line), max_chars)]


def chunk_text(
    content: str,
    max_tokens: int = 400,
    overlap_tokens: int = 80,
    chars_per_token: int = 4,
) -> list[TextChunk]:
    """Split text into overlapping chunks with line tracking.
    - Accumulate lines until max_chars is exceeded
    - Flush the chunk and carry overlap lines forward
    - Track line numbers for source attribution
    Args:
        content: Full text to chunk.
        max_tokens: Maximum tokens per chunk.
        overlap_tokens: Number of overlap tokens between chunks.
        chars_per_token: Character-to-token multiplier (default 4).
        List of TextChunk with text, line range, and content hash.
    """
    if not content or not content.strip():
        return []
    lines = content.split("\n")
    if not lines:
        return []
    max_chars = max(32, max_tokens * chars_per_token)
    overlap_chars = max(0, overlap_tokens * chars_per_token)
    current: list[tuple[str, int]] = []  # (line_text, line_number)
    current_chars = 0
    def flush() -> None:
        if not current:
            return
        text = "\n".join(line for line, _ in current)
        start_line = current[0][1]
        end_line = current[-1][1]
        chunks.append(
            TextChunk(
                text=text,
                start_line=start_line,
                end_line=end_line,
                content_hash=_hash_text(text),
                chunk_index=len(chunks),
            )
        )
    def carry_overlap() -> None:
        nonlocal current, current_chars
        if overlap_chars <= 0 or not current:
            current = []
            current_chars = 0
            return
        acc = 0
        kept: list[tuple[str, int]] = []
        for i in range(len(current) - 1, -1, -1):
            line_text, line_no = current[i]
            acc += len(line_text) + 1
            kept.insert(0, (line_text, line_no))
            if acc >= overlap_chars:
                break
        current = kept
        current_chars = sum(len(t) + 1 for t, _ in kept)
        line_no = i + 1
        segments = _split_line_into_segments(line, max_chars)
        for segment in segments:
            line_size = len(segment) + 1
            if current_chars + line_size > max_chars and current:
                flush()
                carry_overlap()
            current.append((segment, line_no))
            current_chars += line_size
    flush()
    return chunks
