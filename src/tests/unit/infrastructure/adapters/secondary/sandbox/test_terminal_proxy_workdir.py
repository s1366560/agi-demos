"""Terminal startup survives an unavailable container working directory."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.infrastructure.adapters.secondary.sandbox import terminal_proxy


@pytest.mark.unit
@pytest.mark.parametrize("available", [True, False])
async def test_terminal_bootstrap_preserves_or_recovers_workdir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, available: bool
) -> None:
    import asyncio

    # Include shell syntax in the path: it must stay data, never executable code.
    workspace = tmp_path / "workspace $(exit 9)"
    if available:
        workspace.mkdir()
    shell = tmp_path / "report-cwd"
    shell.write_text("#!/bin/sh\npwd -P\n")
    shell.chmod(0o700)
    api = MagicMock()
    api.exec_create.return_value = {"Id": "test-exec"}
    container = SimpleNamespace(
        id="test-container",
        attrs={"Config": {"WorkingDir": str(workspace)}},
        client=SimpleNamespace(api=api),
    )
    docker = MagicMock()
    docker.containers.get.return_value = container
    monkeypatch.setattr(terminal_proxy, "from_env", lambda: docker)

    await terminal_proxy.TerminalProxy().create_session("test-container", shell=str(shell))

    args, kwargs = api.exec_create.call_args
    assert kwargs["workdir"] == "/"
    process = await asyncio.create_subprocess_exec(
        *args[1],
        cwd=kwargs["workdir"],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0
    expected = str(workspace.resolve()) if available else "/"
    assert stdout.decode().strip() == expected
    assert bool(stderr) is not available
