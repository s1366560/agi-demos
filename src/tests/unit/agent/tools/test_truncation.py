"""Tests for OutputTruncator and related truncation functions."""

from pathlib import Path

import pytest

from src.infrastructure.agent.tools.truncation import (
    DEFAULT_READ_LIMIT,
    MAX_LINE_LENGTH,
    MAX_OUTPUT_BYTES,
    OutputTruncator,
    TruncateDirection,
    TruncationResult,
    format_file_output,
    truncate_by_bytes,
    truncate_lines_by_bytes,
    truncate_output,
)


@pytest.mark.unit
class TestTruncateDirection:
    """Tests for TruncateDirection enum."""

    def test_values(self) -> None:
        assert TruncateDirection.HEAD.value == "head"
        assert TruncateDirection.TAIL.value == "tail"


@pytest.mark.unit
class TestTruncationResult:
    """Tests for TruncationResult dataclass."""

    def test_defaults(self) -> None:
        result = TruncationResult()
        assert result.truncated is False
        assert result.output == ""
        assert result.truncated_bytes is None
        assert result.truncated_lines is None
        assert result.total_lines is None
        assert result.last_read_line is None
        assert result.has_more is False

    def test_to_dict(self) -> None:
        result = TruncationResult(
            truncated=True,
            output="hello",
            truncated_bytes=100,
            total_lines=50,
            last_read_line=20,
            has_more=True,
        )
        d = result.to_dict()
        assert d["truncated"] is True
        assert d["output"] == "hello"
        assert d["truncated_bytes"] == 100
        assert d["total_lines"] == 50
        assert d["has_more"] is True


@pytest.mark.unit
class TestTruncateByBytes:
    """Tests for truncate_by_bytes function."""

    def test_empty_content(self) -> None:
        result = truncate_by_bytes("")
        assert result.truncated is False
        assert result.output == ""

    def test_content_within_limit(self) -> None:
        result = truncate_by_bytes("hello", max_bytes=100)
        assert result.truncated is False
        assert result.output == "hello"

    def test_content_exceeds_limit(self) -> None:
        content = "a" * 200
        result = truncate_by_bytes(content, max_bytes=100)
        assert result.truncated is True
        assert len(result.output.encode("utf-8")) <= 100
        assert result.truncated_bytes == 100  # 200 - 100

    def test_multibyte_unicode_handling(self) -> None:
        # Each CJK char is 3 bytes in UTF-8
        content = "\u4e2d" * 10  # 30 bytes total
        result = truncate_by_bytes(content, max_bytes=15)
        assert result.truncated is True
        # Should handle incomplete multibyte gracefully
        assert len(result.output.encode("utf-8")) <= 15


@pytest.mark.unit
class TestTruncateLinesByBytes:
    """Tests for truncate_lines_by_bytes function."""

    def test_empty_lines(self) -> None:
        result = truncate_lines_by_bytes([])
        assert result.truncated is False
        assert result.total_lines == 0

    def test_within_limits(self) -> None:
        lines = ["line 1", "line 2", "line 3"]
        result = truncate_lines_by_bytes(lines, max_bytes=10000)
        assert result.truncated is False
        assert result.total_lines == 3
        assert "line 1" in result.output

    def test_line_truncation_by_length(self) -> None:
        long_line = "x" * 3000
        result = truncate_lines_by_bytes([long_line], max_line_length=100)
        assert "..." in result.output

    def test_offset(self) -> None:
        lines = ["a", "b", "c", "d"]
        result = truncate_lines_by_bytes(lines, offset=2, max_bytes=10000)
        assert "c" in result.output
        assert "d" in result.output
        # Lines before offset should not appear
        assert result.last_read_line == 4

    def test_limit(self) -> None:
        lines = ["a", "b", "c", "d", "e"]
        result = truncate_lines_by_bytes(lines, limit=2, max_bytes=10000)
        assert result.last_read_line == 2
        assert result.has_more is True

    def test_byte_limit_truncation(self) -> None:
        lines = ["a" * 100] * 100  # 100 lines of 100 chars each
        result = truncate_lines_by_bytes(lines, max_bytes=500)
        assert result.truncated is True
        assert "truncated" in result.output.lower() or "Output truncated" in result.output


