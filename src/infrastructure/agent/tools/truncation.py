"""Tool Output Truncation Module.

Provides output truncation capabilities for agent tools to prevent
excessive token usage from large tool outputs.

Aligned with vendor/opencode's truncation strategy:
- MAX_OUTPUT_BYTES: Maximum output size (50KB)
- MAX_LINE_LENGTH: Maximum characters per line (2000)
- Truncation metadata markers
- User guidance for continued reading

Reference: vendor/opencode/packages/opencode/src/tool/read.ts
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

# Truncation thresholds (aligned with vendor/opencode)
MAX_OUTPUT_BYTES = 50 * 1024  # 50KB max output size
MAX_LINE_LENGTH = 2000  # Max characters per line
DEFAULT_READ_LIMIT = 2000  # Default lines to read


@dataclass
class TruncationResult:
    """Result of truncating tool output."""

    truncated: bool = False
    output: str = ""
    truncated_bytes: Optional[int] = None
    truncated_lines: Optional[int] = None
    total_lines: Optional[int] = None
    last_read_line: Optional[int] = None
    has_more: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "truncated": self.truncated,
            "output": self.output,
            "truncated_bytes": self.truncated_bytes,
            "truncated_lines": self.truncated_lines,
            "total_lines": self.total_lines,
            "last_read_line": self.last_read_line,
            "has_more": self.has_more,
        }


def truncate_by_bytes(
    content: str,
    max_bytes: int = MAX_OUTPUT_BYTES,
) -> TruncationResult:
    """
    Truncate content by byte size.

    Args:
        content: Content to truncate
        max_bytes: Maximum byte size (default: 50KB)

    Returns:
        TruncationResult with truncated output
    """
    if not content:
        return TruncationResult(truncated=False, output="")

    # Encode to bytes and truncate if needed
    content_bytes = content.encode("utf-8")

    if len(content_bytes) <= max_bytes:
        return TruncationResult(truncated=False, output=content)

    # Truncate at byte boundary
    truncated_bytes = content_bytes[:max_bytes]

    # Decode back to string, handling incomplete UTF-8 sequences
    try:
        truncated_content = truncated_bytes.decode("utf-8")
    except UnicodeDecodeError:
        # Handle incomplete UTF-8 sequence by removing continuation bytes
        truncated_content = truncated_bytes.decode("utf-8", errors="ignore")

    return TruncationResult(
        truncated=True,
        output=truncated_content,
        truncated_bytes=len(content_bytes) - max_bytes,
    )


def truncate_lines_by_bytes(
    lines: List[str],
    offset: int = 0,
    limit: Optional[int] = None,
    max_bytes: int = MAX_OUTPUT_BYTES,
    max_line_length: int = MAX_LINE_LENGTH,
) -> TruncationResult:
    """
    Truncate lines by byte and line count limits.

    Aligned with vendor/opencode's read tool logic.

    Args:
        lines: List of lines to truncate
        offset: Starting line index (0-based)
        limit: Maximum number of lines to read
        max_bytes: Maximum byte size
        max_line_length: Maximum characters per line

    Returns:
        TruncationResult with truncated output and metadata
    """
    if not lines:
        return TruncationResult(truncated=False, output="", total_lines=0)

    limit = limit or DEFAULT_READ_LIMIT
    total_lines = len(lines)

    # Process lines with truncation
    processed_lines: List[str] = []
    bytes_count = 0
    truncated_by_bytes = False

    for i in range(offset, min(len(lines), offset + limit)):
        line = lines[i]

        # Truncate long lines
        if len(line) > max_line_length:
            line = line[:max_line_length] + "..."

        # Calculate size (including newline)
        line_size = len(line.encode("utf-8")) + (1 if processed_lines else 0)

        # Check byte limit
        if bytes_count + line_size > max_bytes:
            truncated_by_bytes = True
            break

        processed_lines.append(line)
        bytes_count += line_size

    last_read_line = offset + len(processed_lines)
    has_more_lines = total_lines > last_read_line
    truncated = has_more_lines or truncated_by_bytes

    # Build output with truncation message
    output_lines = [f"{i + offset + 1:5d}| {line}" for i, line in enumerate(processed_lines)]

    if truncated_by_bytes:
        output_lines.append(
            f"\n(Output truncated at {max_bytes} bytes. "
            f"Use 'offset' parameter to read beyond line {last_read_line})"
        )
    elif has_more_lines:
        output_lines.append(
            f"\n(File has more lines. Use 'offset' parameter to read beyond line {last_read_line})"
        )
    else:
        output_lines.append(f"\n(End of file - total {total_lines} lines)")

    output = "\n".join(output_lines)

    return TruncationResult(
        truncated=truncated,
        output=output,
        truncated_bytes=bytes_count if truncated_by_bytes else None,
        truncated_lines=len(processed_lines) if truncated else None,
        total_lines=total_lines,
        last_read_line=last_read_line,
        has_more=has_more_lines,
    )


def truncate_output(
    content: str,
    max_bytes: int = MAX_OUTPUT_BYTES,
    add_message: bool = True,
) -> str:
    """
    Simple truncation of content by byte size.

    Args:
        content: Content to truncate
        max_bytes: Maximum byte size
        add_message: Whether to add truncation message

    Returns:
        Truncated content with optional message
    """
    result = truncate_by_bytes(content, max_bytes)

    if not result.truncated:
        return content

    output = result.output

    if add_message:
        truncated_msg = f"\n\n(Output truncated at {max_bytes} bytes)"
        output += truncated_msg

    return output


def format_file_output(
    lines: List[str],
    file_path: str,
    offset: int = 0,
    limit: Optional[int] = None,
    max_bytes: int = MAX_OUTPUT_BYTES,
) -> str:
    """
    Format file output with truncation and line numbers.

    Aligned with vendor/opencode's read tool format.

    Args:
        lines: List of file lines
        file_path: File path for display
        offset: Starting line index
        limit: Maximum lines to read
        max_bytes: Maximum byte size

    Returns:
        Formatted and truncated output
    """
    result = truncate_lines_by_bytes(lines, offset, limit, max_bytes)

    # Wrap in <file> tags (aligned with vendor/opencode)
    output = f"<file>\n{result.output}\n</file>"

    return output


class OutputTruncator:
    """
    Utility class for truncating tool outputs.

    Provides methods for various truncation scenarios:
    - Simple text truncation
    - Line-based truncation with byte limits
    - File output formatting
    """

    def __init__(
        self,
        max_bytes: int = MAX_OUTPUT_BYTES,
        max_line_length: int = MAX_LINE_LENGTH,
    ):
        """
        Initialize output truncator.

        Args:
            max_bytes: Maximum output size in bytes
            max_line_length: Maximum characters per line
        """
        self.max_bytes = max_bytes
        self.max_line_length = max_line_length

    def truncate(self, content: str) -> TruncationResult:
        """Truncate content by byte size."""
        return truncate_by_bytes(content, self.max_bytes)

    def truncate_lines(
        self,
        lines: List[str],
        offset: int = 0,
        limit: Optional[int] = None,
    ) -> TruncationResult:
        """Truncate lines by byte and line count limits."""
        return truncate_lines_by_bytes(
            lines,
            offset,
            limit,
            self.max_bytes,
            self.max_line_length,
        )

    def format_file(
        self,
        lines: List[str],
        file_path: str,
        offset: int = 0,
        limit: Optional[int] = None,
    ) -> str:
        """Format file output with truncation."""
        return format_file_output(
            lines,
            file_path,
            offset,
            limit,
            self.max_bytes,
        )


# Convenience exports
__all__ = [
    "MAX_OUTPUT_BYTES",
    "MAX_LINE_LENGTH",
    "DEFAULT_READ_LIMIT",
    "TruncationResult",
    "truncate_by_bytes",
    "truncate_lines_by_bytes",
    "truncate_output",
    "format_file_output",
    "OutputTruncator",
]
