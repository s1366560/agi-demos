"""
Unit tests for Tool Output Truncation module.

Tests the truncation capabilities for preventing excessive token usage
from large tool outputs, aligned with vendor/opencode implementation.
"""

import pytest

from src.infrastructure.agent.tools.truncation import (
    DEFAULT_READ_LIMIT,
    MAX_LINE_LENGTH,
    MAX_OUTPUT_BYTES,
    OutputTruncator,
    TruncationResult,
    format_file_output,
    truncate_by_bytes,
    truncate_lines_by_bytes,
    truncate_output,
)


@pytest.mark.unit
class TestConstants:
    """Test truncation constants."""

    def test_max_output_bytes(self):
        """Test MAX_OUTPUT_BYTES constant."""
        assert MAX_OUTPUT_BYTES == 50 * 1024  # 50KB

    def test_max_line_length(self):
        """Test MAX_LINE_LENGTH constant."""
        assert MAX_LINE_LENGTH == 2000

    def test_default_read_limit(self):
        """Test DEFAULT_READ_LIMIT constant."""
        assert DEFAULT_READ_LIMIT == 2000


@pytest.mark.unit
class TestTruncateByBytes:
    """Test byte-based truncation."""

    def test_empty_string(self):
        """Test truncating empty string."""
        result = truncate_by_bytes("")
        assert not result.truncated
        assert result.output == ""
        assert result.truncated_bytes is None

    def test_small_content(self):
        """Test content under limit."""
        content = "x" * 1000  # 1KB
        result = truncate_by_bytes(content, max_bytes=2000)
        assert not result.truncated
        assert result.output == content

    def test_exact_limit(self):
        """Test content exactly at limit."""
        content = "x" * 2000
        result = truncate_by_bytes(content, max_bytes=2000)
        assert not result.truncated
        assert result.output == content

    def test_over_limit(self):
        """Test content over limit."""
        content = "x" * 3000
        result = truncate_by_bytes(content, max_bytes=2000)
        assert result.truncated
        assert len(result.output) <= 2000
        assert result.truncated_bytes == 1000
        assert result.output == "x" * 2000

    def test_unicode_handling(self):
        """Test Unicode content truncation."""
        # Mixed ASCII and multi-byte characters
        content = "Hello世界" * 1000
        result = truncate_by_bytes(content, max_bytes=1000)
        assert result.truncated
        # Should not break UTF-8 encoding
        assert len(result.output.encode("utf-8")) <= 1000


@pytest.mark.unit
class TestTruncateLinesByBytes:
    """Test line-based truncation with byte limits."""

    def test_empty_lines(self):
        """Test empty line list."""
        result = truncate_lines_by_bytes([])
        assert not result.truncated
        assert result.output == ""
        assert result.total_lines == 0

    def test_small_output(self):
        """Test small output under all limits."""
        lines = ["line 1", "line 2", "line 3"]
        result = truncate_lines_by_bytes(lines)
        assert not result.truncated
        assert "1| line 1" in result.output
        assert "2| line 2" in result.output
        assert "3| line 3" in result.output
        assert "(End of file - total 3 lines)" in result.output

    def test_with_offset(self):
        """Test reading with offset."""
        lines = [f"line {i}" for i in range(100)]
        result = truncate_lines_by_bytes(lines, offset=10, limit=5)
        # has_more triggers truncated = True
        assert result.truncated  # Because has_more is True
        assert "11| line 10" in result.output
        assert "15| line 14" in result.output
        assert result.last_read_line == 15

    def test_with_limit(self):
        """Test reading with limit."""
        lines = [f"line {i}" for i in range(100)]
        result = truncate_lines_by_bytes(lines, offset=0, limit=10)
        # has_more triggers truncated = True
        assert result.truncated  # Because has_more is True
        assert result.last_read_line == 10
        # The message says "File has more lines" not "has_more"
        assert "more lines" in result.output.lower()

    def test_truncated_by_bytes(self):
        """Test truncation by byte limit."""
        # Create many long lines to exceed byte limit
        lines = ["x" * 1000 for _ in range(100)]
        result = truncate_lines_by_bytes(lines, max_bytes=5000)
        assert result.truncated
        assert result.truncated_bytes is not None
        # truncated_bytes stores bytes_count (used bytes), not removed bytes
        assert result.truncated_bytes <= 5000
        assert "truncated at 5000 bytes" in result.output.lower()

    def test_line_truncation(self):
        """Test individual line truncation."""
        long_line = "x" * (MAX_LINE_LENGTH + 1000)
        lines = [long_line, "short line"]
        result = truncate_lines_by_bytes(lines)
        assert "..." in result.output
        # Line format: "#####| " (7) + truncated (2000) + "..." (3) = 2010
        first_line = result.output.split("\n")[0]
        assert (
            len(first_line) == MAX_LINE_LENGTH + 10
        )  # "#####| " (7) + "..." (3) + "\n" (implicit)
        # Both lines are included because the first line (after truncation) fits in 50KB
        assert "short line" in result.output  # Second line IS included

    def test_end_of_file(self):
        """Test end of file message."""
        lines = ["line 1", "line 2", "line 3"]
        result = truncate_lines_by_bytes(lines, offset=0, limit=10)
        assert "End of file" in result.output
        assert result.total_lines == 3
        assert not result.has_more  # All lines read
        assert not result.truncated  # No truncation needed

    def test_metadata(self):
        """Test TruncationResult metadata."""
        lines = [f"line {i}" for i in range(100)]
        result = truncate_lines_by_bytes(lines, offset=0, limit=10)
        assert result.total_lines == 100
        assert result.last_read_line == 10
        assert result.has_more is True  # More lines available
        assert result.truncated is True  # Because has_more


