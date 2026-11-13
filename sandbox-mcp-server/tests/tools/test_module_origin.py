"""Duplicate pkg layouts resolve to the file that was requested."""

from __future__ import annotations

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
