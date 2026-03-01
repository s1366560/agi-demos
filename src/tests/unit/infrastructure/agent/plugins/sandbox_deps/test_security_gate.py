"""Unit tests for sandbox dependency security gate."""

import pytest

from src.infrastructure.agent.plugins.sandbox_deps.models import (
    InstallRequest,
    RuntimeDependencies,
)
from src.infrastructure.agent.plugins.sandbox_deps.security_gate import (
    SecurityGate,
    ValidationResult,
)


@pytest.mark.unit
class TestValidationResult:
    """Tests for ValidationResult frozen dataclass."""

    def test_valid_result_with_empty_errors(self) -> None:
        """A valid result should have valid=True and no errors."""
        result = ValidationResult(valid=True)
        assert result.valid is True
        assert result.errors == ()
        assert result.warnings == ()

    def test_invalid_result_with_errors(self) -> None:
        """An invalid result should carry error descriptions."""
        result = ValidationResult(
            valid=False,
            errors=("pkg not allowed", "url blocked"),
        )
        assert result.valid is False
        assert len(result.errors) == 2
        assert "pkg not allowed" in result.errors


@pytest.mark.unit
class TestSecurityGateInit:
    """Tests for SecurityGate constructor and allowlist defaults."""

    def test_default_allowlists_used_when_none_passed(self) -> None:
        """Passing None should use DEFAULT_PIP/SYSTEM_ALLOWLIST."""
        gate = SecurityGate()
        assert gate._pip_allowlist is SecurityGate.DEFAULT_PIP_ALLOWLIST
        assert gate._system_allowlist is SecurityGate.DEFAULT_SYSTEM_ALLOWLIST
        assert gate._blocked_patterns is SecurityGate.DEFAULT_BLOCKED_PATTERNS

    def test_custom_allowlists_override_defaults(self) -> None:
        """Explicit allowlists should replace the defaults."""
        custom_pip = frozenset({"my-pkg"})
        custom_sys = frozenset({"my-sys"})
        custom_blocked = frozenset({"gopher://"})
        gate = SecurityGate(
            pip_allowlist=custom_pip,
            system_allowlist=custom_sys,
            blocked_patterns=custom_blocked,
        )
        assert gate._pip_allowlist is custom_pip
        assert gate._system_allowlist is custom_sys
        assert gate._blocked_patterns is custom_blocked


@pytest.mark.unit
class TestValidatePipPackages:
    """Tests for SecurityGate.validate_pip_packages."""

    def test_allowed_package_passes(self) -> None:
        """A package on the default allowlist should pass."""
        gate = SecurityGate()
        errors = gate.validate_pip_packages(("numpy",))
        assert errors == []

    def test_allowed_package_with_version_constraint_passes(self) -> None:
        """A package with == version constraint should pass."""
        gate = SecurityGate()
        errors = gate.validate_pip_packages(("pandas==2.0",))
        assert errors == []

    def test_allowed_package_with_gte_constraint_passes(self) -> None:
        """A package with >= version constraint should pass (bugfix)."""
        gate = SecurityGate()
        errors = gate.validate_pip_packages(("pandas>=1.5.0",))
        assert errors == []

    def test_allowed_package_with_lte_constraint_passes(self) -> None:
        """A package with <= version constraint should pass (bugfix)."""
        gate = SecurityGate()
        errors = gate.validate_pip_packages(("numpy<=2.0",))
        assert errors == []

    def test_allowed_package_with_gt_constraint_passes(self) -> None:
        """A package with > version constraint should pass (bugfix)."""
        gate = SecurityGate()
        errors = gate.validate_pip_packages(("scipy>1.0",))
        assert errors == []

    def test_allowed_package_with_lt_constraint_passes(self) -> None:
        """A package with < version constraint should pass (bugfix)."""
        gate = SecurityGate()
        errors = gate.validate_pip_packages(("flask<3.0",))
        assert errors == []

    def test_allowed_package_with_extras_passes(self) -> None:
        """Extras brackets should be stripped; base name checked."""
        gate = SecurityGate()
        errors = gate.validate_pip_packages(("requests[security]",))
        assert errors == []

    def test_disallowed_package_fails(self) -> None:
        """A package not on the allowlist should fail."""
        gate = SecurityGate()
        errors = gate.validate_pip_packages(("evil-pkg",))
        assert len(errors) == 1
        assert "not on the allowlist" in errors[0]

    def test_url_pattern_blocked(self) -> None:
        """URL-based requirement should be blocked."""
        gate = SecurityGate()
        errors = gate.validate_pip_packages(("https://evil.com/pkg.tar.gz",))
        assert any("blocked pattern" in e for e in errors)

    def test_absolute_path_blocked(self) -> None:
        """Absolute path requirement should be blocked."""
        gate = SecurityGate()
        errors = gate.validate_pip_packages(("/tmp/malicious.whl",))
        assert any("absolute path" in e for e in errors)

    def test_shell_metacharacters_blocked(self) -> None:
        """Shell metacharacters in requirement should be blocked."""
        gate = SecurityGate()
        errors = gate.validate_pip_packages(("numpy; rm -rf /",))
        assert any("shell metacharacter" in e for e in errors)

    def test_shell_redirection_blocked(self) -> None:
        """Shell redirection in requirement should be blocked."""
        gate = SecurityGate()
        errors = gate.validate_pip_packages(("numpy >output.txt",))
        assert any("shell redirection" in e for e in errors)

    def test_empty_tuple_passes(self) -> None:
        """An empty packages tuple should return no errors."""
        gate = SecurityGate()
        errors = gate.validate_pip_packages(())
        assert errors == []

    def test_pep503_normalization_underscore_to_dash(self) -> None:
        """'Scikit_Learn' should normalize to 'scikit-learn' (allowed)."""
        gate = SecurityGate()
        errors = gate.validate_pip_packages(("Scikit_Learn",))
        assert errors == []

    def test_pep503_normalization_capitalized(self) -> None:
        """'Pandas' (capitalized) should normalize to 'pandas'."""
        gate = SecurityGate()
        errors = gate.validate_pip_packages(("Pandas",))
        assert errors == []


