"""AST parsing tools for MCP server.

Provides Python AST parsing capabilities for code understanding.
"""

import ast
import logging
import re
from typing import Any, Dict, List, Optional

from src.server.websocket_server import MCPTool
from src.tools.file_tools import _error_result, _path_metadata, _resolve_path, _success_result

logger = logging.getLogger(__name__)


# =============================================================================
# AST PARSE TOOL
# =============================================================================


async def ast_parse(
    file_path: str,
    include_docstrings: bool = True,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Parse a Python file and return its AST structure.

    Args:
        file_path: Path to the Python file
        include_docstrings: Include docstrings in output
        _workspace_dir: Workspace directory

    Returns:
        AST structure with symbols metadata
    """
    try:
        full_path = _resolve_path(file_path, _workspace_dir, allow_extra_paths=True)
        path_metadata = _path_metadata(full_path, _workspace_dir)

        if not full_path.exists():
            return _error_result(
                f"File not found: {file_path}",
                code="file_not_found",
                hint="Pass a Python file inside the workspace or an allowlisted read-only path.",
                metadata={"requested_path": file_path, **path_metadata},
            )

        if not full_path.is_file():
            return _error_result(
                f"Not a file: {file_path}",
                code="not_a_file",
                hint="AST parsing requires a concrete Python source file.",
                metadata={"requested_path": file_path, **path_metadata},
            )

        content = full_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(full_path))

        # Extract symbols
        symbols = {
            "classes": [],
            "functions": [],
            "imports": [],
            "variables": [],
        }

        # Track parent context
        parent_stack = []

        class SymbolVisitor(ast.NodeVisitor):
            """AST visitor to extract symbol information."""

            def __init__(self, include_docstrings: bool = True):
                self.include_docstrings = include_docstrings
                self.symbols = symbols
                self.parent_stack = parent_stack

            def get_parent(self) -> Optional[str]:
                """Get current parent context name."""
                if self.parent_stack:
                    return self.parent_stack[-1]
                return None

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                """Visit class definition."""
                parent = self.get_parent()

                class_info = {
                    "name": node.name,
                    "lineno": node.lineno,
                    "end_lineno": node.end_lineno,
                    "type": "class",
                    "parent": parent,
                }

                # Get base classes
                if node.bases:
                    bases = []
                    for base in node.bases:
                        if isinstance(base, ast.Name):
                            bases.append(base.id)
                        elif isinstance(base, ast.Attribute):
                            bases.append(ast.unparse(base))
                    class_info["bases"] = bases

                # Get decorators
                if node.decorator_list:
                    class_info["decorators"] = [
                        ast.unparse(d) for d in node.decorator_list
                    ]

                if self.include_docstrings:
                    class_info["docstring"] = ast.get_docstring(node)

                # Get methods
                methods = []
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        methods.append({
                            "name": item.name,
                            "lineno": item.lineno,
                            "args": [a.arg for a in item.args.args],
                        })
                    elif isinstance(item, ast.AsyncFunctionDef):
                        methods.append({
                            "name": item.name,
                            "lineno": item.lineno,
                            "async": True,
                            "args": [a.arg for a in item.args.args],
                        })
                class_info["methods"] = methods

                self.symbols["classes"].append(class_info)

                self.parent_stack.append(node.name)
                self.generic_visit(node)
                self.parent_stack.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                """Visit function definition."""
                if self.get_parent() is None:  # Top-level function only
                    func_info = {
                        "name": node.name,
                        "lineno": node.lineno,
                        "end_lineno": node.end_lineno,
                        "type": "function",
                        "args": [a.arg for a in node.args.args],
                        "returns": ast.unparse(node.returns) if node.returns else None,
                    }

                    # Get decorators
                    if node.decorator_list:
                        func_info["decorators"] = [
                            ast.unparse(d) for d in node.decorator_list
                        ]

                    # Get default values
                    defaults = []
                    for default in node.args.defaults:
                        defaults.append(ast.unparse(default))
                    if defaults:
                        func_info["defaults"] = defaults

                    if self.include_docstrings:
                        func_info["docstring"] = ast.get_docstring(node)

                    self.symbols["functions"].append(func_info)

                self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                """Visit async function definition."""
                if self.get_parent() is None:  # Top-level function only
                    func_info = {
                        "name": node.name,
                        "lineno": node.lineno,
                        "end_lineno": node.end_lineno,
                        "type": "async_function",
                        "args": [a.arg for a in node.args.args],
                        "returns": ast.unparse(node.returns) if node.returns else None,
                        "async": True,
                    }

                    if self.include_docstrings:
                        func_info["docstring"] = ast.get_docstring(node)

                    self.symbols["functions"].append(func_info)

                self.generic_visit(node)

            def visit_Import(self, node: ast.Import) -> None:
                """Visit import statement."""
                for alias in node.names:
                    import_info = {
                        "module": alias.name,
                        "alias": alias.asname,
                        "lineno": node.lineno,
                        "type": "import",
                    }
                    self.symbols["imports"].append(import_info)
                self.generic_visit(node)

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                """Visit from...import statement."""
                names = []
                for alias in node.names:
                    name_str = alias.name
                    if alias.asname:
                        name_str += f" as {alias.asname}"
                    names.append(name_str)

                import_info = {
                    "module": node.module or "",
                    "names": names,
                    "level": node.level,
                    "lineno": node.lineno,
                    "type": "import_from",
                }
                self.symbols["imports"].append(import_info)

        visitor = SymbolVisitor(include_docstrings=include_docstrings)
        visitor.visit(tree)

        # Build output
        lines = []
        lines.append(f"AST parse result for {file_path}")
        lines.append("")

        if symbols["classes"]:
            lines.append(f"Classes ({len(symbols['classes'])}):")
            for cls in symbols["classes"]:
                bases = f"({', '.join(cls.get('bases', []))})" if cls.get('bases') else ""
                lines.append(f"  {cls['lineno']}: class {cls['name']}{bases}")
                if cls.get("methods"):
                    for method in cls["methods"]:
                        async_prefix = "async " if method.get("async") else ""
                        lines.append(f"    - {async_prefix}def {method['name']}({', '.join(method['args'])})")

        if symbols["functions"]:
            lines.append("")
            lines.append(f"Functions ({len(symbols['functions'])}):")
            for func in symbols["functions"]:
                async_prefix = "async " if func.get("async") else ""
                lines.append(f"  {func['lineno']}: {async_prefix}def {func['name']}({', '.join(func['args'])})")

        if symbols["imports"]:
            lines.append("")
            lines.append(f"Imports ({len(symbols['imports'])}):")
            for imp in symbols["imports"]:
                if imp["type"] == "import":
                    alias = f" as {imp['alias']}" if imp['alias'] else ""
                    lines.append(f"  {imp['lineno']}: import {imp['module']}{alias}")
                else:
                    lines.append(f"  {imp['lineno']}: from {imp['module']} import {', '.join(imp['names'])}")

        return _success_result(
            "\n".join(lines),
            metadata={
                "file_path": file_path,
                "symbols": symbols,
                "total_symbols": sum(len(v) for v in symbols.values()),
                **path_metadata,
            },
        )

    except SyntaxError as e:
        return _error_result(
            f"Syntax error at line {e.lineno}: {e.msg}",
            code="syntax_error",
            hint="Fix the Python syntax before using AST tools on this file.",
            metadata={"error_type": "SyntaxError", "lineno": e.lineno, "file_path": file_path},
        )
    except ValueError as e:
        return _error_result(
            str(e),
            code="path_outside_workspace",
            hint="AST tools are limited to the workspace or allowlisted read-only directories.",
            metadata={"requested_path": file_path},
        )
    except Exception as e:
        logger.error(f"Error parsing AST: {e}", exc_info=True)
        return _error_result(
            str(e),
            code="ast_parse_failed",
            metadata={"requested_path": file_path},
        )


def create_ast_parse_tool() -> MCPTool:
    """Create the AST parse tool."""
    return MCPTool(
        name="ast_parse",
        description="Parse a Python file and extract its AST structure including classes, functions, methods, and imports.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Python file to parse",
                },
                "include_docstrings": {
                    "type": "boolean",
                    "description": "Include docstrings in output",
                    "default": True,
                },
            },
            "required": ["file_path"],
        },
        handler=ast_parse,
    )


# =============================================================================
# AST FIND SYMBOLS TOOL
# =============================================================================


async def ast_find_symbols(
    file_path: str,
    symbol_type: str,
    pattern: Optional[str] = None,
    case_sensitive: bool = True,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Find symbols in a Python file.

    Args:
        file_path: Path to the Python file
        symbol_type: Type of symbol (class, function, import, all)
        pattern: Optional regex pattern to filter symbol names
        case_sensitive: Whether pattern matching is case sensitive
        _workspace_dir: Workspace directory

    Returns:
        List of matching symbols
    """
    result = await ast_parse(
        file_path=file_path,
        include_docstrings=False,
        _workspace_dir=_workspace_dir,
    )

    if result.get("isError"):
        return result

    symbols = result["metadata"]["symbols"]
    matches = []

    if symbol_type == "class":
        matches = symbols["classes"]
    elif symbol_type == "function":
        matches = symbols["functions"]
    elif symbol_type == "import":
        matches = symbols["imports"]
    elif symbol_type == "all":
        matches = (
            symbols["classes"] + symbols["functions"] + symbols["imports"]
        )
    else:
        return _error_result(
            f"Invalid symbol_type: {symbol_type}",
            code="invalid_symbol_type",
            hint="Use one of: class, function, import, all.",
            metadata={"symbol_type": symbol_type},
        )

    # Filter by pattern if provided
    if pattern:
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(pattern, flags)
            matches = [m for m in matches if regex.search(m.get("name", ""))]
        except re.error as e:
            return _error_result(
                f"Invalid regex pattern: {e}",
                code="invalid_regex",
                hint="Provide a valid Python regular expression.",
                metadata={"pattern": pattern},
            )

    # Format output
    lines = []
    for m in matches:
        if m.get("type") in ["class", "function", "async_function"]:
            type_label = m["type"]
            name = m["name"]
            lineno = m["lineno"]
            if m.get("parent"):
                lines.append(f"{lineno}: {m['parent']}.{name} ({type_label})")
            else:
                lines.append(f"{lineno}: {name} ({type_label})")
        elif m.get("type") in {"import", "import_from"}:
            if m["type"] == "import":
                alias = f" as {m['alias']}" if m['alias'] else ""
                lines.append(f"{m['lineno']}: import {m['module']}{alias}")
            else:
                lines.append(f"{m['lineno']}: from {m['module']} import {', '.join(m['names'])}")

    if not lines:
        return _success_result(
            f"No {symbol_type} symbols found",
            metadata={"matches": [], "count": 0},
        )

    return _success_result(
        "\n".join(lines),
        metadata={"matches": matches, "count": len(matches)},
    )


def create_ast_find_symbols_tool() -> MCPTool:
    """Create the find symbols tool."""
    return MCPTool(
        name="ast_find_symbols",
        description="Find symbols (classes, functions, imports) in a Python file, with optional regex filtering.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Python file",
                },
                "symbol_type": {
                    "type": "string",
                    "enum": ["class", "function", "import", "all"],
                    "description": "Type of symbol to find",
                },
                "pattern": {
                    "type": "string",
                    "description": "Optional regex pattern to filter symbol names",
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Whether pattern matching is case sensitive",
                    "default": True,
                },
            },
            "required": ["file_path", "symbol_type"],
        },
        handler=ast_find_symbols,
    )


