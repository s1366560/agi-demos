"""Every module the kernel image starts from is admitted into that image.

The image lists the sources it admits one by one. A module that an admitted
module imports, and that is not listed, is found only when the image starts.
"""

import ast
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
ADMITTED = ROOT / "Dockerfile.kernel.dockerignore"
ENTRY = "src.host.transport.package_kernel"


def admitted_patterns() -> list[str]:
    lines = ADMITTED.read_text(encoding="utf-8").splitlines()
    return [line[1:] for line in lines if line.startswith("!")]


def follows(path: str, pattern: str) -> bool:
    """Whether a path follows a pattern of the image, where ** stands for any number of parts."""

    def match(parts: list[str], rule: list[str]) -> bool:
        if not rule:
            return not parts
        if rule[0] == "**":
            return any(match(parts[taken:], rule[1:]) for taken in range(len(parts) + 1))
        return bool(parts) and fnmatchcase(parts[0], rule[0]) and match(parts[1:], rule[1:])

    return match(path.split("/"), pattern.split("/"))


def module_file(module: str, patterns: list[str]) -> str | None:
    """The repository file of a module, when the image admits it."""
    stem = module.replace(".", "/")
    for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
        if (ROOT / candidate).is_file() and any(follows(candidate, p) for p in patterns):
            return candidate
    return None


def package_in_repository(module: str) -> bool:
    stem = module.replace(".", "/")
    return (ROOT / stem / "__init__.py").is_file()


class Imports(ast.NodeVisitor):
    """Collects the modules of the application a file imports as it is loaded.

    An import inside a function runs when the function is called, and one that is
    answered by a handler runs where what it names is present; neither is read.
    """

    def __init__(self, path: str) -> None:
        self.package = path.removesuffix(".py").removesuffix("/__init__").replace("/", ".")
        self.modules: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        return

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Try(self, node: ast.Try) -> None:
        # An import that is answered when what it names is absent is not required.
        if any(
            handler.type is None
            or (isinstance(handler.type, ast.Name) and handler.type.id == "ImportError")
            or (isinstance(handler.type, ast.Attribute) and handler.type.attr == "ImportError")
            for handler in node.handlers
        ):
            return
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        # What is imported only for type checking is never imported where the kernel runs.
        test = node.test
        negated = isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
        target = test.operand if negated else test
        name = (
            target.id
            if isinstance(target, ast.Name)
            else target.attr
            if isinstance(target, ast.Attribute)
            else None
        )
        if name == "TYPE_CHECKING":
            for statement in node.orelse if not negated else node.body:
                self.visit(statement)
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.modules.update(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = node.module or ""
        if node.level:
            parts = self.package.split(".")
            if not self.package or "." not in self.package:
                raise ValueError(f"cannot place the relative imports of {self.package}")
            base = ".".join([*parts[: len(parts) - node.level + 1], base]).strip(".")
        self.modules.add(base)
        # A name imported from a package may be a module of that package.
        self.modules.update(f"{base}.{alias.name}".strip(".") for alias in node.names)


def imports_of(path: str) -> set[str]:
    """The modules of the application that a file imports, wherever in the file they run."""
    visitor = Imports(path)
    visitor.visit(ast.parse((ROOT / path).read_text(encoding="utf-8")))
    return {module for module in visitor.modules if module.startswith("src")}


def missing_from_image(patterns: list[str] | None = None) -> dict[str, set[str]]:
    """Modules of the application that the kernel reaches and the image does not admit."""
    patterns = admitted_patterns() if patterns is None else patterns
    seen: set[str] = set()
    missing: dict[str, set[str]] = {}

    def visit(path: str) -> None:
        if path in seen:
            return
        seen.add(path)
        for module in imports_of(path):
            file = module_file(module, patterns)
            if file is not None:
                visit(file)
            # A module of the application that the image leaves out is not found when
            # it is imported. A package without its initializer in the image is still a
            # package there, and a name that is not a module is something a module defines.
            elif (ROOT / f"{module.replace('.', '/')}.py").is_file() and not package_in_repository(
                module
            ):
                missing.setdefault(path, set()).add(module)

    visit(module_file(ENTRY, patterns) or "")
    return missing


@pytest.mark.unit
def test_kernel_image_admits_every_module_the_kernel_imports() -> None:
    assert missing_from_image() == {}, (
        "modules the kernel imports are not admitted into the kernel image; "
        "add them to Dockerfile.kernel.dockerignore"
    )


@pytest.mark.unit
def test_kernel_image_check_notices_a_module_left_out() -> None:
    # The check reads the list of admitted sources. Without the module that the
    # database setup imports, it names that module, and nothing else.
    without_store = [
        pattern
        for pattern in admitted_patterns()
        if not pattern.endswith("persistence/relational_store.py")
    ]
    assert len(without_store) == len(admitted_patterns()) - 1
    assert missing_from_image(without_store) == {
        "src/infrastructure/adapters/secondary/persistence/database.py": {
            "src.infrastructure.adapters.secondary.persistence.relational_store"
        }
    }
