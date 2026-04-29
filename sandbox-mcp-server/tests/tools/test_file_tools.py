"""Regression tests for file tools."""

import pytest

from src.tools.file_tools import (
    batch_read,
    get_path_error_result,
    glob_files,
    grep_files,
    read_file,
)
from src.tools.registry import get_tool_registry


class TestGrepTool:
    """Test suite for grep tool regressions."""

    @pytest.mark.asyncio
    async def test_grep_files_includes_context_lines(self, tmp_path, monkeypatch):
        """Context lines should be included around a match."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        test_file = workspace / "sample.txt"
        test_file.write_text("before\nmatch here\nafter\n", encoding="utf-8")

        monkeypatch.setattr("src.tools.file_tools._EXTRA_ALLOWED_PATHS", [])

        result = await grep_files(
            pattern="match",
            context_lines=1,
            _workspace_dir=str(workspace),
        )

        assert not result.get("isError")
        text = result["content"][0]["text"]
        assert "before" in text
        assert "match here" in text
        assert "after" in text

    @pytest.mark.asyncio
    async def test_grep_files_supports_allowed_paths_outside_workspace(
        self, tmp_path, monkeypatch
    ):
        """Searching an allowlisted path outside the workspace should not crash."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        (allowed / "outside.txt").write_text("needle\n", encoding="utf-8")

        monkeypatch.setattr(
            "src.tools.file_tools._EXTRA_ALLOWED_PATHS",
            [allowed.resolve()],
        )

        result = await grep_files(
            pattern="needle",
            path=str(allowed),
            _workspace_dir=str(workspace),
        )

        assert not result.get("isError")
        assert "outside.txt:1: needle" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_grep_files_skips_default_heavy_directories(self, tmp_path, monkeypatch):
        """Default grep scans should not traverse dependency caches."""
        workspace = tmp_path / "workspace"
        src = workspace / "src"
        dependency = workspace / "node_modules" / "pkg"
        src.mkdir(parents=True)
        dependency.mkdir(parents=True)
        (src / "app.ts").write_text("needle from source\n", encoding="utf-8")
        (dependency / "index.ts").write_text("needle from dependency\n", encoding="utf-8")

        monkeypatch.setattr("src.tools.file_tools._EXTRA_ALLOWED_PATHS", [])

        result = await grep_files(
            pattern="needle",
            glob_pattern="**/*.ts",
            _workspace_dir=str(workspace),
        )

        assert not result.get("isError")
        text = result["content"][0]["text"]
        assert "src/app.ts:1: needle from source" in text
        assert "node_modules" not in text
        assert result["metadata"]["skipped_dirs"] >= 1


class TestReadTool:
    """Regression coverage for read-oriented file helpers."""

    @pytest.mark.asyncio
    async def test_read_file_returns_structured_missing_file_error(self, tmp_path):
        """Missing-file responses should include structured hints and suggestions."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "sample.py").write_text("print('ok')\n", encoding="utf-8")

        result = await read_file(
            file_path="sampl.py",
            _workspace_dir=str(workspace),
        )

        assert result.get("isError") is True
        metadata = result.get("metadata", {})
        error = metadata.get("error", {})
        assert error.get("code") == "file_not_found"
        assert "glob" in (error.get("hint") or "").lower()
        suggestions = error.get("suggestions") or []
        assert any("sample.py" in suggestion for suggestion in suggestions)

    @pytest.mark.asyncio
    async def test_read_file_supports_tilde_expansion(self, tmp_path, monkeypatch):
        """Tilde paths should be expanded before workspace resolution."""
        fake_home = tmp_path / "home"
        workspace = fake_home / "workspace"
        workspace.mkdir(parents=True)
        sample = workspace / "sample.txt"
        sample.write_text("hello\nworld\n", encoding="utf-8")

        monkeypatch.setenv("HOME", str(fake_home))

        result = await read_file(
            file_path="~/workspace/sample.txt",
            _workspace_dir=str(workspace),
        )

        assert not result.get("isError")
        assert "hello" in result["content"][0]["text"]
        assert result["metadata"]["resolved_path"] == str(sample.resolve())

    @pytest.mark.asyncio
    async def test_read_file_offset_is_line_based(self, tmp_path):
        """Offset should skip whole lines, not raw bytes."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        sample = workspace / "multibyte.txt"
        sample.write_text("第一行\nsecond line\nthird line\n", encoding="utf-8")

        result = await read_file(
            file_path="multibyte.txt",
            offset=1,
            limit=1,
            _workspace_dir=str(workspace),
        )

        assert not result.get("isError")
        text = result["content"][0]["text"]
        assert "second line" in text
        assert "第一行" not in text
        assert result["metadata"]["offset"] == 1
        assert result["metadata"]["offset_unit"] == "lines"


