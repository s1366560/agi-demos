"""Filesystem-based custom tool discovery and loading.

Scans ``.memstack/tools/`` for standalone Python files that define tools
using the ``@tool_define`` decorator. Each file is dynamically imported in
isolation so that errors in one tool do not affect others.

Discovery locations (relative to ``base_path``):

* ``.memstack/tools/*.py``          -- single-file tools
* ``.memstack/tools/<name>/tool.py`` -- package-style tools

Usage::

    loader = CustomToolLoader(base_path=Path.cwd())
    tools, diagnostics = loader.load_all()
    # tools: dict[str, ToolInfo]
    # diagnostics: list[CustomToolDiagnostic]
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.infrastructure.agent.tools.define import ToolInfo

if TYPE_CHECKING:
    from src.infrastructure.agent.tools.hooks import ToolHookRegistry

logger = logging.getLogger(__name__)

# Default directory name inside the project root.
DEFAULT_TOOLS_DIR = ".memstack/tools"

# Module name prefix to avoid collisions with real packages.
_MODULE_PREFIX = "_memstack_custom_tool_"


@dataclass(frozen=True)
class CustomToolDiagnostic:
    """Diagnostic record emitted during custom tool loading."""

    file_path: str
    code: str
    message: str
    level: str = "warning"


class CustomToolLoader:
    """Discover and load custom tool files from the filesystem.

    Each tool file is expected to use the ``@tool_define`` decorator which
    auto-registers ``ToolInfo`` instances into the module-level
    ``_TOOL_REGISTRY`` in ``define.py``.

    To avoid polluting that global registry, we:
    1. Snapshot ``_TOOL_REGISTRY`` before import.
    2. Import the file.
    3. Diff to find newly registered tools.
    4. Remove them from the global registry (they live in our own dict).

    Args:
        base_path: Project root directory containing ``.memstack/``.
        tools_dirs: Override directory names to scan (relative to
            ``base_path``). Defaults to ``[".memstack/tools"]``.
    """

    def __init__(
        self,
        base_path: Path,
        tools_dirs: list[str] | None = None,
        hook_registry: ToolHookRegistry | None = None,
    ) -> None:
        self._base_path = base_path
        self._tools_dirs = tools_dirs or [DEFAULT_TOOLS_DIR]
        self._hook_registry = hook_registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def discover_files(self) -> list[Path]:
        """Return all candidate tool files sorted by name.

        Scans for:
        * ``<dir>/*.py`` (excluding ``__init__.py``, ``__pycache__``)
        * ``<dir>/<subdir>/tool.py`` (package-style tools)
        """
        files: list[Path] = []
        for rel_dir in self._tools_dirs:
            tools_dir = self._base_path / rel_dir
            if not tools_dir.is_dir():
                logger.debug("Custom tools dir not found: %s", tools_dir)
                continue

            # Single-file tools: *.py
            for py_file in sorted(tools_dir.glob("*.py")):
                if py_file.name.startswith("__"):
                    continue
                files.append(py_file)

            # Package-style tools: <name>/tool.py
            for subdir in sorted(tools_dir.iterdir()):
                if not subdir.is_dir():
                    continue
                if subdir.name.startswith(("__", ".")):
                    continue
                tool_file = subdir / "tool.py"
                if tool_file.is_file():
                    files.append(tool_file)

        return files

    def load_all(self) -> tuple[dict[str, ToolInfo], list[CustomToolDiagnostic]]:
        """Discover and load all custom tools.

        Returns:
            Tuple of (tool_name -> ToolInfo dict, diagnostics list).
            Diagnostics include info-level entries for successful loads
            and error/warning entries for failures.
        """
        files = self.discover_files()
        if not files:
            return {}, []

        all_tools: dict[str, ToolInfo] = {}
        diagnostics: list[CustomToolDiagnostic] = []

        for file_path in files:
            tools, file_diags = self._load_file(file_path)
            diagnostics.extend(file_diags)

            for name, info in tools.items():
                if name in all_tools:
                    diagnostics.append(
                        CustomToolDiagnostic(
                            file_path=str(file_path),
                            code="duplicate_tool_name",
                            message=(
                                f"Tool '{name}' already loaded from another "
                                f"file; skipping duplicate from {file_path.name}"
                            ),
                            level="warning",
                        )
                    )
                    continue

                # Apply definition hooks if a registry was provided.
                if self._hook_registry is not None:
                    modified = self._hook_registry.apply_definition_hooks(
                        info,
                    )
                    if modified is None:
                        diagnostics.append(
                            CustomToolDiagnostic(
                                file_path=str(file_path),
                                code="tool_suppressed_by_hook",
                                message=(f"Tool '{name}' suppressed by definition hook"),
                                level="info",
                            )
                        )
                        continue
                    info = modified

                all_tools[name] = info

        if all_tools:
            logger.info(
                "Loaded %d custom tool(s) from %s",
                len(all_tools),
                ", ".join(d for d in self._tools_dirs),
            )
        return all_tools, diagnostics

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_file(
        self,
        file_path: Path,
    ) -> tuple[dict[str, ToolInfo], list[CustomToolDiagnostic]]:
        """Load a single tool file and extract ToolInfo instances.

        Uses the snapshot-diff approach on ``_TOOL_REGISTRY`` to capture
        tools registered via ``@tool_define`` without permanent side effects.
        Also scans module-level attributes for ``ToolInfo`` instances that
        may have been created directly (without the decorator).
        """
        diagnostics: list[CustomToolDiagnostic] = []
        module_name = f"{_MODULE_PREFIX}{file_path.stem}"

        # Snapshot the global registry before import.
        from src.infrastructure.agent.tools.define import get_registered_tools, pop_registered_tool

        pre_keys = set(get_registered_tools().keys())

        try:
            module = self._import_file(file_path, module_name)
        except Exception as exc:
            import traceback

            tb = traceback.format_exc()
            diagnostics.append(
                CustomToolDiagnostic(
                    file_path=str(file_path),
                    code="import_failed",
                    message=f"Failed to import: {exc}\n{tb}",
                    level="error",
                )
            )
            logger.error(
                "Custom tool import failed: %s\n%s",
                file_path,
                tb,
            )
            return {}, diagnostics

        # Diff to find newly registered tools.
        post_keys = set(get_registered_tools().keys())
        new_keys = post_keys - pre_keys

        tools: dict[str, ToolInfo] = {}

        # Capture decorator-registered tools.
        for key in new_keys:
            info = pop_registered_tool(key)
            tools[key] = info

        # Also scan module attributes for ToolInfo instances that were
        # assigned directly (e.g. ``my_tool = ToolInfo(...)``).
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            attr = getattr(module, attr_name, None)
            if isinstance(attr, ToolInfo) and attr.name not in tools:
                tools[attr.name] = attr

        if tools:
            diagnostics.append(
                CustomToolDiagnostic(
                    file_path=str(file_path),
                    code="tools_loaded",
                    message=(f"Loaded {len(tools)} tool(s): {', '.join(sorted(tools.keys()))}"),
                    level="info",
                )
            )
        else:
            diagnostics.append(
                CustomToolDiagnostic(
                    file_path=str(file_path),
                    code="no_tools_found",
                    message="No @tool_define tools found in file",
                    level="warning",
                )
            )

        return tools, diagnostics

    @staticmethod
    def _import_file(file_path: Path, module_name: str) -> types.ModuleType:
        """Dynamically import a Python file as a module.

        The module is added to ``sys.modules`` so that relative imports
        within the tool file can resolve, and removed on failure.
        """
        spec = importlib.util.spec_from_file_location(
            module_name,
            file_path,
        )
        if spec is None or spec.loader is None:
            msg = f"Cannot create module spec for {file_path}"
            raise ImportError(msg)

        module = importlib.util.module_from_spec(spec)

        # Temporarily register in sys.modules for import resolution.
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            # Clean up on failure.
            sys.modules.pop(module_name, None)
            raise

        return module


def load_custom_tools(
    base_path: Path | None = None,
    tools_dirs: list[str] | None = None,
    hook_registry: ToolHookRegistry | None = None,
) -> tuple[dict[str, ToolInfo], list[CustomToolDiagnostic]]:
    """Convenience function to load custom tools.

    Args:
        base_path: Project root. Defaults to ``Path.cwd()``.
        tools_dirs: Override tool directories. Defaults to
            ``[".memstack/tools"]``.
        hook_registry: Optional :class:`ToolHookRegistry` to apply
            definition hooks to each loaded tool.

    Returns:
        Tuple of (tool_name -> ToolInfo, diagnostics).
    """
    path = base_path or Path.cwd()
    loader = CustomToolLoader(
        base_path=path,
        tools_dirs=tools_dirs,
        hook_registry=hook_registry,
    )
    return loader.load_all()


def get_custom_tool_infos(
    base_path: Path | None = None,
    hook_registry: ToolHookRegistry | None = None,
) -> dict[str, Any]:
    """Load custom tools and return as a dict suitable for tool providers.

    This is the entry point used by ``create_custom_tool_provider()``.
    Errors are logged but do not propagate.

    Args:
        base_path: Project root. Defaults to ``Path.cwd()``.
        hook_registry: Optional :class:`ToolHookRegistry` to apply
            definition hooks to each loaded tool.

    Returns:
        Dict of tool_name -> ToolInfo for all successfully loaded tools.
    """
    try:
        tools, diagnostics = load_custom_tools(
            base_path=base_path,
            hook_registry=hook_registry,
        )
        for diag in diagnostics:
            log_fn = getattr(logger, diag.level, logger.info)
            log_fn(
                "[CustomTools] %s: %s (%s)",
                diag.code,
                diag.message,
                diag.file_path,
            )
        return dict(tools)
    except Exception:
        logger.exception("Failed to load custom tools")
        return {}