@pytest.mark.unit
class TestValidateSystemPackages:
    """Tests for SecurityGate.validate_system_packages."""

    def test_allowed_package_passes(self) -> None:
        """A package on the system allowlist should pass."""
        gate = SecurityGate()
        errors = gate.validate_system_packages(("ffmpeg",))
        assert errors == []

    def test_disallowed_package_fails(self) -> None:
        """A package not on the system allowlist should fail."""
        gate = SecurityGate()
        errors = gate.validate_system_packages(("sudo",))
        assert len(errors) == 1
        assert "not on the allowlist" in errors[0]

    def test_url_pattern_blocked(self) -> None:
        """URL-based system package should be blocked."""
        gate = SecurityGate()
        errors = gate.validate_system_packages(("https://evil.com/pkg.deb",))
        assert any("blocked pattern" in e for e in errors)

    def test_shell_metacharacters_blocked(self) -> None:
        """Shell metacharacters in system package should be blocked."""
        gate = SecurityGate()
        errors = gate.validate_system_packages(("ffmpeg; rm -rf /",))
        assert any("shell metacharacter" in e for e in errors)

    def test_absolute_path_blocked(self) -> None:
        """Absolute path in system package should be blocked."""
        gate = SecurityGate()
        errors = gate.validate_system_packages(("/usr/local/bin/evil",))
        assert any("absolute path" in e for e in errors)


@pytest.mark.unit
class TestValidateRequest:
    """Tests for SecurityGate.validate_request (end-to-end)."""

    @staticmethod
    def _make_request(
        pip: tuple[str, ...] = (),
        system: tuple[str, ...] = (),
    ) -> InstallRequest:
        """Helper to build an InstallRequest with given packages."""
        return InstallRequest(
            plugin_id="test-plugin",
            project_id="proj-1",
            sandbox_id="sb-1",
            dependencies=RuntimeDependencies(
                pip_packages=pip,
                system_packages=system,
            ),
        )

    def test_valid_request_with_all_allowed_packages(self) -> None:
        """All-allowed packages should produce valid=True."""
        gate = SecurityGate()
        req = self._make_request(
            pip=("numpy", "pandas"),
            system=("ffmpeg", "git"),
        )
        result = gate.validate_request(req)
        assert result.valid is True
        assert result.errors == ()

    def test_invalid_pip_valid_system(self) -> None:
        """Invalid pip + valid system -> only pip errors."""
        gate = SecurityGate()
        req = self._make_request(
            pip=("evil-pkg",),
            system=("ffmpeg",),
        )
        result = gate.validate_request(req)
        assert result.valid is False
        assert any("pip" in e.lower() or "evil-pkg" in e for e in result.errors)

    def test_valid_pip_invalid_system(self) -> None:
        """Valid pip + invalid system -> only system errors."""
        gate = SecurityGate()
        req = self._make_request(
            pip=("numpy",),
            system=("sudo",),
        )
        result = gate.validate_request(req)
        assert result.valid is False
        assert any("sudo" in e for e in result.errors)

    def test_both_invalid_combined_errors(self) -> None:
        """Both invalid -> combined errors from pip and system."""
        gate = SecurityGate()
        req = self._make_request(
            pip=("evil-pkg",),
            system=("sudo",),
        )
        result = gate.validate_request(req)
        assert result.valid is False
        assert len(result.errors) >= 2

    def test_empty_dependencies_valid(self) -> None:
        """Empty dependencies should return valid=True."""
        gate = SecurityGate()
        req = self._make_request()
        result = gate.validate_request(req)
        assert result.valid is True
        assert result.errors == ()