@pytest.mark.unit
class TestTruncateOutput:
    """Test simple truncation function."""

    def test_no_truncation(self):
        """Test content under limit."""
        content = "small content"
        result = truncate_output(content)
        assert result == "small content"

    def test_with_truncation(self):
        """Test content over limit."""
        content = "x" * 6000
        result = truncate_output(content, max_bytes=2000)
        assert len(result) <= 2000 + 50  # Account for truncation message
        assert "truncated" in result.lower()

    def test_without_message(self):
        """Test truncation without message."""
        content = "x" * 3000
        result = truncate_output(content, max_bytes=2000, add_message=False)
        assert len(result) <= 2000
        assert "truncated" not in result.lower()


@pytest.mark.unit
class TestFormatFileOutput:
    """Test file output formatting."""

    def test_small_file(self):
        """Test small file output."""
        lines = ["line 1", "line 2", "line 3"]
        output = format_file_output(lines, "/path/to/file.txt")
        assert "<file>" in output
        assert "</file>" in output
        assert "1| line 1" in output
        assert "End of file" in output

    def test_large_file(self):
        """Test large file with truncation."""
        lines = [f"line {i}" * 100 for i in range(100)]
        output = format_file_output(lines, "/path/to/file.txt")
        assert "<file>" in output
        assert "</file>" in output
        assert "truncated" in output.lower() or "has more" in output.lower()


@pytest.mark.unit
class TestOutputTruncator:
    """Test OutputTruncator class."""

    def test_custom_limits(self):
        """Test truncator with custom limits."""
        truncator = OutputTruncator(max_bytes=1000, max_line_length=100)

        content = "x" * 2000
        result = truncator.truncate(content)

        assert result.truncated
        assert len(result.output) <= 1000

    def test_truncate_lines_with_custom_limit(self):
        """Test line truncation with custom limits."""
        truncator = OutputTruncator(max_bytes=5000, max_line_length=500)

        lines = ["x" * 1000 for _ in range(10)]
        result = truncator.truncate_lines(lines, offset=0, limit=5)

        assert result.last_read_line == 5
        # 5 lines + empty string from "\n" prefix + message = 7 elements when split
        assert len(result.output.split("\n")) <= 7

    def test_format_file_with_custom_limits(self):
        """Test file formatting with custom limits."""
        truncator = OutputTruncator(max_bytes=2000)

        lines = [f"line {i}" * 50 for i in range(100)]
        output = truncator.format_file(lines, "/path/to/file.txt", offset=0, limit=10)

        assert "<file>" in output
        assert "</file>" in output
        # Should truncate due to byte limit
        assert "truncated" in output.lower() or "has more" in output.lower()


@pytest.mark.unit
class TestTruncationResult:
    """Test TruncationResult dataclass."""

    def test_default_values(self):
        """Test default result values."""
        result = TruncationResult()
        assert not result.truncated
        assert result.output == ""
        assert result.truncated_bytes is None
        assert result.total_lines is None
        assert result.last_read_line is None
        assert not result.has_more

    def test_to_dict(self):
        """Test serialization to dict."""
        result = TruncationResult(
            truncated=True,
            output="test output",
            truncated_bytes=1000,
            truncated_lines=10,
            total_lines=100,
            last_read_line=50,
            has_more=True,
        )

        data = result.to_dict()
        assert data["truncated"] is True
        assert data["output"] == "test output"
        assert data["truncated_bytes"] == 1000
        assert data["total_lines"] == 100
        assert data["last_read_line"] == 50
        assert data["has_more"] is True


