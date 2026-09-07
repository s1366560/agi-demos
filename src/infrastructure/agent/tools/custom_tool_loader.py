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

import contextlib
import importlib.util
import logging
import sys
import types
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.infrastructure.agent.plugins.sandbox_deps.models import (
    ExecutionContext,
    RuntimeDependencies,
)
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.result import ToolResult

if TYPE_CHECKING:
    from src.domain.ports.services.sandbox_port import SandboxPort
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
    registers ``ToolInfo`` instances into an invocation-local capture during
    import. The process-global decorator registry is never consulted or
    mutated by this loader.

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
        sandbox_port: SandboxPort | None = None,
        sandbox_id: str | None = None,
        sandbox_mode: bool = False,
    ) -> None:
        self._base_path = base_path
        self._tools_dirs = tools_dirs or [DEFAULT_TOOLS_DIR]
        self._hook_registry = hook_registry
        self._sandbox_port = sandbox_port
        self._sandbox_id = sandbox_id
        self._sandbox_mode = sandbox_mode and sandbox_port is not None and sandbox_id is not None

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

                info = replace(info, tags=info.tags | frozenset({"custom"}))
                if self._sandbox_mode:
                    info = self._wrap_as_sandbox_tool(info, file_path)
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

    @staticmethod
    def _parse_dependency_header(file_path: Path) -> list[str]:
        """Parse memstack dependency header comments from tool file.

        Looks for lines matching::

            # memstack:dependencies: pkg1>=1.0, pkg2, pkg3>=2.0

        in the first 10 lines of the file.

        Returns:
            List of pip requirement strings.
        """
        deps: list[str] = []
        try:
            with open(file_path, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i >= 10:
                        break
                    stripped = line.strip()
                    if stripped.startswith("# memstack:dependencies:"):
                        raw = stripped[len("# memstack:dependencies:") :].strip()
                        deps.extend(d.strip() for d in raw.split(",") if d.strip())
        except OSError:
            pass
        return deps

    def _wrap_as_sandbox_tool(
        self,
        host_info: ToolInfo,
        file_path: Path,
    ) -> ToolInfo:
        """Wrap a host-extracted ToolInfo as a sandbox-delegating tool.

        Keeps the metadata (name, description, parameters) from the host
        import but replaces the execute callable with one that delegates
        to sandbox_port.call_tool().
        """
        sandbox_port = self._sandbox_port
        sandbox_id = self._sandbox_id
        tool_name = host_info.name

        # Parse dependency header
        dep_strings = self._parse_dependency_header(file_path)

        async def execute(ctx: Any, **kwargs: Any) -> ToolResult:
            """Execute custom tool via sandbox."""
            assert sandbox_port is not None
            assert sandbox_id is not None
            try:
                result = await sandbox_port.call_tool(
                    sandbox_id,
                    tool_name,
                    kwargs,
                )
                if result.get("is_error") or result.get("isError"):
                    content_list = result.get("content", [])
                    error_msg = ""
                    if content_list:
                        first = content_list[0]
                        error_msg = first.get("text", "") if isinstance(first, dict) else str(first)
                    return ToolResult(
                        output=error_msg or f"Tool {tool_name} failed",
                        is_error=True,
                    )
                content_list = result.get("content", [])
                if content_list:
                    first = content_list[0]
                    output = first.get("text", "") if isinstance(first, dict) else str(first)
                else:
                    output = "Success"
                return ToolResult(output=output)
            except Exception as exc:
                return ToolResult(output=f"Sandbox execution failed: {exc}", is_error=True)

        # Build dependencies if header found
        dependencies: RuntimeDependencies | None = None
        if dep_strings:
            dependencies = RuntimeDependencies(pip_packages=tuple(dep_strings))

        return ToolInfo(
            name=host_info.name,
            description=host_info.description,
            parameters=host_info.parameters,
            execute=execute,
            permission=host_info.permission,
            category=host_info.category,
            model_filter=host_info.model_filter,
            tags=host_info.tags | frozenset({"sandbox", "custom"}),
            execution_context=ExecutionContext.SANDBOX,
            dependencies=dependencies,
        )

    def _load_file(
        self,
        file_path: Path,
    ) -> tuple[dict[str, ToolInfo], list[CustomToolDiagnostic]]:
        """Load a single tool file and extract ToolInfo instances.

        Uses an invocation-local decorator capture to collect tools registered
        via ``@tool_define`` without process-global side effects.
        Also scans module-level attributes for ``ToolInfo`` instances that
        may have been created directly (without the decorator).
        """
        diagnostics: list[CustomToolDiagnostic] = []
        module_name = f"{_MODULE_PREFIX}{file_path.stem}"

        from src.infrastructure.agent.tools.define import capture_tool_definitions

        try:
            with capture_tool_definitions() as captured:
                module = self._import_file(file_path, module_name, base_path=self._base_path)
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

        tools = dict(captured)

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
    def _import_file(
        file_path: Path,
        module_name: str,
        base_path: Path | None = None,
    ) -> types.ModuleType:
        """Dynamically import a Python file as a module.

        The module is added to ``sys.modules`` so that relative imports
        within the tool file can resolve, and removed on failure.

        When *base_path* is provided it is temporarily prepended to
        ``sys.path`` so that ``from memstack_tools import ...`` works
        for tool files that use the public SDK package.
        """
        # Ensure the project root is importable (memstack_tools lives there).
        added_to_path = False
        if base_path is not None:
            base_str = str(base_path)
            if base_str not in sys.path:
                sys.path.insert(0, base_str)
                added_to_path = True

        try:
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
        finally:
            if added_to_path:
                with contextlib.suppress(ValueError):
                    sys.path.remove(str(base_path))


def load_custom_tools(
    base_path: Path | None = None,
    tools_dirs: list[str] | None = None,
    hook_registry: ToolHookRegistry | None = None,
    sandbox_port: SandboxPort | None = None,
    sandbox_id: str | None = None,
    sandbox_mode: bool = False,
) -> tuple[dict[str, ToolInfo], list[CustomToolDiagnostic]]:
    """Convenience function to load custom tools.

    Args:
        base_path: Project root. Defaults to ``Path.cwd()``.
        tools_dirs: Override tool directories. Defaults to
            ``[".memstack/tools"]``.
        hook_registry: Optional :class:`ToolHookRegistry` to apply
            definition hooks to each loaded tool.
        sandbox_port: Optional :class:`SandboxPort` for sandbox execution.
        sandbox_id: Optional sandbox identifier.
        sandbox_mode: When True, wrap tools for sandbox execution.

    Returns:
        Tuple of (tool_name -> ToolInfo, diagnostics).
    """
    path = base_path or Path.cwd()
    loader = CustomToolLoader(
        base_path=path,
        tools_dirs=tools_dirs,
        hook_registry=hook_registry,
        sandbox_port=sandbox_port,
        sandbox_id=sandbox_id,
        sandbox_mode=sandbox_mode,
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
