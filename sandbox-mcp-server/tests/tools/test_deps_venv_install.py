"""A workspace venv can install a local wheel without touching the system prefix."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from src.tools.deps_tools import deps_install, local_workspace_wheel


def _wheel(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("fixturepkg/__init__.py", "value = 'installed'\n")
        archive.writestr(
            "fixturepkg-0.0.1.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: fixturepkg\nVersion: 0.0.1\n",
        )
        archive.writestr(
            "fixturepkg-0.0.1.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(
            "fixturepkg-0.0.1.dist-info/RECORD",
            "fixturepkg/__init__.py,,\nfixturepkg-0.0.1.dist-info/METADATA,,\n"
            "fixturepkg-0.0.1.dist-info/WHEEL,,\nfixturepkg-0.0.1.dist-info/RECORD,,\n",
        )


@pytest.mark.asyncio
async def test_workspace_venv_imports_local_wheel(tmp_path: Path) -> None:
    wheel = tmp_path / "fixturepkg-0.0.1-py3-none-any.whl"
    _wheel(wheel)
    venv = tmp_path / "iso"
    result = await deps_install(
        packages=wheel.name,
        package_type="pip",
        venv_path=str(venv),
        timeout=120,
        _workspace_dir=str(tmp_path),
    )
    assert result["isError"] is False, result
    assert result["metadata"]["install_scope"] == "explicit_venv"
    probe = subprocess.run(
        [str(venv / "bin" / "python"), "-c", "import fixturepkg; print(fixturepkg.value)"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "installed"
    assert sys.prefix != str(venv)


def test_wheel_outside_workspace_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-fixture.whl"
    _wheel(outside)
    try:
        assert local_workspace_wheel(str(tmp_path / "workspace"), str(outside)) is None
    finally:
        outside.unlink(missing_ok=True)


def test_failed_venv_creation_does_not_change_system_prefix(tmp_path: Path) -> None:
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("file", encoding="utf-8")
    before = os.stat(sys.prefix).st_mode
    assert local_workspace_wheel(str(tmp_path), str(blocked)) is None
    assert os.stat(sys.prefix).st_mode == before
