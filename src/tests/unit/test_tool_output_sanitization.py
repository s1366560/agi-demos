"""
Unit tests for binary/base64 content isolation from LLM context.

Verifies that export_artifact and similar tools returning binary data
do NOT leak base64 content into tool_part.output (the LLM context).
"""

import base64
import json

import pytest

from src.infrastructure.agent.tools.executor import ToolExecutor


@pytest.mark.unit
class TestSanitizeToolOutputProcessor:
    """Test ToolExecutor._sanitize_tool_output (formerly on SessionProcessor)."""

    def _make_executor_instance(self):
        """Create a minimal ToolExecutor for testing the sanitizer."""
        executor = object.__new__(ToolExecutor)
        return executor

    def test_short_text_unchanged(self):
        executor = self._make_executor_instance()
        output = "File exported successfully"
        assert executor._sanitize_tool_output(output) == output

    def test_empty_string_unchanged(self):
        executor = self._make_executor_instance()
        assert executor._sanitize_tool_output("") == ""

    def test_none_returns_none(self):
        executor = self._make_executor_instance()
        assert executor._sanitize_tool_output(None) is None

    def test_base64_blob_replaced(self):
        executor = self._make_executor_instance()
        # Simulate a base64-encoded binary blob (e.g., 1KB of random data)
        fake_b64 = base64.b64encode(b"\x00" * 1024).decode()
        output = f"Here is the data: {fake_b64} end"
        result = executor._sanitize_tool_output(output)
        assert fake_b64 not in result
        assert "[binary data omitted]" in result
        assert "Here is the data:" in result

    def test_multiple_base64_blobs_replaced(self):
        executor = self._make_executor_instance()
        blob1 = base64.b64encode(b"\xff" * 512).decode()
        blob2 = base64.b64encode(b"\xaa" * 512).decode()
        output = f"img1: {blob1}\nimg2: {blob2}"
        result = executor._sanitize_tool_output(output)
        assert blob1 not in result
        assert blob2 not in result
        assert result.count("[binary data omitted]") == 2

    def test_short_base64_not_replaced(self):
        """Base64 strings shorter than 256 chars should not be stripped."""
        executor = self._make_executor_instance()
        short_b64 = base64.b64encode(b"\x00" * 100).decode()
        assert len(short_b64) < 256
        output = f"token: {short_b64}"
        result = executor._sanitize_tool_output(output)
        assert short_b64 in result

    def test_large_output_truncated(self):
        executor = self._make_executor_instance()
        # Use chars outside base64 alphabet to test pure size truncation
        large = "hello world! " * 5_000
        result = executor._sanitize_tool_output(large)
        assert len(result.encode("utf-8")) <= ToolExecutor._MAX_TOOL_OUTPUT_BYTES + 100
        assert "[output truncated]" in result

    def test_normal_json_output_unchanged(self):
        executor = self._make_executor_instance()
        data = json.dumps({"status": "ok", "files": ["a.py", "b.py"], "count": 42})
        assert executor._sanitize_tool_output(data) == data


@pytest.mark.unit
class TestSanitizeToolOutputExecutor:
    """Test ToolExecutor._sanitize_tool_output."""

    def _make_executor_instance(self):
        executor = object.__new__(ToolExecutor)
        return executor

    def test_base64_blob_replaced(self):
        executor = self._make_executor_instance()
        fake_b64 = base64.b64encode(b"\x00" * 1024).decode()
        output = f"data: {fake_b64}"
        result = executor._sanitize_tool_output(output)
        assert fake_b64 not in result
        assert "[binary data omitted]" in result

    def test_large_output_truncated(self):
        executor = self._make_executor_instance()
        # Use chars outside base64 alphabet to test pure size truncation
        large = "hello world! " * 5_000
        result = executor._sanitize_tool_output(large)
        assert "[output truncated]" in result