@pytest.mark.unit
class TestTruncateOutput:
    """Tests for truncate_output convenience function."""

    def test_no_truncation(self) -> None:
        result = truncate_output("short", max_bytes=100)
        assert result == "short"

    def test_truncation_with_message(self) -> None:
        content = "a" * 200
        result = truncate_output(content, max_bytes=100, add_message=True)
        assert "truncated" in result.lower()

    def test_truncation_without_message(self) -> None:
        content = "a" * 200
        result = truncate_output(content, max_bytes=100, add_message=False)
        assert "truncated" not in result.lower()


@pytest.mark.unit
class TestFormatFileOutput:
    """Tests for format_file_output function."""

    def test_basic_formatting(self) -> None:
        lines = ["hello", "world"]
        result = format_file_output(lines, "/tmp/test.py")
        assert "<file>" in result
        assert "</file>" in result
        assert "hello" in result


@pytest.mark.unit
class TestOutputTruncator:
    """Tests for OutputTruncator class."""

    def test_init_defaults(self) -> None:
        t = OutputTruncator()
        assert t.max_bytes == MAX_OUTPUT_BYTES
        assert t.max_line_length == MAX_LINE_LENGTH
        assert t.max_lines == DEFAULT_READ_LIMIT

    def test_init_custom(self) -> None:
        t = OutputTruncator(max_bytes=1024, max_line_length=100, max_lines=50)
        assert t.max_bytes == 1024

    def test_truncate_delegates(self) -> None:
        t = OutputTruncator(max_bytes=10)
        result = t.truncate("a" * 20)
        assert result.truncated is True

    def test_truncate_lines_delegates(self) -> None:
        t = OutputTruncator(max_bytes=10000)
        result = t.truncate_lines(["a", "b", "c"])
        assert result.total_lines == 3

    def test_format_file_delegates(self) -> None:
        t = OutputTruncator()
        result = t.format_file(["line1"], "/tmp/f.py")
        assert "<file>" in result

    def test_truncate_to_result_no_truncation(self) -> None:
        t = OutputTruncator(max_bytes=1000)
        result = t.truncate_to_result("short output")
        assert result.output == "short output"
        assert result.was_truncated is False

    def test_truncate_to_result_empty(self) -> None:
        t = OutputTruncator()
        result = t.truncate_to_result("")
        assert result.output == ""

    def test_truncate_to_result_head_direction(self, tmp_path: Path) -> None:
        t = OutputTruncator(max_bytes=50, output_dir=tmp_path)
        content = "x" * 200
        result = t.truncate_to_result(content, direction=TruncateDirection.HEAD)

        assert result.was_truncated is True
        assert result.original_bytes == 200
        assert result.full_output_path is not None
        # Full output should be saved
        saved = Path(result.full_output_path).read_text()
        assert saved == content

    def test_truncate_to_result_tail_direction(self, tmp_path: Path) -> None:
        t = OutputTruncator(max_bytes=50, output_dir=tmp_path)
        content = "A" * 100 + "B" * 100
        result = t.truncate_to_result(content, direction=TruncateDirection.TAIL)

        assert result.was_truncated is True
        # TAIL keeps the end, so should contain B's
        assert "B" in result.output

    def test_truncate_to_result_with_tool_name(self, tmp_path: Path) -> None:
        t = OutputTruncator(max_bytes=50, output_dir=tmp_path)
        content = "x" * 200
        result = t.truncate_to_result(content, tool_name="bash")

        assert result.full_output_path is not None
        assert "bash" in result.full_output_path

    def test_cleanup_old_files(self, tmp_path: Path) -> None:
        # Create a file
        f = tmp_path / "old.txt"
        f.write_text("old")
        # Set mtime to 30 days ago
        import os

        old_time = f.stat().st_mtime - (30 * 86400)
        os.utime(f, (old_time, old_time))

        removed = OutputTruncator.cleanup_old_files(output_dir=tmp_path, max_age_days=7)
        assert removed == 1

    def test_cleanup_nonexistent_dir(self) -> None:
        removed = OutputTruncator.cleanup_old_files(output_dir=Path("/tmp/nonexistent_dir_xyz_123"))
        assert removed == 0
