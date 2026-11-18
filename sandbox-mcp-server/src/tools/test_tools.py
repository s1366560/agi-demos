"""Test tools for MCP server.

Provides test generation, execution, and coverage analysis capabilities.
"""

import ast
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.server.websocket_server import MCPTool
from src.tools.file_tools import _error_result, _path_metadata, _resolve_path, _success_result

logger = logging.getLogger(__name__)

# Keep enough pytest output for diagnosis without unbounded payloads.
_PYTEST_OUTPUT_LIMIT = 8000


def _clip_text(text: str, *, limit: int = _PYTEST_OUTPUT_LIMIT) -> str:
    """Return text trimmed to a diagnostic budget."""
    text = text or ""
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n... [{omitted} more characters omitted]"


def _format_pytest_streams(stdout: str, stderr: str) -> str:
    """Render captured pytest streams without dropping stderr."""
    parts: list[str] = []
    stdout = _clip_text((stdout or "").rstrip())
    stderr = _clip_text((stderr or "").rstrip())
    if stdout:
        parts.extend(["stdout:", stdout])
    if stderr:
        parts.extend(["stderr:", stderr])
    return "\n".join(parts)


def _pytest_stream_metadata(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Expose clipped pytest streams in tool metadata."""
    return {
        "stdout": _clip_text(result.stdout or ""),
        "stderr": _clip_text(result.stderr or ""),
        "returncode": result.returncode,
    }


def _coverage_plugin_missing(stdout: str, stderr: str) -> bool:
    """Detect a missing or unloadable pytest-cov plugin from pytest output."""
    combined = f"{stdout or ''}\n{stderr or ''}".lower()
    if "no module named pytest_cov" in combined or "no module named 'pytest_cov'" in combined:
        return True
    if "pytest-cov" in combined and any(
        token in combined
        for token in (
            "not found",
            "not installed",
            "could not load",
            "import error",
            "importerror",
        )
    ):
        return True
    if "--cov" in combined and (
        "unrecognized arguments" in combined or "unrecognised arguments" in combined
    ):
        return True
    return False



def _module_import_data(source_path: Path, workspace_dir: str) -> tuple[str, Path]:
    """Return an importable module name plus the sys.path root to prepend.

    When both ``pkg`` and ``src/pkg`` exist, a file under ``src/pkg`` imports
    from ``src`` so its origin is that file. The other directory is left in place.
    """
    workspace = Path(workspace_dir).resolve()
    source = source_path.resolve()

    try:
        relative = source.relative_to(workspace)
        module_parts = list(relative.with_suffix("").parts)
        import_root = workspace
    except ValueError:
        module_parts = [source.stem]
        import_root = source.parent

    if module_parts and module_parts[-1] == "__init__":
        module_parts = module_parts[:-1]

    if (
        len(module_parts) >= 3
        and module_parts[0] == "src"
        and (workspace / module_parts[1]).is_dir()
        and (workspace / "src" / module_parts[1]).is_dir()
    ):
        import_root = workspace / "src"
        module_parts = module_parts[1:]

    if not module_parts or not all(part.isidentifier() for part in module_parts):
        module_parts = [source.stem]
        import_root = source.parent

    module_name = ".".join(module_parts)
    return module_name, import_root


def module_origin_for(module_name: str, import_root: Path) -> Path:
    """Return the file a module name resolves to under one import root."""
    return import_root.joinpath(*module_name.split(".")).with_suffix(".py")


def _sample_argument_value(
    arg: ast.arg,
    *,
    default: str | None = None,
) -> str:
    """Return a syntactically valid placeholder value for a parameter."""
    if default is not None:
        return default

    annotation = ast.unparse(arg.annotation).lower() if arg.annotation else ""
    if "bool" in annotation:
        return "True"
    if "float" in annotation:
        return "1.0"
    if "int" in annotation:
        return "1"
    if "str" in annotation:
        return "'value'"
    if "bytes" in annotation:
        return "b'value'"
    if "dict" in annotation:
        return "{}"
    if "list" in annotation:
        return "[]"
    if "tuple" in annotation:
        return "()"
    if "set" in annotation:
        return "set()"
    return "None"


def _build_call_arguments(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    """Build sample invocation arguments for a function signature."""
    args = node.args.args
    defaults = node.args.defaults
    offset = len(args) - len(defaults)
    call_args: list[str] = []

    for index, arg in enumerate(args):
        if arg.arg in {"self", "cls"}:
            continue

        default: str | None = None
        default_index = index - offset
        if default_index >= 0:
            default = ast.unparse(defaults[default_index])

        call_args.append(_sample_argument_value(arg, default=default))

    return call_args


# =============================================================================
# GENERATE TESTS TOOL
# =============================================================================


async def generate_tests(
    file_path: str,
    function_name: Optional[str] = None,
    class_name: Optional[str] = None,
    test_framework: str = "pytest",
    output_path: Optional[str] = None,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Generate test cases for a Python file or specific functions/classes.

    Args:
        file_path: Path to the source file
        function_name: Optional function name to generate tests for
        class_name: Optional class name to generate tests for
        test_framework: Test framework to use (pytest, unittest)
        output_path: Optional output file path
        _workspace_dir: Workspace directory

    Returns:
        Generated test code
    """
    try:
        full_path = _resolve_path(file_path, _workspace_dir)
        path_metadata = _path_metadata(full_path, _workspace_dir)

        if not full_path.exists():
            return _error_result(
                f"File not found: {file_path}",
                code="file_not_found",
                hint="Generate tests only for source files inside the workspace.",
                metadata={"requested_path": file_path, **path_metadata},
            )

        content = full_path.read_text(encoding="utf-8")

        tree = ast.parse(content, filename=str(full_path))

        tests_generated: list[str] = []
        import_targets: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if class_name and node.name != class_name:
                    continue

                # Generate tests for class methods
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not item.name.startswith("_"):  # Skip private methods
                            import_targets.add(node.name)
                            tests_generated.append(f"{node.name}.{item.name}")

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if class_name:
                    continue
                if function_name and node.name != function_name:
                    continue

                if not node.name.startswith("_"):
                    import_targets.add(node.name)
                    tests_generated.append(node.name)

        if not tests_generated:
            return _success_result(
                f"No tests generated for {file_path} (no matching functions/classes found)",
                metadata={"tests_generated": 0, **path_metadata},
            )

        module_name, import_root = _module_import_data(full_path, _workspace_dir)
        generated_code = [
            f'"""Auto-generated tests for {full_path.name}."""',
            "from __future__ import annotations",
            "",
            "from pathlib import Path",
            "import sys",
            "",
            "import pytest",
            "",
            f'SOURCE_ROOT = Path(r"{import_root}")',
            "if str(SOURCE_ROOT) not in sys.path:",
            "    sys.path.insert(0, str(SOURCE_ROOT))",
            "",
            f"from {module_name} import {', '.join(sorted(import_targets))}",
            "",
        ]

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if class_name and node.name != class_name:
                    continue
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name.startswith("_"):
                            continue
                        generated_code.append(
                            _generate_function_test(
                                item.name,
                                item,
                                is_method=True,
                                class_name=node.name,
                                docstring=ast.get_docstring(item),
                            )
                        )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if class_name or node.name.startswith("_"):
                    continue
                if function_name and node.name != function_name:
                    continue
                generated_code.append(
                    _generate_function_test(
                        node.name,
                        node,
                        is_method=False,
                        class_name=None,
                        docstring=ast.get_docstring(node),
                    )
                )

        full_test_code = "\n\n".join(generated_code).rstrip() + "\n"
        ast.parse(full_test_code)

        # Write to output file if specified
        if output_path:
            output_full_path = _resolve_path(output_path, _workspace_dir)
        else:
            # Default to test_<filename>.py
            output_full_path = full_path.parent / f"test_{full_path.stem}.py"
        output_full_path.parent.mkdir(parents=True, exist_ok=True)
        output_full_path.write_text(full_test_code, encoding="utf-8")

        return _success_result(
            f"Generated {len(tests_generated)} test(s) for {file_path}",
            metadata={
                "tests_generated": len(tests_generated),
                "test_names": tests_generated,
                "output_file": str(output_full_path),
                "module_name": module_name,
                **path_metadata,
            },
        )

    except ValueError as e:
        return _error_result(
            str(e),
            code="path_outside_workspace",
            hint="Test generation only writes files inside the workspace.",
            metadata={"requested_path": file_path},
        )
    except SyntaxError as e:
        return _error_result(
            f"Syntax error at line {e.lineno}: {e.msg}",
            code="syntax_error",
            hint="Fix the source file syntax before generating tests.",
            metadata={"requested_path": file_path, "lineno": e.lineno},
        )
    except Exception as e:
        logger.error(f"Error generating tests: {e}", exc_info=True)
        return _error_result(
            str(e),
            code="generate_tests_failed",
            metadata={"requested_path": file_path},
        )


def _generate_function_test(
    func_name: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    is_method: bool,
    class_name: Optional[str],
    docstring: Optional[str],
) -> str:
    """Generate test code for a function."""
    is_async = isinstance(node, ast.AsyncFunctionDef)
    test_name = f"test_{func_name}"
    if is_method:
        test_name = f"test_{class_name}_{func_name}" if class_name else f"test_{func_name}"

    call_args = ", ".join(_build_call_arguments(node))
    test_lines: list[str] = []
    if is_async:
        test_lines.append("@pytest.mark.asyncio")
    test_lines.append(f"{'async ' if is_async else ''}def {test_name}() -> None:")
    if docstring:
        test_lines.append(
            f'    """Generated from {func_name}: {docstring[:80].replace(chr(34), chr(39))}."""'
        )
    test_lines.append("    # TODO: replace sample inputs and assertions with real expectations.")
    if is_method and class_name:
        test_lines.append(f"    subject = {class_name}()")
        call_target = f"subject.{func_name}"
    else:
        call_target = func_name
    invocation = f"{'await ' if is_async else ''}{call_target}({call_args})"
    test_lines.append(f"    result = {invocation}")
    test_lines.append("    assert result is not None")
    return "\n".join(test_lines)


def create_generate_tests_tool() -> MCPTool:
    """Create the generate tests tool."""
    return MCPTool(
        name="generate_tests",
        description="Generate test cases for Python files using AST analysis. Can generate tests for specific functions or all functions.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the source file",
                },
                "function_name": {
                    "type": "string",
                    "description": "Optional function name to generate tests for",
                },
                "class_name": {
                    "type": "string",
                    "description": "Optional class name to generate tests for",
                },
                "test_framework": {
                    "type": "string",
                    "enum": ["pytest", "unittest"],
                    "description": "Test framework to use",
                    "default": "pytest",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional output file path",
                },
            },
            "required": ["file_path"],
        },
        handler=generate_tests,
    )


