"""Tests for test tools using TDD methodology.

TDD Cycle:
1. RED - Write failing test
2. GREEN - Implement minimal code to pass
3. REFACTOR - Improve while keeping tests passing
"""

import asyncio
import pytest

from src.tools.test_tools import (
    analyze_coverage,
    generate_tests,
    run_tests,
)


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
            # Should return some coverage info
            assert "file_path" in metadata

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
            # Should return coverage info
            assert "file_path" in metadata or "coverage" in metadata

    @pytest.mark.asyncio
    async def test_analyze_coverage_nonexistent_file(self):
        """Test analyzing coverage for nonexistent file."""
        result = await analyze_coverage(
            file_path="nonexistent.py",
            _workspace_dir=".",
        )

        assert result.get("isError") is True


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
