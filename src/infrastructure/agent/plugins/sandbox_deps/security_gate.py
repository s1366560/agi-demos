"""Security validation layer for sandbox package installation requests.

Validates pip and system packages against allowlists and blocks unsafe
inputs (URLs, absolute paths, shell metacharacters) before they reach the
sandbox runtime.  This module does NOT perform any actual installation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .models import InstallRequest, RuntimeDependencies

logger = logging.getLogger(__name__)

_SAFE_REQUIREMENT_RE = re.compile(
    r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?(?:(==|>=|<=|~=|!=|>|<)[A-Za-z0-9*+!_.-]+)?$"
)

_PEP503_NORMALIZE_RE = re.compile(r"[-_.]+")

# Shell metacharacters that are ALWAYS dangerous.
# NOTE: '>' and '<' are excluded because they appear in valid pip version
# specifiers (>=, <=, >, <).  Shell redirections are caught by
# _SHELL_REDIRECT_RE instead.
_BLOCKED_SHELL_CHARS = frozenset(";|&$`")

# Matches shell redirection patterns that are NOT version specifiers.
# Version specifiers look like: >=1.0, <=2.0, >1.0, <2.0
# Shell redirections look like: >file, >>file, <file, 2>&1
# Key distinction: version specifiers are followed by digits/dots,
# shell redirections target filenames (alpha chars, /, etc.).
_SHELL_REDIRECT_RE = re.compile(
    r"(?:"
    r"\d*>>|"              # append redirect: >>, 2>>
    r"\d*>[^=0-9.]|"       # output redirect (not >= or >1.0): >f, 2>f
    r"\d*>$|"              # trailing >: cmd>
    r"<[^=0-9.]|"           # input redirect (not <= or <3.0): <f
    r"<$"                   # trailing <: cmd<
    r")"
)


@dataclass(frozen=True)
class ValidationResult:
    """Immutable outcome of a security validation pass.

    Attributes:
        valid: ``True`` when no blocking errors were found.
        errors: Tuple of human-readable error descriptions.
        warnings: Tuple of non-blocking advisory messages.
    """

    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class SecurityGate:
    """Validate package installation requests against allowlists.

    The gate rejects any package not present on its allowlists and blocks
    requirement strings that contain URLs, absolute paths, or shell
    metacharacters.  It is intentionally at least as strict as the
    ``_SAFE_REQUIREMENT_RE`` regex used by ``manager.py``.

    Parameters:
        pip_allowlist: Explicit pip package allowlist.  Falls back to
            :pyattr:`DEFAULT_PIP_ALLOWLIST` when ``None``.
        system_allowlist: Explicit system (apt) package allowlist.  Falls
            back to :pyattr:`DEFAULT_SYSTEM_ALLOWLIST` when ``None``.
        blocked_patterns: Additional literal substrings to reject.  Falls
            back to :pyattr:`DEFAULT_BLOCKED_PATTERNS` when ``None``.
    """

    DEFAULT_PIP_ALLOWLIST: frozenset[str] = frozenset(
        {
            "pandas",
            "numpy",
            "scipy",
            "matplotlib",
            "seaborn",
            "scikit-learn",
            "pillow",
            "requests",
            "httpx",
            "aiohttp",
            "beautifulsoup4",
            "lxml",
            "pydantic",
            "rich",
            "click",
            "typer",
            "fastapi",
            "flask",
            "sqlalchemy",
            "pytest",
            "black",
            "ruff",
            "mypy",
            "pyyaml",
            "toml",
            "jinja2",
            "cryptography",
            "boto3",
            "google-cloud-storage",
            "azure-storage-blob",
            "paramiko",
            "openpyxl",
            "xlsxwriter",
            "tabulate",
            "tqdm",
            "tenacity",
            "python-dotenv",
            "arrow",
            "pendulum",
            "orjson",
            "msgpack",
            "protobuf",
            "grpcio",
        }
    )

    DEFAULT_SYSTEM_ALLOWLIST: frozenset[str] = frozenset(
        {
            "ffmpeg",
            "imagemagick",
            "graphviz",
            "poppler-utils",
            "tesseract-ocr",
            "libmagic1",
            "git",
            "curl",
            "wget",
            "jq",
            "tree",
            "zip",
            "unzip",
            "tar",
            "gzip",
        }
    )

    DEFAULT_BLOCKED_PATTERNS: frozenset[str] = frozenset(
        {
            "http://",
            "https://",
            "ftp://",
        }
    )

    def __init__(
        self,
        *,
        pip_allowlist: frozenset[str] | None = None,
        system_allowlist: frozenset[str] | None = None,
        blocked_patterns: frozenset[str] | None = None,
    ) -> None:
        self._pip_allowlist = (
            pip_allowlist if pip_allowlist is not None else self.DEFAULT_PIP_ALLOWLIST
        )
        self._system_allowlist = (
            system_allowlist if system_allowlist is not None else self.DEFAULT_SYSTEM_ALLOWLIST
        )
        self._blocked_patterns = (
            blocked_patterns if blocked_patterns is not None else self.DEFAULT_BLOCKED_PATTERNS
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_request(self, request: InstallRequest) -> ValidationResult:
        """Validate an entire :class:`InstallRequest`.

        Both ``pip_packages`` and ``system_packages`` fields of *request*
        are checked.  All detected errors are collected and returned in a
        single :class:`ValidationResult`; validation is **not** short-
        circuited on the first failure.
        """
        errors: list[str] = []
        warnings: list[str] = []

        deps: RuntimeDependencies = request.dependencies

        pip_errors = self.validate_pip_packages(deps.pip_packages)
        errors.extend(pip_errors)

        sys_errors = self.validate_system_packages(deps.system_packages)
        errors.extend(sys_errors)

        if errors:
            logger.warning(
                "Security gate rejected install request with %d error(s)",
                len(errors),
            )

        return ValidationResult(
            valid=len(errors) == 0,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def validate_pip_packages(
        self,
        packages: tuple[str, ...],
    ) -> list[str]:
        """Validate a sequence of pip requirement strings.

        Returns a list of human-readable error messages.  An empty list
        means every package passed validation.
        """
        errors: list[str] = []
        for req in packages:
            errors.extend(self._check_blocked_content(req, kind="pip"))

            if not self._is_safe_requirement(req):
                errors.append(f"Pip requirement '{req}' contains disallowed characters")
                continue

            name = self._normalize_package_name(self._extract_package_name(req))
            if name not in self._pip_allowlist_normalized:
                errors.append(f"Pip package '{name}' is not on the allowlist")
        return errors

    def validate_system_packages(
        self,
        packages: tuple[str, ...],
    ) -> list[str]:
        """Validate a sequence of system (apt) package names.

        Returns a list of human-readable error messages.  An empty list
        means every package passed validation.
        """
        errors: list[str] = []
        for pkg in packages:
            errors.extend(self._check_blocked_content(pkg, kind="system"))

            if not self._is_safe_requirement(pkg):
                errors.append(f"System package '{pkg}' contains disallowed characters")
                continue

            if pkg not in self._system_allowlist:
                errors.append(f"System package '{pkg}' is not on the allowlist")
        return errors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_package_name(name: str) -> str:
        """Normalize a Python package name per PEP 503.

        Lowercases the name and replaces runs of ``-``, ``_``, or ``.``
        with a single ``-``.
        """
        return _PEP503_NORMALIZE_RE.sub("-", name).lower()

    @staticmethod
    def _extract_package_name(requirement: str) -> str:
        """Extract the bare package name from a requirement specifier.

        ``"pandas>=1.5.0"`` becomes ``"pandas"``.  Extras brackets
        (``pkg[extra]``) are stripped as well.
        """
        # Strip extras first: "pkg[extra]>=1.0" -> "pkg>=1.0"
        base = requirement.split("[", 1)[0]
        # Strip version specifier
        for sep in ("==", ">=", "<=", "~=", "!=", ">", "<"):
            base = base.split(sep, 1)[0]
        return base.strip()

    @staticmethod
    def _is_safe_requirement(requirement: str) -> bool:
        """Return ``True`` when *requirement* matches the safe regex.

        Uses the same pattern as ``_SAFE_REQUIREMENT_RE`` from
        ``manager.py`` to guarantee parity.
        """
        return _SAFE_REQUIREMENT_RE.fullmatch(requirement) is not None

    def _check_blocked_content(
        self,
        value: str,
        *,
        kind: str,
    ) -> list[str]:
        """Check *value* against blocked patterns, paths, and shell chars.

        Returns a list of error messages (empty when clean).
        """
        errors: list[str] = []

        # URL patterns
        for pattern in self._blocked_patterns:
            if pattern in value.lower():
                errors.append(
                    f"{kind.capitalize()} spec '{value}' contains blocked pattern '{pattern}'"
                )

        # Absolute paths
        if value.startswith("/"):
            errors.append(f"{kind.capitalize()} spec '{value}' looks like an absolute path")

        # Shell metacharacters (;|&$`)
        found_chars = _BLOCKED_SHELL_CHARS & set(value)
        if found_chars:
            chars_repr = ", ".join(sorted(found_chars))
            errors.append(
                f"{kind.capitalize()} spec '{value}' contains shell metacharacter(s): {chars_repr}"
            )

        # Shell redirections (> or < used outside version specifiers)
        if _SHELL_REDIRECT_RE.search(value):
            errors.append(
                f"{kind.capitalize()} spec '{value}' contains shell redirection syntax"
            )

        return errors

    # ------------------------------------------------------------------
    # Lazy normalized allowlist
    # ------------------------------------------------------------------

    @property
    def _pip_allowlist_normalized(self) -> frozenset[str]:
        """Return the pip allowlist with PEP 503 normalization applied.

        Computed once and cached on the instance so repeated calls inside
        :meth:`validate_pip_packages` are cheap.
        """
        attr = "_pip_allowlist_normalized_cache"
        cached: frozenset[str] | None = getattr(self, attr, None)
        if cached is not None:
            return cached
        normalized = frozenset(self._normalize_package_name(p) for p in self._pip_allowlist)
        object.__setattr__(self, attr, normalized)
        return normalized
