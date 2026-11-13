"""Duplicate pkg layouts resolve to the file that was requested."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from src.tools.test_tools import _module_import_data, module_origin_for


def _write(path: Path, text: str = "value = 1\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_src_pkg_does_not_import_the_sibling_copy(tmp_path: Path) -> None:
    sibling = tmp_path / "pkg" / "service.py"
    requested = tmp_path / "src" / "pkg" / "service.py"
    _write(sibling, "value = 'sibling'\n")
    _write(requested, "value = 'requested'\n")

    module_name, import_root = _module_import_data(requested, str(tmp_path))
    origin = module_origin_for(module_name, import_root)

    assert module_name == "pkg.service"
    assert import_root == tmp_path / "src"
    assert origin.resolve() == requested.resolve()
    assert sibling.exists()


def test_single_src_layout_keeps_the_src_package_name(tmp_path: Path) -> None:
    requested = tmp_path / "src" / "pkg" / "service.py"
    _write(requested)

    module_name, import_root = _module_import_data(requested, str(tmp_path))
    origin = module_origin_for(module_name, import_root)

    assert module_name == "src.pkg.service"
    assert import_root == tmp_path
    assert origin.resolve() == requested.resolve()


def _execute_import(module_name: str, import_root: Path) -> tuple[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(import_root)
    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name} as module; print(module.__file__); print(module.value)"],
        cwd=import_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    origin, value = result.stdout.splitlines()
    return origin, value


def test_executed_import_follows_the_requested_file(tmp_path: Path) -> None:
    sibling = tmp_path / "pkg" / "service.py"
    requested = tmp_path / "src" / "pkg" / "service.py"
    _write(sibling, "value = 'sibling'\n")
    _write(requested, "value = 'requested'\n")
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")

    module_name, import_root = _module_import_data(requested, str(tmp_path))
    origin, value = _execute_import(module_name, import_root)

    assert Path(origin).resolve() == requested.resolve()
    assert value == "requested"


def test_executed_import_of_only_src_pkg_uses_src_prefix(tmp_path: Path) -> None:
    requested = tmp_path / "src" / "pkg" / "service.py"
    _write(requested, "value = 'only'\n")
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")

    module_name, import_root = _module_import_data(requested, str(tmp_path))
    origin, value = _execute_import(module_name, import_root)

    assert module_name == "src.pkg.service"
    assert Path(origin).resolve() == requested.resolve()
    assert value == "only"