# =============================================================================
# RUN TESTS TOOL
# =============================================================================


async def run_tests(
    file_pattern: str = "test_*.py",
    test_path: Optional[str] = None,
    verbose: bool = False,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Run tests and return results.

    Args:
        file_pattern: Glob pattern for test files
        test_path: Directory containing tests
        verbose: Enable verbose output
        _workspace_dir: Workspace directory

    Returns:
        Test results
    """
    try:
        # Find test files
        if test_path:
            test_dir = _resolve_path(test_path, _workspace_dir)
        else:
            test_dir = Path(_workspace_dir).resolve()

        if not test_dir.exists():
            return _error_result(
                f"Directory not found: {test_path}",
                code="directory_not_found",
                hint="Pass an existing test directory inside the workspace.",
                metadata={"requested_path": test_path},
            )

        test_files = list(test_dir.rglob(file_pattern))

        if not test_files:
            return _success_result(
                f"No test files found matching: {file_pattern}",
                metadata={
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "resolved_test_path": str(test_dir),
                },
            )

        # Run pytest with verbose output for easier parsing
        import sys

        pytest_args = [
            sys.executable,
            "-m",
            "pytest",
            "-v",
            "--tb=short",
        ] + [str(f) for f in test_files]

        result = subprocess.run(
            pytest_args,
            capture_output=True,
            text=True,
            cwd=str(test_dir),
            timeout=120,
        )

        # Parse output - look for PASSED/FAILED in verbose output
        lines = (result.stdout or "").split("\n")
        passed = 0
        failed = 0
        errors = []

        for line in lines:
            # Look for test results in verbose format: "test_file.py::test_function PASSED"
            if "::" in line and "PASSED" in line:
                passed += 1
            elif "::" in line and "FAILED" in line:
                failed += 1
            elif "::" in line and "ERROR" in line:
                failed += 1
                errors.append(line)

        output_lines = [
            f"Test results: {passed} passed, {failed} failed",
            f"Total tests run: {passed + failed}",
        ]
        streams = _format_pytest_streams(result.stdout or "", result.stderr or "")
        metadata = {
            "total": passed + failed,
            "passed": passed,
            "failed": failed,
            "resolved_test_path": str(test_dir),
            "command": pytest_args,
            **_pytest_stream_metadata(result),
        }

        # A non-zero pytest exit with no parsed test failures is a collection
        # or configuration problem, not a successful empty run.
        if result.returncode != 0 and failed == 0:
            output_lines.append("Tests failed to run (check configuration)")
            message = "\n".join(output_lines)
            if streams:
                message = f"{message}\n{streams}"
            return _error_result(
                message,
                code="tests_failed_to_run",
                hint="Inspect pytest stdout/stderr for collection or configuration errors.",
                metadata=metadata,
            )

        if failed > 0:
            output_lines.append(f"\nFailed tests: {failed}")
            output_lines.extend(lines[-min(10, len(lines)) :])  # Last 10 lines

        message = "\n".join(output_lines)
        # Keep assertion failures as a successful tool result, but do not hide stderr.
        if result.stderr and result.stderr.strip():
            message = f"{message}\nstderr:\n{_clip_text(result.stderr.rstrip())}"

        return _success_result(
            message,
            metadata=metadata,
        )

    except ValueError as e:
        return _error_result(
            str(e),
            code="path_outside_workspace",
            hint="Test execution is limited to directories inside the workspace.",
            metadata={"requested_path": test_path},
        )
    except subprocess.TimeoutExpired:
        return _error_result(
            "Test execution timed out after 120 seconds",
            code="test_timeout",
            hint="Narrow file_pattern or test_path and try again.",
            metadata={"requested_path": test_path, "file_pattern": file_pattern},
        )
    except Exception as e:
        logger.error(f"Error running tests: {e}", exc_info=True)
        return _error_result(
            str(e),
            code="run_tests_failed",
            metadata={"requested_path": test_path, "file_pattern": file_pattern},
        )


def create_run_tests_tool() -> MCPTool:
    """Create the run tests tool."""
    return MCPTool(
        name="run_tests",
        description="Run pytest tests and return results. Supports glob patterns for filtering test files.",
        input_schema={
            "type": "object",
            "properties": {
                "file_pattern": {
                    "type": "string",
                    "description": "Glob pattern for test files (default: test_*.py)",
                    "default": "test_*.py",
                },
                "test_path": {
                    "type": "string",
                    "description": "Directory containing tests",
                },
                "verbose": {
                    "type": "boolean",
                    "description": "Enable verbose output",
                    "default": False,
                },
            },
            "required": [],
        },
        handler=run_tests,
    )


# =============================================================================
# ANALYZE COVERAGE TOOL
# =============================================================================


async def analyze_coverage(
    file_path: str,
    use_pytest: bool = True,
    context_lines: int = 0,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Analyze test coverage for a file.

    Args:
        file_path: Path to the source file
        use_pytest: Use pytest-cov for coverage analysis
        context_lines: Lines of context to show
        _workspace_dir: Workspace directory

    Returns:
        Coverage analysis results
    """
    try:
        full_path = _resolve_path(file_path, _workspace_dir)
        path_metadata = _path_metadata(full_path, _workspace_dir)

        if not full_path.exists():
            return _error_result(
                f"File not found: {file_path}",
                code="file_not_found",
                hint="Coverage analysis only works on source files inside the workspace.",
                metadata={"requested_path": file_path, **path_metadata},
            )

        if not use_pytest:
            return _error_result(
                "Coverage analysis requires pytest-cov; no coverage numbers are available without it.",
                code="coverage_unavailable",
                hint="Call analyze_coverage with use_pytest=True and install pytest-cov.",
                metadata={
                    "file_path": file_path,
                    "method": "unavailable",
                    "requested_path": file_path,
                    **path_metadata,
                },
            )

        if use_pytest:
            import sys

            module_name, import_root = _module_import_data(full_path, _workspace_dir)

            candidate_tests = sorted(full_path.parent.glob(f"test*{full_path.stem}*.py"))
            with tempfile.TemporaryDirectory(prefix="coverage-") as temp_dir_str:
                temp_dir = Path(temp_dir_str)
                json_report = temp_dir / "coverage.json"
                pytest_targets: list[str]

                if candidate_tests:
                    pytest_targets = [str(test_path) for test_path in candidate_tests]
                else:
                    helper_test = temp_dir / f"test_{full_path.stem}_coverage.py"
                    helper_test.write_text(
                        "\n".join(
                            [
                                "from __future__ import annotations",
                                "from pathlib import Path",
                                "import sys",
                                "",
                                f'IMPORT_ROOT = Path(r"{import_root}")',
                                "if str(IMPORT_ROOT) not in sys.path:",
                                "    sys.path.insert(0, str(IMPORT_ROOT))",
                                "",
                                f"import {module_name}",
                                "",
                                f"def test_{full_path.stem}_coverage() -> None:",
                                f"    assert {module_name} is not None",
                            ]
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    pytest_targets = [str(helper_test)]

                pytest_args = [
                    sys.executable,
                    "-m",
                    "pytest",
                    "--cov",
                    module_name,
                    f"--cov-report=json:{json_report}",
                    "--cov-report=term-missing:skip-covered",
                    "-q",
                    *pytest_targets,
                ]
                env = os.environ.copy()
                # Only the root that owns this file. Adding the workspace root
                # as well lets a sibling pkg/ shadow src/pkg.
                env["PYTHONPATH"] = os.pathsep.join(
                    [str(import_root), env.get("PYTHONPATH", "")]
                ).rstrip(os.pathsep)
                origin = module_origin_for(module_name, import_root)
                if origin.resolve() != full_path.resolve():
                    return _error_result(
                        "Imported module origin does not match the requested source file",
                        code="module_origin_mismatch",
                        hint="Keep the import root aligned with the file being measured.",
                        metadata={
                            "requested_path": str(full_path),
                            "module_name": module_name,
                            "import_root": str(import_root),
                            "resolved_origin": str(origin),
                        },
                    )

                result = subprocess.run(
                    pytest_args,
                    capture_output=True,
                    text=True,
                    # The import root is the cwd so a sibling package at the
                    # workspace root cannot shadow this file.
                    cwd=str(import_root),
                    env=env,
                    timeout=120,
                )

                coverage_data = _parse_coverage_json(json_report, full_path, roots=[import_root])
                if coverage_data is not None and "coverage_percent" in coverage_data:
                    coverage_data.update(path_metadata)
                    coverage_data["module_name"] = module_name
                    coverage_data["import_root"] = str(import_root)
                    coverage_data["module_origin"] = str(origin)
                    coverage_data["returncode"] = result.returncode
                    coverage_data["used_tests"] = pytest_targets
                    coverage_data.update(_pytest_stream_metadata(result))
                    return _success_result(
                        _format_coverage_result(coverage_data),
                        metadata=coverage_data,
                    )

                streams = _format_pytest_streams(result.stdout or "", result.stderr or "")
                plugin_missing = _coverage_plugin_missing(
                    result.stdout or "", result.stderr or ""
                )
                if plugin_missing:
                    code = "pytest_cov_missing"
                    message = "pytest-cov is not available; coverage numbers were not produced."
                else:
                    code = "coverage_report_unavailable"
                    message = "Coverage analysis did not produce numeric results."
                if streams:
                    message = f"{message}\n{streams}"
                return _error_result(
                    message,
                    code=code,
                    hint="Install pytest-cov and inspect pytest stdout/stderr for the coverage failure.",
                    metadata={
                        "file_path": file_path,
                        "requested_path": file_path,
                        "module_name": module_name,
                        "import_root": str(import_root),
                        "used_tests": pytest_targets,
                        **path_metadata,
                        **_pytest_stream_metadata(result),
                    },
                )

    except ValueError as e:
        return _error_result(
            str(e),
            code="path_outside_workspace",
            hint="Coverage analysis is limited to source files inside the workspace.",
            metadata={"requested_path": file_path},
        )
    except subprocess.TimeoutExpired:
        return _error_result(
            "Coverage analysis timed out after 120 seconds",
            code="coverage_timeout",
            hint="Narrow the target file or simplify the surrounding test suite.",
            metadata={"requested_path": file_path},
        )
    except Exception as e:
        logger.error(f"Error analyzing coverage: {e}", exc_info=True)
        return _error_result(
            f"Coverage analysis failed: {e}",
            code="coverage_analysis_failed",
            hint="Inspect the error and pytest output; numeric coverage was not produced.",
            metadata={"file_path": file_path, "requested_path": file_path},
        )


def _candidate_paths(file_name: str, roots: list[Path]) -> list[Path]:
    """Expand a coverage JSON path against likely roots."""
    candidate = Path(file_name)
    options = [candidate]
    if not candidate.is_absolute():
        options.extend(root / candidate for root in roots)
    return options


def _paths_refer_to_same_file(candidate: Path, target: Path) -> bool:
    """Compare coverage report paths, including macOS /var aliases."""
    try:
        target_resolved = target.resolve()
    except OSError:
        return False
    try:
        resolved = candidate.resolve()
    except OSError:
        return False
    if resolved == target_resolved:
        return True
    try:
        return candidate.exists() and target.exists() and resolved.samefile(target_resolved)
    except OSError:
        return False


def _parse_coverage_json(
    report_path: Path,
    target_file: Path,
    *,
    roots: list[Path] | None = None,
) -> Dict[str, Any] | None:
    """Parse a pytest-cov JSON report for a specific file."""
    if not report_path.exists():
        return None

    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    files = payload.get("files", {})
    target_resolved = target_file.resolve()
    search_roots = [target_resolved.parent]
    if roots:
        search_roots.extend(Path(root) for root in roots)

    for file_name, file_data in files.items():
        if not any(
            _paths_refer_to_same_file(option, target_resolved)
            for option in _candidate_paths(file_name, search_roots)
        ):
            continue

        summary = file_data.get("summary", {})
        return {
            "file_path": str(target_resolved),
            "coverage_percent": round(summary.get("percent_covered", 0), 2),
            "missing_lines": file_data.get("missing_lines", []),
            "covered_lines": file_data.get("executed_lines", []),
        }

    return None


def _format_coverage_result(data: Dict[str, Any]) -> str:
    """Format coverage result for display."""
    lines = [
        f"Coverage for {data['file_path']}:",
        f"Coverage: {data.get('coverage_percent', 0)}%",
    ]

    if data.get("missing_lines"):
        lines.append(f"Missing lines: {len(data['missing_lines'])}")
        if len(data["missing_lines"]) <= 10:
            lines.append(f"  {data['missing_lines']}")
        else:
            lines.append(f"  {data['missing_lines'][:10]}...")

    return "\n".join(lines)


def create_analyze_coverage_tool() -> MCPTool:
    """Create the analyze coverage tool."""
    return MCPTool(
        name="analyze_coverage",
        description="Analyze test coverage for a Python file using pytest-cov. Shows coverage percentage and missing lines.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the source file",
                },
                "use_pytest": {
                    "type": "boolean",
                    "description": "Use pytest-cov for accurate results",
                    "default": True,
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Lines of context to show",
                    "default": 0,
                },
            },
            "required": ["file_path"],
        },
        handler=analyze_coverage,
    )


# =============================================================================
# GET ALL TEST TOOLS
# =============================================================================


def get_test_tools() -> List[MCPTool]:
    """Get all test tool definitions."""
    return [
        create_generate_tests_tool(),
        create_run_tests_tool(),
        create_analyze_coverage_tool(),
    ]