class TestGlobTool:
    """Regression tests for glob path normalization."""

    @pytest.mark.asyncio
    async def test_glob_supports_tilde_expansion(self, tmp_path, monkeypatch):
        """Glob should expand tilde-based patterns and search roots."""
        fake_home = tmp_path / "home"
        workspace = fake_home / "workspace"
        src_dir = workspace / "src"
        src_dir.mkdir(parents=True)
        sample = src_dir / "demo.py"
        sample.write_text("print('demo')\n", encoding="utf-8")

        monkeypatch.setenv("HOME", str(fake_home))

        result = await glob_files(
            pattern="~/workspace/src/*.py",
            _workspace_dir=str(workspace),
        )

        assert not result.get("isError")
        assert "src/demo.py" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_glob_skips_default_heavy_directories(self, tmp_path, monkeypatch):
        """Recursive glob should prune large dependency directories by default."""
        workspace = tmp_path / "workspace"
        src = workspace / "src"
        dependency = workspace / "node_modules" / "pkg"
        src.mkdir(parents=True)
        dependency.mkdir(parents=True)
        (src / "app.tsx").write_text("export default function App() {}\n", encoding="utf-8")
        (dependency / "index.tsx").write_text("export const dep = true;\n", encoding="utf-8")

        monkeypatch.setattr("src.tools.file_tools._EXTRA_ALLOWED_PATHS", [])

        result = await glob_files(
            pattern="**/*.tsx",
            _workspace_dir=str(workspace),
        )

        assert not result.get("isError")
        text = result["content"][0]["text"]
        assert "src/app.tsx" in text
        assert "node_modules" not in text
        assert result["metadata"]["skipped_dirs"] >= 1


class TestBatchReadTool:
    """Regression tests for batch file reads."""

    @pytest.mark.asyncio
    async def test_batch_read_collects_results_and_errors(self, tmp_path):
        """Batch reads should preserve both successes and per-file failures."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        first = workspace / "one.txt"
        second = workspace / "two.txt"
        first.write_text("one\n", encoding="utf-8")
        second.write_text("two\n", encoding="utf-8")

        result = await batch_read(
            file_paths=["one.txt", "missing.txt", "two.txt"],
            _workspace_dir=str(workspace),
        )

        assert result.get("isError") is False
        assert result["metadata"]["successful"] == 2
        assert result["metadata"]["failed"] == 1
        assert len(result["results"]) == 2
        assert len(result["errors"]) == 1
        assert result["errors"][0]["error"]["code"] == "file_not_found"
        assert "one" in result["results"][0]["content"]


class TestErrorHelpers:
    """Focused tests for reusable error payload helpers."""

    def test_path_error_helper_includes_structured_metadata(self):
        """Shared error helpers should produce machine-readable metadata."""
        result = get_path_error_result(
            message="Path '/tmp/outside.py' is outside workspace directory",
            code="path_outside_workspace",
            hint="Use a path inside the workspace.",
            suggestions=["sandbox-mcp-server/src/tools/file_tools.py"],
        )

        assert result["isError"] is True
        error = result["metadata"]["error"]
        assert error["code"] == "path_outside_workspace"
        assert error["suggestions"] == ["sandbox-mcp-server/src/tools/file_tools.py"]


class TestToolRegistry:
    """Regression tests for file-tool registration."""

    def test_batch_read_is_registered(self):
        """The registry should expose the new batch_read tool."""
        registry = get_tool_registry()

        assert "batch_read" in registry.list_names()