# =============================================================================
# AST EXTRACT FUNCTION TOOL
# =============================================================================


async def ast_extract_function(
    file_path: str,
    function_name: str,
    class_name: Optional[str] = None,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Extract a function's source code from a Python file.

    Args:
        file_path: Path to the Python file
        function_name: Name of the function to extract
        class_name: Optional class name if function is a method
        _workspace_dir: Workspace directory

    Returns:
        Function source code and metadata
    """
    try:
        full_path = _resolve_path(file_path, _workspace_dir, allow_extra_paths=True)
        path_metadata = _path_metadata(full_path, _workspace_dir)

        if not full_path.exists():
            return _error_result(
                f"File not found: {file_path}",
                code="file_not_found",
                hint="Pass a Python file inside the workspace or an allowlisted read-only path.",
                metadata={"requested_path": file_path, **path_metadata},
            )

        content = full_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(full_path))

        class FunctionFinder(ast.NodeVisitor):
            """Find and extract function source."""

            def __init__(self, target_name: str, target_class: Optional[str] = None):
                self.target_name = target_name
                self.target_class = target_class
                self.result = None
                self.class_stack = []

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                self.class_stack.append(node.name)
                self.generic_visit(node)
                self.class_stack.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                if node.name == self.target_name:
                    current_class = self.class_stack[-1] if self.class_stack else None
                    if self.target_class is None or current_class == self.target_class:
                        # Found the function
                        self.result = {
                            "name": node.name,
                            "lineno": node.lineno,
                            "end_lineno": node.end_lineno,
                            "is_async": False,
                            "args": [a.arg for a in node.args.args],
                            "returns": ast.unparse(node.returns) if node.returns else None,
                            "docstring": ast.get_docstring(node),
                            "class": current_class,
                        }
                self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                if node.name == self.target_name:
                    current_class = self.class_stack[-1] if self.class_stack else None
                    if self.target_class is None or current_class == self.target_class:
                        self.result = {
                            "name": node.name,
                            "lineno": node.lineno,
                            "end_lineno": node.end_lineno,
                            "is_async": True,
                            "args": [a.arg for a in node.args.args],
                            "returns": ast.unparse(node.returns) if node.returns else None,
                            "docstring": ast.get_docstring(node),
                            "class": current_class,
                        }
                self.generic_visit(node)

        finder = FunctionFinder(function_name, class_name)
        finder.visit(tree)

        if not finder.result:
            return _success_result(
                f"Function '{function_name}' not found",
                metadata={"found": False, **path_metadata},
            )

        # Extract source lines
        lines = content.splitlines()
        start = finder.result["lineno"] - 1
        end = finder.result.get("end_lineno", finder.result["lineno"])
        source_lines = lines[start:end]
        source = "\n".join(source_lines)

        return _success_result(
            source,
            metadata={
                "found": True,
                **finder.result,
                **path_metadata,
            },
        )

    except SyntaxError as e:
        return _error_result(
            f"Syntax error at line {e.lineno}: {e.msg}",
            code="syntax_error",
            hint="Fix the Python syntax before extracting function source.",
            metadata={"requested_path": file_path, "lineno": e.lineno},
        )
    except ValueError as e:
        return _error_result(
            str(e),
            code="path_outside_workspace",
            hint="AST tools are limited to the workspace or allowlisted read-only directories.",
            metadata={"requested_path": file_path},
        )
    except Exception as e:
        logger.error(f"Error extracting function: {e}", exc_info=True)
        return _error_result(
            str(e),
            code="ast_extract_failed",
            metadata={"requested_path": file_path},
        )


def create_ast_extract_function_tool() -> MCPTool:
    """Create the extract function tool."""
    return MCPTool(
        name="ast_extract_function",
        description="Extract a function's source code from a Python file. Can extract top-level functions or class methods.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Python file",
                },
                "function_name": {
                    "type": "string",
                    "description": "Name of the function to extract",
                },
                "class_name": {
                    "type": "string",
                    "description": "Optional class name if extracting a method",
                },
            },
            "required": ["file_path", "function_name"],
        },
        handler=ast_extract_function,
    )


# =============================================================================
# AST GET IMPORTS TOOL
# =============================================================================


async def ast_get_imports(
    file_path: str,
    group_by_module: bool = False,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Get all imports from a Python file.

    Args:
        file_path: Path to the Python file
        group_by_module: Group imports by module
        _workspace_dir: Workspace directory

    Returns:
        List of imports
    """
    result = await ast_parse(
        file_path=file_path,
        include_docstrings=False,
        _workspace_dir=_workspace_dir,
    )

    if result.get("isError"):
        return result

    imports = result["metadata"]["symbols"]["imports"]

    if group_by_module:
        # Group by module
        grouped: Dict[str, List[Dict]] = {}
        for imp in imports:
            module = imp.get("module", "") or "<relative>"
            if module not in grouped:
                grouped[module] = []
            grouped[module].append(imp)

        lines = []
        for module, imps in sorted(grouped.items()):
            lines.append(f"{module}:")
            for imp in imps:
                if imp.get("type") == "import":
                    alias = f" as {imp['alias']}" if imp['alias'] else ""
                    lines.append(f"  - import {imp['module']}{alias}")
                else:
                    lines.append(f"  - from {imp['module']} import {', '.join(imp['names'])}")

        return _success_result(
            "\n".join(lines),
            metadata={"imports": imports, "grouped": grouped, "count": len(imports)},
        )

    # Flat list
    lines = [f"{imp['lineno']}: {imp['module']}" for imp in imports]

    return _success_result(
        "\n".join(lines),
        metadata={"imports": imports, "count": len(imports)},
    )


def create_ast_get_imports_tool() -> MCPTool:
    """Create the get imports tool."""
    return MCPTool(
        name="ast_get_imports",
        description="Get all import statements from a Python file, optionally grouped by module.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Python file",
                },
                "group_by_module": {
                    "type": "boolean",
                    "description": "Group imports by module",
                    "default": False,
                },
            },
            "required": ["file_path"],
        },
        handler=ast_get_imports,
    )


# =============================================================================
# GET ALL AST TOOLS
# =============================================================================


def get_ast_tools() -> List[MCPTool]:
    """Get all AST tool definitions."""
    return [
        create_ast_parse_tool(),
        create_ast_find_symbols_tool(),
        create_ast_extract_function_tool(),
        create_ast_get_imports_tool(),
    ]
