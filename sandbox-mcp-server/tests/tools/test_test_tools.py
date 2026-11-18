"""Tests for test tools using TDD methodology.

TDD Cycle:
1. RED - Write failing test
2. GREEN - Implement minimal code to pass
3. REFACTOR - Improve while keeping tests passing
"""

import ast
import subprocess
from pathlib import Path

import pytest

from src.tools.test_tools import (
    _parse_coverage_json,
    analyze_coverage,
    generate_tests,
    run_tests,
)


def _result_text(result: dict) -> str:
    """Join tool text content for assertions."""
    chunks = []
    for item in result.get("content") or []:
        if isinstance(item, dict):
            chunks.append(item.get("text") or "")
    return "\n".join(chunks)



class TestGenerateTests:
    """Test suite for generate_tests tool."""

    @pytest.mark.asyncio
    async def test_generate_tests_for_function(self):
        """Test generating tests for a function."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "sample.py"
            test_file.write_text('''
def calculate_sum(a: int, b: int) -> int:
    """Calculate the sum of two numbers."""
    return a + b

def calculate_product(a: int, b: int) -> int:
    """Calculate the product of two numbers."""
    return a * b
''')

            result = await generate_tests(
                file_path=str(test_file),
                function_name="calculate_sum",
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            metadata = result.get("metadata", {})
            assert metadata.get("tests_generated") > 0

    @pytest.mark.asyncio
    async def test_generate_tests_for_class(self):
        """Test generating tests for a class."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "sample.py"
            test_file.write_text('''
class Calculator:
    """A simple calculator."""

    def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    def multiply(self, a: int, b: int) -> int:
        """Multiply two numbers."""
        return a * b
''')

            result = await generate_tests(
                file_path=str(test_file),
                class_name="Calculator",
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")

    @pytest.mark.asyncio
    async def test_generate_tests_nonexistent_file(self):
        """Test generating tests for nonexistent file."""
        result = await generate_tests(
            file_path="nonexistent.py",
            function_name="some_function",
            _workspace_dir=".",
        )

        assert result.get("isError") is True

    @pytest.mark.asyncio
    async def test_generate_tests_output_is_valid_python(self, tmp_path):
        """Generated tests should always be syntactically valid Python."""
        source_file = tmp_path / "calculator.py"
        source_file.write_text(
            """
def add(a: int, b: int) -> int:
    return a + b

async def fetch(name: str) -> str:
    return name
""".strip()
            + "\n",
            encoding="utf-8",
        )

        result = await generate_tests(
            file_path=str(source_file),
            _workspace_dir=str(tmp_path),
        )

        assert not result.get("isError")
        output_file = Path(result["metadata"]["output_file"])
        ast.parse(output_file.read_text(encoding="utf-8"))

    @pytest.mark.asyncio
    async def test_generate_tests_rejects_path_escape(self, tmp_path):
        """Test generation should not write files for sources outside the workspace."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "outside.py"
        outside.write_text("def escape() -> int:\n    return 1\n", encoding="utf-8")

        result = await generate_tests(
            file_path=str(outside.resolve()),
            _workspace_dir=str(workspace),
        )

        assert result.get("isError") is True
        assert result["metadata"]["error"]["code"] == "path_outside_workspace"


class TestRunTests:
    """Test suite for run_tests tool."""

    @pytest.mark.asyncio
    async def test_run_tests_success(self):
        """Test running tests with all passing."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a simple test file
            test_file = Path(tmpdir) / "test_sample.py"
            test_file.write_text('''
def test_addition():
    assert 1 + 1 == 2

def test_subtraction():
    assert 5 - 3 == 2
''')

            result = await run_tests(
                file_pattern="test_*.py",
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            metadata = result.get("metadata", {})
            assert metadata.get("total") >= 2

    @pytest.mark.asyncio
    async def test_run_tests_with_failures(self):
        """Test running tests with some failures."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_sample.py"
            test_file.write_text('''
def test_passing():
    assert True

def test_failing():
    assert False
''')

            result = await run_tests(
                file_pattern="test_*.py",
                _workspace_dir=tmpdir,
            )

            # Should not error, but should report failures
            assert not result.get("isError")
            metadata = result.get("metadata", {})
            assert metadata.get("failed") >= 1

    @pytest.mark.asyncio
    async def test_run_tests_no_tests_found(self):
        """Test running tests when no tests found."""
        result = await run_tests(
            file_pattern="nonexistent_*.py",
            _workspace_dir=".",
        )

        assert not result.get("isError")

    @pytest.mark.asyncio
    async def test_run_tests_no_tests_in_empty_workspace(self, tmp_path):
        """An empty workspace should report zero tests, not a tool error."""
        result = await run_tests(
            file_pattern="test_*.py",
            _workspace_dir=str(tmp_path),
        )

        assert not result.get("isError")
        assert result["metadata"]["total"] == 0
        assert result["metadata"]["passed"] == 0
        assert result["metadata"]["failed"] == 0
        assert "No test files found" in _result_text(result)

    @pytest.mark.asyncio
    async def test_run_tests_config_failure_is_error(self, tmp_path):
        """Invalid pytest configuration must be reported as a tool error."""
        (tmp_path / "pytest.ini").write_text(
            "[pytest]\naddopts = --not-a-real-pytest-option\n",
            encoding="utf-8",
        )
        (tmp_path / "test_sample.py").write_text(
            "def test_ok():\n    assert True\n",
            encoding="utf-8",
        )

        result = await run_tests(
            file_pattern="test_*.py",
            _workspace_dir=str(tmp_path),
        )

        assert result.get("isError") is True
        assert result["metadata"]["error"]["code"] == "tests_failed_to_run"
        text = _result_text(result)
        assert "Tests failed to run" in text
        assert "stderr:" in text
        assert "--not-a-real-pytest-option" in text or "--not-a-real-pytest-option" in (
            result["metadata"].get("stderr") or ""
        )

    @pytest.mark.asyncio
    async def test_run_tests_collection_error_is_error(self, tmp_path):
        """Collection/import failures must be errors and must keep stderr."""
        (tmp_path / "test_broken.py").write_text(
            "import module_that_does_not_exist_xyz123\n\n"
            "def test_ok():\n    assert True\n",
            encoding="utf-8",
        )

        result = await run_tests(
            file_pattern="test_*.py",
            _workspace_dir=str(tmp_path),
        )

        assert result.get("isError") is True
        assert result["metadata"]["error"]["code"] == "tests_failed_to_run"
        text = _result_text(result)
        assert "Tests failed to run" in text
        assert "module_that_does_not_exist_xyz123" in text

    @pytest.mark.asyncio
    async def test_run_tests_rejects_path_escape(self, tmp_path):
        """Escaped test directories should be rejected."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        result = await run_tests(
            test_path=str(outside.resolve()),
            _workspace_dir=str(workspace),
        )

        assert result.get("isError") is True
        assert result["metadata"]["error"]["code"] == "path_outside_workspace"


class TestAnalyzeCoverage:
    """Test suite for analyze_coverage tool."""

    @pytest.mark.asyncio
    async def test_analyze_coverage_with_covered_file(self):
        """Test analyzing coverage for a covered file."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "sample.py"
            test_file.write_text('''
def function_a():
    """Function A."""
    return 1

def function_b():
    """Function B."""
    return 2
''')

            result = await analyze_coverage(
                file_path=str(test_file),
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            metadata = result.get("metadata", {})
            assert "coverage_percent" in metadata
            assert isinstance(metadata["coverage_percent"], (int, float))
            assert "Coverage:" in _result_text(result)

    @pytest.mark.asyncio
    async def test_analyze_coverage_with_pytest(self):
        """Test analyzing coverage using pytest-cov."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a simple module and test
            module_file = Path(tmpdir) / "mymodule.py"
            module_file.write_text('''
def my_function():
    return 1

def another_function():
    return 2
''')

            test_file = Path(tmpdir) / "test_mymodule.py"
            test_file.write_text('''
from mymodule import my_function

def test_my_function():
    assert my_function() == 1
''')

            result = await analyze_coverage(
                file_path=str(module_file),
                use_pytest=True,
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            metadata = result.get("metadata", {})
            assert "coverage_percent" in metadata
            assert isinstance(metadata["coverage_percent"], (int, float))
            assert "Coverage:" in _result_text(result)

    @pytest.mark.asyncio
    async def test_analyze_coverage_nonexistent_file(self):
        """Test analyzing coverage for nonexistent file."""
        result = await analyze_coverage(
            file_path="nonexistent.py",
            _workspace_dir=".",
        )

        assert result.get("isError") is True

    @pytest.mark.asyncio
    async def test_analyze_coverage_does_not_leave_temp_test_file(self, tmp_path):
        """Coverage analysis should not leave helper tests in the source directory."""
        module_file = tmp_path / "mymodule.py"
        module_file.write_text(
            """
def my_function():
    return 1
""".strip()
            + "\n",
            encoding="utf-8",
        )

        result = await analyze_coverage(
            file_path=str(module_file),
            use_pytest=True,
            _workspace_dir=str(tmp_path),
        )

        assert not result.get("isError")
        assert not (tmp_path / "test_mymodule_coverage.py").exists()



    @pytest.mark.asyncio
    async def test_analyze_coverage_without_pytest_is_error(self, tmp_path):
        """Refusing pytest-cov must not invent a numeric estimate or succeed."""
        module_file = tmp_path / "mymodule.py"
        module_file.write_text("def my_function():\n    return 1\n", encoding="utf-8")

        result = await analyze_coverage(
            file_path=str(module_file),
            use_pytest=False,
            _workspace_dir=str(tmp_path),
        )

        assert result.get("isError") is True
        assert result["metadata"]["error"]["code"] == "coverage_unavailable"
        assert "coverage_percent" not in result["metadata"]
        assert "Basic coverage estimation" not in _result_text(result)

    @pytest.mark.asyncio
    async def test_analyze_coverage_missing_plugin_is_error(self, tmp_path, monkeypatch):
        """A missing pytest-cov plugin must surface as an error with stderr."""
        module_file = tmp_path / "mymodule.py"
        module_file.write_text("def my_function():\n    return 1\n", encoding="utf-8")
        (tmp_path / "test_mymodule.py").write_text(
            "from mymodule import my_function\n\ndef test_my_function():\n    assert my_function() == 1\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

        result = await analyze_coverage(
            file_path=str(module_file),
            use_pytest=True,
            _workspace_dir=str(tmp_path),
        )

        assert result.get("isError") is True
        assert result["metadata"]["error"]["code"] == "pytest_cov_missing"
        text = _result_text(result)
        assert "stderr:" in text or "unrecognized arguments" in text.lower()
        assert "--cov" in text or "--cov" in (result["metadata"].get("stderr") or "")
        assert "coverage_percent" not in result["metadata"]

    @pytest.mark.asyncio
    async def test_analyze_coverage_missing_report_is_error(self, tmp_path, monkeypatch):
        """Successful pytest without a coverage report must not be marked success."""
        module_file = tmp_path / "mymodule.py"
        module_file.write_text("def my_function():\n    return 1\n", encoding="utf-8")

        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout="collected 0 items", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = await analyze_coverage(
            file_path=str(module_file),
            use_pytest=True,
            _workspace_dir=str(tmp_path),
        )

        assert result.get("isError") is True
        assert result["metadata"]["error"]["code"] == "coverage_report_unavailable"
        assert "numeric results" in _result_text(result)
        assert "coverage_percent" not in result["metadata"]

    @pytest.mark.asyncio
    async def test_analyze_coverage_exception_is_error(self, tmp_path, monkeypatch):
        """Unexpected exceptions must be errors, not a fake coverage estimate."""
        module_file = tmp_path / "mymodule.py"
        module_file.write_text("def my_function():\n    return 1\n", encoding="utf-8")

        def boom(*args, **kwargs):
            raise RuntimeError("simulated coverage crash")

        monkeypatch.setattr(subprocess, "run", boom)

        result = await analyze_coverage(
            file_path=str(module_file),
            use_pytest=True,
            _workspace_dir=str(tmp_path),
        )

        assert result.get("isError") is True
        assert result["metadata"]["error"]["code"] == "coverage_analysis_failed"
        assert "simulated coverage crash" in _result_text(result)
        assert "Basic coverage estimation" not in _result_text(result)


class TestTestToolsIntegration:

    """Integration tests for test tools."""

    @pytest.mark.asyncio
    async def test_full_test_workflow(self):
        """Test complete workflow: generate -> run -> analyze."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create source file
            source_file = Path(tmpdir) / "mathlib.py"
            source_file.write_text('''
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

def subtract(a: int, b: int) -> int:
    """Subtract two numbers."""
    return a - b

def divide(a: int, b: int) -> float:
    """Divide two numbers."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
''')

            # Step 1: Generate tests
            gen_result = await generate_tests(
                file_path=str(source_file),
                _workspace_dir=tmpdir,
            )
            assert not gen_result.get("isError")

            # Step 2: Run tests (may have coverage info)
            run_result = await run_tests(
                file_pattern="test_*.py",
                _workspace_dir=tmpdir,
            )
            assert not run_result.get("isError")

            # Step 3: Analyze coverage
            cov_result = await analyze_coverage(
                file_path=str(source_file),
                _workspace_dir=tmpdir,
            )
            assert not cov_result.get("isError")



def test_parse_coverage_json_accepts_relative_report_paths(tmp_path):
    """pytest-cov may record relative paths; resolve them against the import root."""
    source = tmp_path / "mymodule.py"
    source.write_text("def f():\n    return 1\n", encoding="utf-8")
    report = tmp_path / "coverage.json"
    report.write_text(
        '''{"files": {"mymodule.py": {"summary": {"percent_covered": 75.0}, "missing_lines": [5], "executed_lines": [1, 2, 3]}}}''',
        encoding="utf-8",
    )

    parsed = _parse_coverage_json(report, source, roots=[tmp_path])

    assert parsed is not None
    assert parsed["coverage_percent"] == 75.0
    assert parsed["missing_lines"] == [5]