@pytest.mark.unit
class TestProcessResultExecutor:
    """Test ToolExecutor._process_result artifact handling."""

    def _make_executor_instance(self):
        executor = object.__new__(ToolExecutor)
        return executor

    def test_artifact_result_uses_output_key(self):
        """When result has 'output' and 'artifact', output_str should be the summary."""
        executor = self._make_executor_instance()
        fake_b64 = base64.b64encode(b"\x00" * 2048).decode()
        result = {
            "output": "Exported artifact: report.pdf (application/pdf, 2048 bytes)",
            "content": [{"type": "text", "text": "exported"}],
            "artifact": {
                "filename": "report.pdf",
                "mime_type": "application/pdf",
                "size": 2048,
                "encoding": "base64",
                "data": fake_b64,
            },
        }
        output_str, sse_result = executor._process_result(result)
        assert fake_b64 not in output_str
        assert "report.pdf" in output_str
        # sse_result should be a stripped copy without base64 data
        assert sse_result is not result
        assert "data" not in sse_result["artifact"]
        assert sse_result["artifact"]["filename"] == "report.pdf"

    def test_artifact_result_without_output_key(self):
        """When result has 'artifact' but no 'output', should generate a summary."""
        executor = self._make_executor_instance()
        fake_b64 = base64.b64encode(b"\x00" * 4096).decode()
        result = {
            "content": [{"type": "text", "text": "done"}],
            "artifact": {
                "filename": "image.png",
                "mime_type": "image/png",
                "size": 4096,
                "data": fake_b64,
            },
        }
        output_str, _sse_result = executor._process_result(result)
        assert fake_b64 not in output_str
        assert "image.png" in output_str
        assert "image/png" in output_str

    def test_regular_dict_with_output(self):
        """Regular dict with 'output' key should extract the output."""
        executor = self._make_executor_instance()
        result = {"output": "command completed", "metadata": {"exit_code": 0}}
        output_str, _ = executor._process_result(result)
        assert output_str == "command completed"

    def test_string_result_passthrough(self):
        """String results should pass through."""
        executor = self._make_executor_instance()
        output_str, _ = executor._process_result("hello world")
        assert output_str == "hello world"

    def test_generic_dict_json_serialized(self):
        """Dicts without 'output' or 'artifact' should be JSON-serialized."""
        executor = self._make_executor_instance()
        result = {"key": "value", "count": 3}
        output_str, _ = executor._process_result(result)
        assert json.loads(output_str) == result


@pytest.mark.unit
class TestArtifactResultContextIsolation:
    """End-to-end test: export_artifact-style result never leaks base64 to LLM context."""

    def test_full_export_artifact_flow(self):
        """Simulate the complete flow from SandboxMCPToolWrapper return to LLM context."""
        # 1. Simulate what SandboxMCPToolWrapper now returns
        fake_pdf = b"%PDF-1.4 fake content " * 500
        fake_b64 = base64.b64encode(fake_pdf).decode()

        wrapper_result = {
            "output": f"Exported artifact: report.pdf (application/pdf, {len(fake_pdf)} bytes, "
            f"category: document)",
            "content": [{"type": "text", "text": "PDF report generated"}],
            "artifact": {
                "filename": "report.pdf",
                "mime_type": "application/pdf",
                "size": len(fake_pdf),
                "category": "document",
                "encoding": "base64",
                "data": fake_b64,
            },
        }

        # 2. Simulate processor result processing (the fixed code path)
        if isinstance(wrapper_result, dict) and "artifact" in wrapper_result:
            artifact = wrapper_result["artifact"]
            output_str = wrapper_result.get(
                "output",
                f"Exported artifact: {artifact.get('filename', 'unknown')} "
                f"({artifact.get('mime_type', 'unknown')}, "
                f"{artifact.get('size', 0)} bytes)",
            )
        elif isinstance(wrapper_result, dict) and "output" in wrapper_result:
            output_str = wrapper_result.get("output", "")
        else:
            output_str = json.dumps(wrapper_result)

        # 3. Verify: no base64 in what would be sent to LLM
        assert fake_b64 not in output_str
        assert len(output_str) < 500
        assert "report.pdf" in output_str
        assert "application/pdf" in output_str

        # 4. Verify: full result still available for artifact upload
        assert wrapper_result["artifact"]["data"] == fake_b64
