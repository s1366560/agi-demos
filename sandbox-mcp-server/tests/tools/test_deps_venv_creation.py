"""venv creation failures stay distinct from an unwritable prefix."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from src.tools import deps_tools
from src.tools.deps_tools import classify_venv_creation_failure, deps_install


def test_missing_ensurepip_is_not_a_permission_failure() -> None:
    message = classify_venv_creation_failure(
        "The virtual environment was not created successfully because ensurepip is not available."
    )
    assert message.startswith("venv_creation_failed:")
    assert "not a sandbox write-permission failure" in message
    assert not message.startswith("environment_not_writable:")


def test_venv_permission_denied_stays_environment_not_writable() -> None:
    message = classify_venv_creation_failure(
        "Error: [Errno 13] Permission denied: '/opt/sandbox-mcp-venv'"
    )
    assert message.startswith("environment_not_writable:")
    assert "Errno 13" in message


@pytest.mark.asyncio
async def test_failed_venv_creation_returns_before_pip_and_removes_partial_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    partial = tmp_path / ".deps-venv"
    partial.mkdir()
    (partial / "pyvenv.cfg").write_text("incomplete\n", encoding="utf-8")

    async def fail_venv(cmd: str, cwd: str, timeout: int, env=None):
        assert "python3 -m venv" in cmd
        Path(cwd, ".deps-venv").mkdir(exist_ok=True)
        return "", "ensurepip is not available", 1

    monkeypatch.setattr(deps_tools, "_run_subprocess", fail_venv)
    monkeypatch.setattr(deps_tools, "interpreter_prefix_writable", lambda prefix=None: False)
    result = await deps_install("fixture.whl", _workspace_dir=str(tmp_path))
    text = result["content"][0]["text"]
    assert result["isError"] is True
    assert text.startswith("Error: venv_creation_failed:")
    assert "ensurepip" in text
    assert "bin/pip" not in text
    assert result["metadata"]["venv_creation"] == "failed"
    assert result["metadata"]["install_scope"] == "workspace_venv"
    assert not partial.exists()


@pytest.mark.asyncio
async def test_explicit_readonly_venv_is_classified_and_left_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "locked-venv"
    target.mkdir()
    target.chmod(stat.S_IREAD | stat.S_IEXEC)

    async def deny(cmd: str, cwd: str, timeout: int, env=None):
        return "", "Error: [Errno 13] Permission denied: " + str(target), 1

    monkeypatch.setattr(deps_tools, "_run_subprocess", deny)
    monkeypatch.setattr(deps_tools, "interpreter_prefix_writable", lambda prefix=None: False)
    try:
        result = await deps_install(
            "fixture.whl",
            venv_path=str(target),
            _workspace_dir=str(tmp_path),
        )
    finally:
        os.chmod(target, stat.S_IRWXU)
    text = result["content"][0]["text"]
    assert text.startswith("Error: environment_not_writable:")
    assert "Errno 13" in text
    assert target.exists()
