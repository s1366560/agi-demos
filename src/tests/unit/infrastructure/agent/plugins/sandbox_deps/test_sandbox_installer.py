"""Unit tests for SandboxDependencyInstaller."""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.plugins.sandbox_deps.models import (
    InstallRequest,
    RuntimeDependencies,
)
from src.infrastructure.agent.plugins.sandbox_deps.sandbox_installer import (
    SandboxDependencyInstaller,
)
from src.infrastructure.agent.plugins.sandbox_deps.security_gate import (
    SecurityGate,
    ValidationResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_deps(
    *,
    pip: tuple[str, ...] = (),
    system: tuple[str, ...] = (),
) -> RuntimeDependencies:
    """Create a minimal RuntimeDependencies."""
    return RuntimeDependencies(pip_packages=pip, system_packages=system)


def _make_request(
    *,
    plugin_id: str = "test-plugin",
    project_id: str = "proj-1",
    sandbox_id: str = "sbx-1",
    pip: tuple[str, ...] = (),
    system: tuple[str, ...] = (),
    force: bool = False,
) -> InstallRequest:
    """Create an InstallRequest with sensible defaults."""
    return InstallRequest(
        plugin_id=plugin_id,
        project_id=project_id,
        sandbox_id=sandbox_id,
        dependencies=_make_deps(pip=pip, system=system),
        force=force,
    )


def _mcp_response(
    payload: dict[str, Any] | str,
    *,
    is_error: bool = False,
) -> dict[str, Any]:
    """Build a standard MCP tool response dict."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def _check_response(packages: dict[str, bool]) -> dict[str, Any]:
    """Build a deps_check MCP response dict."""
    return _mcp_response({"packages": packages})


# ---------------------------------------------------------------------------
# Tests: __init__
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSandboxDependencyInstallerInit:
    """Test SandboxDependencyInstaller constructor."""

    async def test_init_default_security_gate(self) -> None:
        """Default SecurityGate should be created when none provided."""
        caller = AsyncMock()
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=caller,
        )
        assert isinstance(installer._security_gate, SecurityGate)

    async def test_init_custom_security_gate(self) -> None:
        """Provided SecurityGate should be used."""
        caller = AsyncMock()
        gate = SecurityGate()
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=caller,
            security_gate=gate,
        )
        assert installer._security_gate is gate

    async def test_init_custom_timeout(self) -> None:
        """Custom timeout should override default."""
        caller = AsyncMock()
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=caller,
            default_timeout=60.0,
        )
        assert installer._default_timeout == 60.0

    async def test_init_default_timeout(self) -> None:
        """Default timeout should be 120.0."""
        caller = AsyncMock()
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=caller,
        )
        assert installer._default_timeout == 120.0


# ---------------------------------------------------------------------------
# Tests: install
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSandboxDependencyInstallerInstall:
    """Test the install() method under various scenarios."""

    async def test_install_security_rejection(self) -> None:
        """SecurityGate rejection should return failure immediately."""
        caller = AsyncMock()
        gate = MagicMock(spec=SecurityGate)
        gate.validate_request.return_value = ValidationResult(
            valid=False,
            errors=("blocked package: evil",),
        )
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=caller,
            security_gate=gate,
        )
        request = _make_request(pip=("evil",))

        result = await installer.install(request)

        assert result.success is False
        assert "blocked package: evil" in result.errors
        # Should NOT have called the sandbox at all
        caller.assert_not_awaited()

    async def test_install_all_packages_already_installed(self) -> None:
        """When all packages are already installed, skip everything."""
        caller = AsyncMock()
        # deps_check returns all True
        caller.return_value = _check_response(
            {"numpy": True, "pandas": True, "curl": True},
        )
        gate = MagicMock(spec=SecurityGate)
        gate.validate_request.return_value = ValidationResult(valid=True)
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=caller,
            security_gate=gate,
        )
        request = _make_request(
            pip=("numpy", "pandas"),
            system=("curl",),
        )

        result = await installer.install(request)

        assert result.success is True
        assert len(result.installed_packages) == 0
        assert set(result.skipped_packages) == {"numpy", "pandas", "curl"}

    async def test_install_missing_pip_packages_success(self) -> None:
        """Missing pip packages should be installed via deps_install."""
        call_count = 0

        async def _caller(
            tool_name: str,
            arguments: dict,
            timeout: float = 60.0,
        ) -> dict:
            nonlocal call_count
            call_count += 1
            if tool_name == "deps_check":
                return _check_response({"numpy": False, "pandas": True})
            if tool_name == "deps_install":
                return _mcp_response(
                    {"installed": ["numpy"], "failed": []},
                )
            return {}

        gate = MagicMock(spec=SecurityGate)
        gate.validate_request.return_value = ValidationResult(valid=True)
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=_caller,
            security_gate=gate,
        )
        request = _make_request(pip=("numpy", "pandas"))

        result = await installer.install(request)

        assert result.success is True
        assert "numpy" in result.installed_packages
        assert "pandas" in result.skipped_packages

    async def test_install_missing_system_packages_success(self) -> None:
        """Missing system packages should be installed via deps_install."""

        async def _caller(
            tool_name: str,
            arguments: dict,
            timeout: float = 60.0,
        ) -> dict:
            if tool_name == "deps_check":
                pkg_type = arguments.get("package_type", "")
                if pkg_type == "system":
                    return _check_response({"ffmpeg": False})
                return _check_response({})
            if tool_name == "deps_install":
                return _mcp_response(
                    {"installed": ["ffmpeg"], "failed": []},
                )
            return {}

        gate = MagicMock(spec=SecurityGate)
        gate.validate_request.return_value = ValidationResult(valid=True)
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=_caller,
            security_gate=gate,
        )
        request = _make_request(system=("ffmpeg",))

        result = await installer.install(request)

        assert result.success is True
        assert "ffmpeg" in result.installed_packages

    async def test_install_tool_call_exception(self) -> None:
        """Exception during deps_install should populate errors."""

        async def _caller(
            tool_name: str,
            arguments: dict,
            timeout: float = 60.0,
        ) -> dict:
            if tool_name == "deps_check":
                return _check_response({"numpy": False})
            if tool_name == "deps_install":
                raise ConnectionError("sandbox unreachable")
            return {}

        gate = MagicMock(spec=SecurityGate)
        gate.validate_request.return_value = ValidationResult(valid=True)
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=_caller,
            security_gate=gate,
        )
        request = _make_request(pip=("numpy",))

        result = await installer.install(request)

        assert result.success is False
        assert len(result.errors) >= 1
        assert "sandbox unreachable" in result.errors[0]

    async def test_install_tool_reports_is_error(self) -> None:
        """Tool returning isError=True should populate errors."""

        async def _caller(
            tool_name: str,
            arguments: dict,
            timeout: float = 60.0,
        ) -> dict:
            if tool_name == "deps_check":
                return _check_response({"numpy": False})
            if tool_name == "deps_install":
                return _mcp_response("install failed", is_error=True)
            return {}

        gate = MagicMock(spec=SecurityGate)
        gate.validate_request.return_value = ValidationResult(valid=True)
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=_caller,
            security_gate=gate,
        )
        request = _make_request(pip=("numpy",))

        result = await installer.install(request)

        assert result.success is False
        assert len(result.errors) >= 1
        assert "install failed" in result.errors[0]

    async def test_install_partial_failure(self) -> None:
        """Some packages installed, some failed."""

        async def _caller(
            tool_name: str,
            arguments: dict,
            timeout: float = 60.0,
        ) -> dict:
            if tool_name == "deps_check":
                return _check_response({"numpy": False, "pandas": False})
            if tool_name == "deps_install":
                return _mcp_response(
                    {
                        "installed": ["numpy"],
                        "failed": [
                            {"package": "pandas", "error": "build failed"},
                        ],
                    },
                )
            return {}

        gate = MagicMock(spec=SecurityGate)
        gate.validate_request.return_value = ValidationResult(valid=True)
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=_caller,
            security_gate=gate,
        )
        request = _make_request(pip=("numpy", "pandas"))

        result = await installer.install(request)

        # Has errors from the failed package
        assert result.success is False
        assert "numpy" in result.installed_packages
        assert any("pandas" in e and "build failed" in e for e in result.errors)

    async def test_install_check_installed_exception_continues(
        self,
    ) -> None:
        """If check_installed raises, install should still proceed."""

        call_order: list[str] = []

        async def _caller(
            tool_name: str,
            arguments: dict,
            timeout: float = 60.0,
        ) -> dict:
            call_order.append(tool_name)
            if tool_name == "deps_check":
                raise RuntimeError("check failed")
            if tool_name == "deps_install":
                return _mcp_response(
                    {"installed": ["numpy"], "failed": []},
                )
            return {}

        gate = MagicMock(spec=SecurityGate)
        gate.validate_request.return_value = ValidationResult(valid=True)
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=_caller,
            security_gate=gate,
        )
        request = _make_request(pip=("numpy",))

        result = await installer.install(request)

        assert result.success is True
        assert "numpy" in result.installed_packages
        # deps_install should still have been called
        assert "deps_install" in call_order

    async def test_install_result_has_duration_ms(self) -> None:
        """InstallResult should include a non-negative duration_ms."""
        caller = AsyncMock()
        caller.return_value = _check_response({})
        gate = MagicMock(spec=SecurityGate)
        gate.validate_request.return_value = ValidationResult(valid=True)
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=caller,
            security_gate=gate,
        )
        request = _make_request()

        result = await installer.install(request)

        assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# Tests: check_installed
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSandboxDependencyInstallerCheckInstalled:
    """Test check_installed method."""

    async def test_check_installed_merges_pip_and_system(self) -> None:
        """check_installed should merge pip and system results."""

        async def _caller(
            tool_name: str,
            arguments: dict,
            timeout: float = 60.0,
        ) -> dict:
            pkg_type = arguments.get("package_type", "")
            if pkg_type == "pip":
                return _check_response({"numpy": True, "pandas": False})
            if pkg_type == "system":
                return _check_response({"curl": True})
            return _check_response({})

        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=_caller,
        )
        deps = _make_deps(pip=("numpy", "pandas"), system=("curl",))

        result = await installer.check_installed(deps)

        assert result["numpy"] is True
        assert result["pandas"] is False
        assert result["curl"] is True

    async def test_check_installed_empty_deps(self) -> None:
        """No packages should return empty dict without calling tool."""
        caller = AsyncMock()
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=caller,
        )
        deps = _make_deps()

        result = await installer.check_installed(deps)

        assert result == {}
        caller.assert_not_awaited()

    async def test_check_installed_pip_only(self) -> None:
        """Only pip packages should call deps_check once."""
        caller = AsyncMock()
        caller.return_value = _check_response({"requests": True})
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=caller,
        )
        deps = _make_deps(pip=("requests",))

        result = await installer.check_installed(deps)

        assert result["requests"] is True
        caller.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests: _parse_tool_result
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSandboxDependencyInstallerParseToolResult:
    """Test _parse_tool_result method."""

    async def test_parse_tool_result_success(self) -> None:
        """Non-error response should return (True, text)."""
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=AsyncMock(),
        )
        raw = _mcp_response({"installed": ["numpy"]})

        success, text = await installer._parse_tool_result(raw)

        assert success is True
        assert "numpy" in text

    async def test_parse_tool_result_error(self) -> None:
        """Error response should return (False, text)."""
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=AsyncMock(),
        )
        raw = _mcp_response("something went wrong", is_error=True)

        success, text = await installer._parse_tool_result(raw)

        assert success is False
        assert "something went wrong" in text

    async def test_parse_tool_result_empty_content(self) -> None:
        """Empty content list should return (True, '')."""
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=AsyncMock(),
        )
        raw: dict = {"content": [], "isError": False}

        success, text = await installer._parse_tool_result(raw)

        assert success is True
        assert text == ""

    async def test_parse_tool_result_missing_keys(self) -> None:
        """Missing keys should default gracefully."""
        installer = SandboxDependencyInstaller(
            sandbox_tool_caller=AsyncMock(),
        )
        raw: dict = {}

        success, text = await installer._parse_tool_result(raw)

        assert success is True
        assert text == ""


# ---------------------------------------------------------------------------
# Tests: _collect_installed_from_text
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSandboxDependencyInstallerCollectInstalled:
    """Test _collect_installed_from_text static method."""

    async def test_collect_installed_valid_json(self) -> None:
        """Valid JSON with installed/failed should be parsed."""
        installed: list[str] = []
        errors: list[str] = []
        text = json.dumps(
            {
                "installed": ["numpy", "pandas"],
                "failed": [
                    {"package": "scipy", "error": "build error"},
                ],
            },
        )

        SandboxDependencyInstaller._collect_installed_from_text(
            text=text,
            packages=("numpy", "pandas", "scipy"),
            installed_out=installed,
            errors_out=errors,
            plugin_id="test-plugin",
            package_type="pip",
        )

        assert installed == ["numpy", "pandas"]
        assert len(errors) == 1
        assert "scipy" in errors[0]
        assert "build error" in errors[0]

    async def test_collect_installed_invalid_json_optimistic(self) -> None:
        """Invalid JSON should fall back to adding all packages."""
        installed: list[str] = []
        errors: list[str] = []

        SandboxDependencyInstaller._collect_installed_from_text(
            text="not json at all",
            packages=("numpy", "pandas"),
            installed_out=installed,
            errors_out=errors,
            plugin_id="test-plugin",
            package_type="pip",
        )

        # Optimistic fallback: all packages assumed installed
        assert installed == ["numpy", "pandas"]
        assert len(errors) == 0

    async def test_collect_installed_non_dict_json(self) -> None:
        """JSON that is not a dict should also use optimistic fallback."""
        installed: list[str] = []
        errors: list[str] = []

        SandboxDependencyInstaller._collect_installed_from_text(
            text=json.dumps(["not", "a", "dict"]),
            packages=("pkg-a",),
            installed_out=installed,
            errors_out=errors,
            plugin_id="test-plugin",
            package_type="pip",
        )

        assert installed == ["pkg-a"]
        assert len(errors) == 0

    async def test_collect_installed_empty_installed_list(self) -> None:
        """Empty installed list with no failures should produce nothing."""
        installed: list[str] = []
        errors: list[str] = []

        SandboxDependencyInstaller._collect_installed_from_text(
            text=json.dumps({"installed": [], "failed": []}),
            packages=("numpy",),
            installed_out=installed,
            errors_out=errors,
            plugin_id="test-plugin",
            package_type="pip",
        )

        assert installed == []
        assert errors == []


# ---------------------------------------------------------------------------
# Tests: _parse_check_result
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSandboxDependencyInstallerParseCheckResult:
    """Test _parse_check_result static method."""

    async def test_parse_check_result_valid(self) -> None:
        """Valid deps_check response should return package booleans."""
        raw = _check_response({"numpy": True, "pandas": False})

        result = SandboxDependencyInstaller._parse_check_result(raw)

        assert result == {"numpy": True, "pandas": False}

    async def test_parse_check_result_flat_dict(self) -> None:
        """Response without 'packages' key should use data directly."""
        raw = _mcp_response({"numpy": True, "pandas": False})

        result = SandboxDependencyInstaller._parse_check_result(raw)

        assert result == {"numpy": True, "pandas": False}

    async def test_parse_check_result_invalid_json(self) -> None:
        """Invalid JSON in response should return empty dict."""
        raw: dict = {
            "content": [{"type": "text", "text": "not json"}],
            "isError": False,
        }

        result = SandboxDependencyInstaller._parse_check_result(raw)

        assert result == {}

    async def test_parse_check_result_empty_content(self) -> None:
        """Empty content list should return empty dict."""
        raw: dict = {"content": [], "isError": False}

        result = SandboxDependencyInstaller._parse_check_result(raw)

        assert result == {}

    async def test_parse_check_result_non_dict_json(self) -> None:
        """Non-dict JSON should return empty dict."""
        raw = _mcp_response([1, 2, 3])

        result = SandboxDependencyInstaller._parse_check_result(raw)

        assert result == {}


# ---------------------------------------------------------------------------
# Tests: _elapsed_ms
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSandboxDependencyInstallerElapsedMs:
    """Test _elapsed_ms static method."""

    async def test_elapsed_ms_returns_non_negative(self) -> None:
        """_elapsed_ms should return a non-negative integer."""
        start = time.monotonic()
        result = SandboxDependencyInstaller._elapsed_ms(start)
        assert isinstance(result, int)
        assert result >= 0

    async def test_elapsed_ms_increases_over_time(self) -> None:
        """A later call should show more elapsed ms."""
        start = time.monotonic() - 0.1  # Simulate 100ms ago
        result = SandboxDependencyInstaller._elapsed_ms(start)
        assert result >= 90  # At least ~90ms accounting for float imprecision