@pytest.mark.unit
class TestIntegrationWithAgentTool:
    """Test integration with AgentTool base class."""

    def test_tool_with_truncation(self):
        """Test that AgentTool truncate_output method works."""
        from src.infrastructure.agent.tools.base import AgentTool

        class TestTool(AgentTool):
            def __init__(self) -> None:
                super().__init__("test", "Test tool", max_output_bytes=100)

            async def execute(self, **kwargs):
                return "x" * 200

        tool = TestTool()
        result = tool.truncate_output("x" * 200)

        # Should truncate to 100 bytes
        assert len(result.encode("utf-8")) <= 100

    def test_tool_without_truncation(self):
        """Test that small outputs are not truncated."""
        from src.infrastructure.agent.tools.base import AgentTool

        class TestTool(AgentTool):
            def __init__(self) -> None:
                super().__init__("test", "Test tool")

            async def execute(self, **kwargs):
                return "small output"

        tool = TestTool()
        result = tool.truncate_output("small output")

        assert result == "small output"


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_string_with_limit(self):
        """Test empty string with custom limit."""
        result = truncate_by_bytes("", max_bytes=1000)
        assert not result.truncated
        assert result.output == ""

    def test_exactly_at_limit(self):
        """Test content exactly at byte limit."""
        # ASCII: 1 char = 1 byte
        content = "x" * 1000
        result = truncate_by_bytes(content, max_bytes=1000)
        assert not result.truncated
        assert result.output == content

    def test_one_byte_over(self):
        """Test content one byte over limit."""
        content = "x" * 1001
        result = truncate_by_bytes(content, max_bytes=1000)
        assert result.truncated
        assert result.truncated_bytes == 1
        assert len(result.output) == 1000

    def test_all_unicode(self):
        """Test all Unicode content."""
        # Emoji and multi-byte characters
        content = "😀" * 500  # Each emoji is 4 bytes
        result = truncate_by_bytes(content, max_bytes=1000)
        assert result.truncated
        # Should handle UTF-8 properly
        assert len(result.output.encode("utf-8")) <= 1000

    def test_mixed_content(self):
        """Test mixed ASCII and Unicode."""
        content = "Hello " + "世界" * 100
        result = truncate_by_bytes(content, max_bytes=500)
        assert result.truncated
        # Should be valid UTF-8
        result.output.encode("utf-8")  # Should not raise

    def test_lines_with_empty_strings(self):
        """Test lines containing empty strings."""
        lines = ["line 1", "", "line 2", "", ""]
        result = truncate_lines_by_bytes(lines)
        assert "1| line 1" in result.output
        assert "2| " in result.output  # Empty line
        assert "5| " in result.output

    def test_single_line_over_limit(self):
        """Test single line that exceeds byte limit."""
        long_line = "x" * 10000
        lines = [long_line]
        result = truncate_lines_by_bytes(lines, max_bytes=1000)
        assert result.truncated
        # Single line exceeds byte limit after line truncation to MAX_LINE_LENGTH
        # So it doesn't get processed at all (line is truncated to 2000+3=2003 bytes > 1000)
        assert result.last_read_line == 0  # No lines were successfully processed
        # Check truncation message is present
        assert "truncated" in result.output.lower()

    def test_offset_beyond_lines(self):
        """Test offset beyond available lines."""
        lines = ["line 1", "line 2", "line 3"]
        result = truncate_lines_by_bytes(lines, offset=10, limit=5)
        assert not result.truncated  # No lines read = no truncation
        assert result.last_read_line == 10  # Offset position
        assert result.total_lines == 3
        assert "1| " not in result.output  # No lines read
        assert "End of file" in result.output

    def test_limit_zero(self):
        """Test limit of zero."""
        lines = ["line 1", "line 2"]
        result = truncate_lines_by_bytes(lines, limit=0)
        # limit=0 is treated as "use default" due to `limit or DEFAULT_READ_LIMIT`
        # So all lines are processed
        assert not result.truncated  # All lines fit within limits
        assert result.last_read_line == 2  # All 2 lines were processed
        assert result.total_lines == 2
