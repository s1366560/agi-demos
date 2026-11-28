"""Pip installs stay off a read-only interpreter prefix."""

from __future__ import annotations

import os

from src.tools.deps_tools import select_pip_install_target


def test_explicit_venv_is_unchanged(tmp_path) -> None:
    target, scope = select_pip_install_target(str(tmp_path), "vendor/venv", prefix_writable=False)
    assert scope == "explicit_venv"
    assert target == os.path.join(str(tmp_path), "vendor/venv")


def test_writable_prefix_keeps_the_interpreter() -> None:
    target, scope = select_pip_install_target("/workspace", None, prefix_writable=True)
    assert target is None
    assert scope == "interpreter_prefix"


def test_read_only_prefix_uses_workspace_venv_without_chmod(tmp_path) -> None:
    target, scope = select_pip_install_target(str(tmp_path), None, prefix_writable=False)
    assert scope == "workspace_venv"
    assert target == os.path.join(str(tmp_path), ".deps-venv")
    assert not os.path.exists(target)