@pytest.mark.unit
class TestCustomAllowlists:
    """Tests for SecurityGate with custom allowlists."""

    def test_custom_pip_allowlist_restricts_packages(self) -> None:
        """Only packages in custom pip allowlist should be allowed."""
        gate = SecurityGate(pip_allowlist=frozenset({"my-special-pkg"}))
        assert gate.validate_pip_packages(("my-special-pkg",)) == []
        errors = gate.validate_pip_packages(("numpy",))
        assert len(errors) == 1
        assert "not on the allowlist" in errors[0]

    def test_custom_system_allowlist_restricts_packages(self) -> None:
        """Only packages in custom system allowlist should be allowed."""
        gate = SecurityGate(system_allowlist=frozenset({"custom-tool"}))
        assert gate.validate_system_packages(("custom-tool",)) == []
        errors = gate.validate_system_packages(("ffmpeg",))
        assert len(errors) == 1
        assert "not on the allowlist" in errors[0]


@pytest.mark.unit
class TestNormalizePackageName:
    """Tests for SecurityGate._normalize_package_name static method."""

    def test_underscore_replaced_with_dash(self) -> None:
        """Underscores should be replaced with dashes."""
        result = SecurityGate._normalize_package_name("My_Package")
        assert result == "my-package"

    def test_dots_replaced_with_dash(self) -> None:
        """Dots should be replaced with dashes."""
        result = SecurityGate._normalize_package_name("foo.bar")
        assert result == "foo-bar"

    def test_mixed_separators_collapsed(self) -> None:
        """Runs of mixed separators should become a single dash."""
        result = SecurityGate._normalize_package_name("a_.b")
        assert result == "a-b"

    def test_lowercased(self) -> None:
        """Result should be lowercased."""
        result = SecurityGate._normalize_package_name("UPPER")
        assert result == "upper"


@pytest.mark.unit
class TestExtractPackageName:
    """Tests for SecurityGate._extract_package_name static method."""

    def test_extracts_name_from_version_constraint(self) -> None:
        """'pandas>=1.5.0' -> 'pandas'."""
        result = SecurityGate._extract_package_name("pandas>=1.5.0")
        assert result == "pandas"

    def test_extracts_name_from_extras_with_version(self) -> None:
        """'pkg[extra]>=1.0' -> 'pkg'."""
        result = SecurityGate._extract_package_name("pkg[extra]>=1.0")
        assert result == "pkg"

    def test_extracts_bare_name(self) -> None:
        """'numpy' -> 'numpy' (no version constraint)."""
        result = SecurityGate._extract_package_name("numpy")
        assert result == "numpy"

    def test_extracts_name_with_exact_version(self) -> None:
        """'flask==2.3.1' -> 'flask'."""
        result = SecurityGate._extract_package_name("flask==2.3.1")
        assert result == "flask"


@pytest.mark.unit
class TestIsSafeRequirement:
    """Tests for SecurityGate._is_safe_requirement static method."""

    def test_simple_name_passes(self) -> None:
        """A bare package name should be safe."""
        assert SecurityGate._is_safe_requirement("numpy") is True

    def test_name_with_version_passes(self) -> None:
        """A name with version constraint should be safe."""
        assert SecurityGate._is_safe_requirement("pandas>=2.0") is True

    def test_name_with_extras_passes(self) -> None:
        """A name with extras should be safe."""
        assert SecurityGate._is_safe_requirement("requests[security]") is True

    def test_url_fails(self) -> None:
        """A URL requirement should fail the regex."""
        assert SecurityGate._is_safe_requirement("https://evil.com/pkg.tar.gz") is False

    def test_shell_injection_fails(self) -> None:
        """Shell metacharacters should fail the regex."""
        assert SecurityGate._is_safe_requirement("numpy; rm -rf /") is False

    def test_absolute_path_fails(self) -> None:
        """An absolute path should fail the regex."""
        assert SecurityGate._is_safe_requirement("/tmp/malicious.whl") is False

    def test_pipe_char_fails(self) -> None:
        """Pipe character should fail the regex."""
        assert SecurityGate._is_safe_requirement("pkg|other") is False
