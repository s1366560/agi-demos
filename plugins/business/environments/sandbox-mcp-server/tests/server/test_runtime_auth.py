"""Tests for private desktop and terminal runtime authentication."""

from unittest.mock import MagicMock, patch

import pytest

from src.server.runtime_auth import (
    get_runtime_service_credentials,
    write_kasm_password_file,
)


def test_runtime_service_credentials_prefer_dedicated_capability(monkeypatch) -> None:
    monkeypatch.setenv("MCP_STATIC_TOKEN", "mcp-capability")
    monkeypatch.setenv("SANDBOX_SERVICE_AUTH_TOKEN", "interactive-capability")

    assert get_runtime_service_credentials() == ("sandbox", "interactive-capability")


def test_runtime_service_credentials_fail_closed_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("MCP_STATIC_TOKEN", raising=False)
    monkeypatch.delenv("SANDBOX_SERVICE_AUTH_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="runtime authentication capability"):
        get_runtime_service_credentials()


@patch("src.server.runtime_auth.subprocess.run")
def test_write_kasm_password_file_uses_vncpasswd_without_plaintext_file_write(
    run: MagicMock,
    tmp_path,
) -> None:
    password_path = tmp_path / ".kasmpasswd"

    def create_hashed_password_file(*_args, **_kwargs):
        password_path.write_text("sandbox:hashed-value:ow", encoding="utf-8")
        return MagicMock(returncode=0)

    run.side_effect = create_hashed_password_file

    write_kasm_password_file(password_path, "sandbox", "private-capability")

    run.assert_called_once_with(
        ["vncpasswd", "-u", "sandbox", "-w", str(password_path)],
        input="private-capability\nprivate-capability\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert "private-capability" not in password_path.read_text(encoding="utf-8")
