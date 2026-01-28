"""Code indexing tools for MCP server.

Provides code indexing and navigation capabilities for Python projects.
"""

import ast
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.server.websocket_server import MCPTool

logger = logging.getLogger(__name__)


# =============================================================================
# SYMBOL INDEX DATA STRUCTURE
# =============================================================================


@dataclass
class SymbolIndex:
    """In-memory code index for Python projects."""

    definitions: Dict[str, List[Dict]] = field(default_factory=dict)
    references: Dict[str, List[Dict]] = field(default_factory=dict)
    call_graph: Dict[str, Set[str]] = field(default_factory=dict)
    files_indexed: Set[str] = field(default_factory=set)
    import_graph: Dict[str, Set[str]] = field(default_factory=dict)  # module -> imported modules
    class_hierarchy: Dict[str, List[str]] = field(default_factory=dict)  # class -> base classes

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "definitions": self.definitions,
            "references": {k: list(v) for k, v in self.references.items()},
            "call_graph": {k: list(v) for k, v in self.call_graph.items()},
            "import_graph": {k: list(v) for k, v in self.import_graph.items()},
            "class_hierarchy": self.class_hierarchy,
            "files_indexed": list(self.files_indexed),
            "stats": {
                "total_definitions": sum(len(v) for v in self.definitions.values()),
                "total_files": len(self.files_indexed),
            },
        }


class CodeIndexer:
    """Code indexer for Python projects."""

    def __init__(self, workspace_dir: str):
        """Initialize the code indexer.

        Args:
            workspace_dir: Root workspace directory
        """
        self.workspace_dir = Path(workspace_dir)
        self.index = SymbolIndex()
        self._index_lock = asyncio.Lock()

    async def build(
        self,
        project_path: str,
        pattern: str = "**/*.py",
        exclude_dirs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Build index for a project.

        Args:
            project_path: Path to the project directory
            pattern: Glob pattern for source files
            exclude_dirs: Directories to exclude (e.g., ['venv', '.git'])

        Returns:
            Build statistics
        """
        async with self._index_lock:
            if exclude_dirs is None:
                exclude_dirs = ["venv", ".venv", "__pycache__", ".git", "node_modules", "dist", "build"]

            project = self.workspace_dir / project_path
            if not project.exists():
                return {
                    "error": f"Project path not found: {project_path}",
                    "files_indexed": 0,
                }

            # Find all Python files
            py_files = []
            for py_file in project.rglob("*.py"):
                # Skip excluded directories
                if any(excluded in py_file.parts for excluded in exclude_dirs):
                    continue
                py_files.append(py_file)

            # Index files in parallel
            tasks = [
                self._index_file(str(py_file.relative_to(self.workspace_dir)))
                for py_file in py_files
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

            return {
                "files_indexed": len(self.index.files_indexed),
                "total_definitions": sum(len(v) for v in self.index.definitions.values()),
                "total_references": sum(len(v) for v in self.index.references.values()),
                "call_graph_nodes": len(self.index.call_graph),
            }

    async def _index_file(self, file_path: str) -> None:
        """Index a single Python file.

        Args:
            file_path: Relative path to the file
        """
        if file_path in self.index.files_indexed:
            return

        full_path = self.workspace_dir / file_path

        try:
            content = full_path.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(full_path))

            # Get module name
            module_name = file_path.replace("/", ".").replace("\\", ".").removesuffix(".py")

            # Track imports for this module
            imported_modules = set()

            for node in ast.walk(tree):
                # Index definitions
                if isinstance(node, ast.ClassDef):
                    self._add_definition(node.name, {
                        "file": file_path,
                        "lineno": node.lineno,
                        "end_lineno": node.end_lineno,
                        "type": "class",
                        "module": module_name,
                    })
                    # Track base classes
                    bases = []
                    for base in node.bases:
                        if isinstance(base, ast.Name):
                            bases.append(base.id)
                        elif isinstance(base, ast.Attribute):
                            bases.append(ast.unparse(base))
                    if bases:
                        self.index.class_hierarchy[node.name] = bases

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self._add_definition(node.name, {
                        "file": file_path,
                        "lineno": node.lineno,
                        "end_lineno": node.end_lineno,
                        "type": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                        "module": module_name,
                    })

                    # Track function arguments as local definitions
                    for arg in node.args.args:
                        if arg.arg not in ["self", "cls"]:
                            self._add_definition(arg.arg, {
                                "file": file_path,
                                "lineno": node.lineno,
                                "type": "parameter",
                                "scope": node.name,
                            })

                # Index imports
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name
                        imported_modules.add(module_name)
                        # Track imported symbols
                        symbol_name = alias.asname or module_name.split(".")[0]
                        self._add_definition(symbol_name, {
                            "file": file_path,
                            "lineno": node.lineno,
                            "type": "imported_module",
                            "from_module": module_name,
                        })

                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    imported_modules.add(module)
                    for alias in node.names:
                        self._add_definition(alias.name, {
                            "file": file_path,
                            "lineno": node.lineno,
                            "type": "imported_symbol",
                            "from_module": module,
                        })

                # Index name references (simplified)
                elif isinstance(node, ast.Name):
                    # Only track references to things that might be definitions
                    if node.id not in ["True", "False", "None"]:
                        self._add_reference(node.id, {
                            "file": file_path,
                            "lineno": node.lineno,
                            "type": "name_ref",
                        })

                # Track function calls
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        self._add_call(node.func.id, node.func.id, file_path)
                    elif isinstance(node.func, ast.Attribute):
                        # Method call like obj.method()
                        if isinstance(node.func.value, ast.Name):
                            self._add_call(node.func.value.id, node.func.attr, file_path)

            # Record import graph
            if imported_modules:
                module_key = file_path.replace("/", ".").removesuffix(".py")
                self.index.import_graph[module_key] = imported_modules

            self.index.files_indexed.add(file_path)

        except SyntaxError:
            # Skip files with syntax errors
            logger.debug(f"Skipping file with syntax error: {file_path}")
        except Exception as e:
            logger.debug(f"Failed to index {file_path}: {e}")

    def _add_definition(self, name: str, location: Dict) -> None:
        """Add a symbol definition."""
        if name not in self.index.definitions:
            self.index.definitions[name] = []
        # Avoid duplicates
        for existing in self.index.definitions[name]:
            if existing["file"] == location["file"] and existing["lineno"] == location["lineno"]:
                return
        self.index.definitions[name].append(location)

    def _add_reference(self, name: str, location: Dict) -> None:
        """Add a symbol reference."""
        if name not in self.index.references:
            self.index.references[name] = []
        # Limit references per symbol to avoid memory issues
        if len(self.index.references[name]) < 1000:
            self.index.references[name].append(location)

    def _add_call(self, caller: str, callee: str, file_path: str) -> None:
        """Add a function call to the call graph."""
        if caller not in self.index.call_graph:
            self.index.call_graph[caller] = set()
        self.index.call_graph[caller].add(callee)

    def find_definition(self, symbol_name: str) -> Optional[List[Dict]]:
        """Find symbol definition.

        Args:
            symbol_name: Name of the symbol to find

        Returns:
            List of definition locations or None
        """
        return self.index.definitions.get(symbol_name)

    def find_references(self, symbol_name: str) -> Optional[List[Dict]]:
        """Find all references to a symbol.

        Args:
            symbol_name: Name of the symbol

        Returns:
            List of reference locations or None
        """
        return self.index.references.get(symbol_name)

    def get_call_graph(self, symbol_name: Optional[str] = None) -> Dict[str, Any]:
        """Get call graph.

        Args:
            symbol_name: Optional specific symbol to get calls for

        Returns:
            Call graph data
        """
        if symbol_name:
            return {
                "symbol": symbol_name,
                "calls": list(self.index.call_graph.get(symbol_name, set())),
                "called_by": [
                    caller for caller, callees in self.index.call_graph.items()
                    if symbol_name in callees
                ],
            }
        return {k: list(v) for k, v in self.index.call_graph.items()}


# Global indexer instances per workspace
_indexers: Dict[str, CodeIndexer] = {}


def get_indexer(workspace_dir: str) -> CodeIndexer:
    """Get or create indexer for workspace.

    Args:
        workspace_dir: Workspace directory path

    Returns:
        CodeIndexer instance
    """
    if workspace_dir not in _indexers:
        _indexers[workspace_dir] = CodeIndexer(workspace_dir)
    return _indexers[workspace_dir]


def reset_indexer(workspace_dir: str) -> None:
    """Reset indexer for workspace.

    Args:
        workspace_dir: Workspace directory path
    """
    if workspace_dir in _indexers:
        del _indexers[workspace_dir]


# =============================================================================
# CODE INDEX BUILD TOOL
# =============================================================================


async def code_index_build(
    project_path: str,
    force_rebuild: bool = False,
    pattern: str = "**/*.py",
    exclude_dirs: Optional[List[str]] = None,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """Build code index for a project.

    Args:
        project_path: Path to the project directory
        force_rebuild: Force rebuilding even if index exists
        pattern: Glob pattern for source files
        exclude_dirs: Directories to exclude
        _workspace_dir: Workspace directory

    Returns:
        Index build result
    """
    try:
        if force_rebuild:
            reset_indexer(_workspace_dir)

        indexer = get_indexer(_workspace_dir)
        result = await indexer.build(project_path, pattern, exclude_dirs)

        if "error" in result:
            return {
                "content": [{"type": "text", "text": result["error"]}],
                "isError": True,
            }

        lines = [
            f"Code index built for project: {project_path}",
            f"Files indexed: {result['files_indexed']}",
            f"Definitions found: {result['total_definitions']}",
            f"References tracked: {result['total_references']}",
            f"Call graph nodes: {result['call_graph_nodes']}",
        ]

        return {
            "content": [{"type": "text", "text": "\n".join(lines)}],
            "isError": False,
            "metadata": result,
        }

    except Exception as e:
        logger.error(f"Error building index: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def create_code_index_build_tool() -> MCPTool:
    """Create the code index build tool."""
    return MCPTool(
        name="code_index_build",
        description="Build code index for a Python project. Indexes classes, functions, imports, and their relationships.",
        input_schema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Path to the project directory",
                },
                "force_rebuild": {
                    "type": "boolean",
                    "description": "Force rebuilding the index",
                    "default": False,
                },
                "exclude_dirs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Directories to exclude from indexing",
                    "default": ["venv", ".venv", "__pycache__", ".git"],
                },
            },
            "required": ["project_path"],
        },
        handler=code_index_build,
    )


# =============================================================================
# FIND DEFINITION TOOL
# =============================================================================


async def find_definition(
    symbol_name: str,
    symbol_type: Optional[str] = None,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """Find definition of a symbol.

    Args:
        symbol_name: Name of the symbol to find
        symbol_type: Optional filter by type (class, function, etc.)
        _workspace_dir: Workspace directory

    Returns:
        Symbol definition locations
    """
    try:
        indexer = get_indexer(_workspace_dir)
        definitions = indexer.find_definition(symbol_name)

        if not definitions:
            return {
                "content": [{"type": "text", "text": f"Definition not found: {symbol_name}\n\nTip: Run code_index_build first to create the index."}],
                "isError": False,
                "metadata": {"found": False, "symbol": symbol_name},
            }

        # Filter by type if specified
        if symbol_type:
            definitions = [d for d in definitions if d.get("type") == symbol_type]

        if not definitions:
            return {
                "content": [{"type": "text", "text": f"Definition not found: {symbol_name} (type: {symbol_type})"}],
                "isError": False,
                "metadata": {"found": False, "symbol": symbol_name, "type_filter": symbol_type},
            }

        # Format output
        lines = [f"Definitions for '{symbol_name}':"]
        for d in definitions:
            type_label = d.get("type", "unknown")
            file_path = d.get("file", "")
            lineno = d.get("lineno", 0)
            module = d.get("module", "")
            if module:
                lines.append(f"  {file_path}:{lineno} ({type_label} in {module})")
            else:
                lines.append(f"  {file_path}:{lineno} ({type_label})")

        return {
            "content": [{"type": "text", "text": "\n".join(lines)}],
            "isError": False,
            "metadata": {"found": True, "symbol": symbol_name, "definitions": definitions},
        }

    except Exception as e:
        logger.error(f"Error finding definition: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def create_find_definition_tool() -> MCPTool:
    """Create the find definition tool."""
    return MCPTool(
        name="find_definition",
        description="Find the definition of a symbol in the indexed codebase. Run code_index_build first.",
        input_schema={
            "type": "object",
            "properties": {
                "symbol_name": {
                    "type": "string",
                    "description": "Name of the symbol to find",
                },
                "symbol_type": {
                    "type": "string",
                    "enum": ["class", "function", "async_function", "imported_module", "imported_symbol", "parameter"],
                    "description": "Optional filter by symbol type",
                },
            },
            "required": ["symbol_name"],
        },
        handler=find_definition,
    )


# =============================================================================
# FIND REFERENCES TOOL
# =============================================================================


async def find_references(
    symbol_name: str,
    group_by_file: bool = True,
    max_results: int = 100,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """Find all references to a symbol.

    Args:
        symbol_name: Name of the symbol
        group_by_file: Group results by file
        max_results: Maximum number of references to return
        _workspace_dir: Workspace directory

    Returns:
        List of reference locations
    """
    try:
        indexer = get_indexer(_workspace_dir)
        references = indexer.find_references(symbol_name)

        if not references:
            return {
                "content": [{"type": "text", "text": f"No references found: {symbol_name}\n\nTip: Run code_index_build first to create the index."}],
                "isError": False,
                "metadata": {"found": False, "symbol": symbol_name},
            }

        # Limit results
        references = references[:max_results]

        if group_by_file:
            # Group by file for cleaner output
            by_file: Dict[str, List[int]] = {}
            for ref in references:
                file = ref.get("file", "unknown")
                if file not in by_file:
                    by_file[file] = []
                by_file[file].append(ref.get("lineno", 0))

            lines = [f"References to '{symbol_name}' (showing {len(by_file)} files):"]
            for file, lines_list in sorted(by_file.items()):
                unique_lines = sorted(set(lines_list))
                if len(unique_lines) <= 10:
                    lines_str = ", ".join(map(str, unique_lines))
                    lines.append(f"  {file}: lines {lines_str}")
                else:
                    lines.append(f"  {file}: {len(unique_lines)} references")

        else:
            lines = [f"References to '{symbol_name}':"]
            for ref in references[:50]:
                file = ref.get("file", "unknown")
                lineno = ref.get("lineno", 0)
                lines.append(f"  {file}:{lineno}")

        return {
            "content": [{"type": "text", "text": "\n".join(lines)}],
            "isError": False,
            "metadata": {
                "found": True,
                "symbol": symbol_name,
                "total_references": len(references),
                "references": references,
            },
        }

    except Exception as e:
        logger.error(f"Error finding references: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def create_find_references_tool() -> MCPTool:
    """Create the find references tool."""
    return MCPTool(
        name="find_references",
        description="Find all references to a symbol in the indexed codebase. Run code_index_build first.",
        input_schema={
            "type": "object",
            "properties": {
                "symbol_name": {
                    "type": "string",
                    "description": "Name of the symbol",
                },
                "group_by_file": {
                    "type": "boolean",
                    "description": "Group results by file",
                    "default": True,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of references to return",
                    "default": 100,
                },
            },
            "required": ["symbol_name"],
        },
        handler=find_references,
    )


# =============================================================================
# CALL GRAPH TOOL
# =============================================================================


async def get_call_graph(
    symbol_name: Optional[str] = None,
    max_depth: int = 1,
    format_output: str = "text",
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """Get call graph for a function or the entire project.

    Args:
        symbol_name: Optional symbol to get calls for
        max_depth: Maximum depth of call graph (1-2 recommended)
        format_output: Output format (text, json)
        _workspace_dir: Workspace directory

    Returns:
        Call graph structure
    """
    try:
        indexer = get_indexer(_workspace_dir)

        if symbol_name:
            graph = indexer.get_call_graph(symbol_name)

            if not graph["calls"] and not graph["called_by"]:
                return {
                    "content": [{"type": "text", "text": f"No call information found for: {symbol_name}"}],
                    "isError": False,
                    "metadata": {"symbol": symbol_name, "found": False},
                }

            lines = [f"Call graph for '{symbol_name}':"]

            if graph["calls"]:
                lines.append(f"  Calls ({len(graph['calls'])}):")
                for callee in sorted(graph["calls"]):
                    lines.append(f"    - {callee}")

            if graph["called_by"]:
                lines.append(f"  Called by ({len(graph['called_by'])}):")
                for caller in sorted(graph["called_by"]):
                    lines.append(f"    - {caller}")

            # Add depth if requested
            if max_depth > 1 and graph["calls"]:
                lines.append("")
                lines.append("  Depth 2 (what these functions call):")
                for callee in sorted(list(graph["calls"])[:20]):  # Limit for performance
                    callee_graph = indexer.get_call_graph(callee)
                    if callee_graph.get("calls"):
                        lines.append(f"    {callee} calls: {', '.join(list(callee_graph['calls'])[:5])}")

            return {
                "content": [{"type": "text", "text": "\n".join(lines)}],
                "isError": False,
                "metadata": {"symbol": symbol_name, "graph": graph},
            }

        else:
            # Return summary of entire call graph
            all_calls = indexer.index.call_graph
            total_edges = sum(len(callees) for callees in all_calls.values())

            lines = [
                f"Project call graph summary:",
                f"  Functions with calls: {len(all_calls)}",
                f"  Total call edges: {total_edges}",
                "",
                "Top 20 functions by number of calls:",
            ]

            # Sort by number of outgoing calls
            sorted_funcs = sorted(all_calls.items(), key=lambda x: len(x[1]), reverse=True)[:20]
            for func, callees in sorted_funcs:
                lines.append(f"  {func}: {len(callees)} calls")

            return {
                "content": [{"type": "text", "text": "\n".join(lines)}],
                "isError": False,
                "metadata": {
                    "total_functions": len(all_calls),
                    "total_edges": total_edges,
                    "top_functions": [
                        {"name": f, "calls": len(c)} for f, c in sorted_funcs
                    ],
                },
            }

    except Exception as e:
        logger.error(f"Error getting call graph: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def create_call_graph_tool() -> MCPTool:
    """Create the call graph tool."""
    return MCPTool(
        name="call_graph",
        description="Get the call graph for a function or the entire project. Shows which functions call which.",
        input_schema={
            "type": "object",
            "properties": {
                "symbol_name": {
                    "type": "string",
                    "description": "Optional function name to get calls for",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum depth of call graph (default: 1)",
                    "default": 1,
                    "minimum": 1,
                    "maximum": 3,
                },
            },
            "required": [],
        },
        handler=get_call_graph,
    )


# =============================================================================
# DEPENDENCY GRAPH TOOL
# =============================================================================


async def get_dependency_graph(
    project_path: str,
    format_output: str = "text",
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """Get dependency graph (import relationships) for a project.

    Args:
        project_path: Path to the project
        format_output: Output format (text, json)
        _workspace_dir: Workspace directory

    Returns:
        Dependency graph structure
    """
    try:
        indexer = get_indexer(_workspace_dir)

        if not indexer.index.import_graph:
            return {
                "content": [{"type": "text", "text": "No import graph available. Run code_index_build first."}],
                "isError": False,
            }

        import_graph = indexer.index.import_graph

        # Group by module
        external_deps: Dict[str, Set[str]] = {}
        internal_deps: Dict[str, Set[str]] = {}

        for file_path, imports in import_graph.items():
            module = file_path.replace("/", ".").removesuffix(".py")

            for imp in imports:
                # Determine if internal or external
                if imp.startswith("."):
                    # Relative import
                    if module not in internal_deps:
                        internal_deps[module] = set()
                    internal_deps[module].add(imp)
                elif any(root in imp for root in ["src", project_path.split("/")[-1] if project_path else ""]):
                    # Internal import
                    if module not in internal_deps:
                        internal_deps[module] = set()
                    internal_deps[module].add(imp)
                else:
                    # External import
                    if module not in external_deps:
                        external_deps[module] = set()
                    external_deps[module].add(imp)

        lines = [f"Dependency graph for {project_path}:", ""]

        # Internal dependencies
        if internal_deps:
            lines.append("Internal imports:")
            for module, deps in sorted(internal_deps.items()):
                if deps:
                    lines.append(f"  {module}:")
                    for dep in sorted(deps):
                        lines.append(f"    - {dep}")

        # External dependencies (summary)
        if external_deps:
            all_external: Set[str] = set()
            for deps in external_deps.values():
                all_external.update(deps)

            lines.append("")
            lines.append(f"External dependencies ({len(all_external)} unique):")
            for dep in sorted(all_external):
                # Count how many modules use this
                count = sum(1 for deps in external_deps.values() if dep in deps)
                lines.append(f"  {dep} (used by {count} module{'s' if count > 1 else ''})")

        return {
            "content": [{"type": "text", "text": "\n".join(lines)}],
            "isError": False,
            "metadata": {
                "internal": {k: list(v) for k, v in internal_deps.items()},
                "external": list(all_external),
            },
        }

    except Exception as e:
        logger.error(f"Error getting dependency graph: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def create_dependency_graph_tool() -> MCPTool:
    """Create the dependency graph tool."""
    return MCPTool(
        name="dependency_graph",
        description="Get the dependency graph (import relationships) for a project.",
        input_schema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Path to the project",
                },
            },
            "required": ["project_path"],
        },
        handler=get_dependency_graph,
    )


# =============================================================================
# GET ALL INDEX TOOLS
# =============================================================================


def get_index_tools() -> List[MCPTool]:
    """Get all code indexing tool definitions."""
    return [
        create_code_index_build_tool(),
        create_find_definition_tool(),
        create_find_references_tool(),
        create_call_graph_tool(),
        create_dependency_graph_tool(),
    ]
