"""Tests for credential resolution and storage."""

from __future__ import annotations

from pathlib import Path

import pytest

import memstack_cli.auth as auth_mod
from memstack_cli.auth import (
    AuthError,
    clear_credentials,
    load_refresh_token,
    resolve_api_key,
    save_api_key,
    save_login_session,
)


class TestResolveApiKey:
    def test_flag_beats_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MEMSTACK_API_KEY", "from_env")
        assert resolve_api_key("from_flag") == "from_flag"

    def test_env_beats_file(
        self, monkeypatch: pytest.MonkeyPatch, isolated_home: Path
    ) -> None:
        save_api_key("from_file")
        monkeypatch.setenv("MEMSTACK_API_KEY", "from_env")
        assert resolve_api_key(None) == "from_env"

    def test_file_used_last(self, isolated_home: Path) -> None:
        save_api_key("  ms_sk_stored  \n")
        assert resolve_api_key(None) == "ms_sk_stored"

    def test_no_credentials_raises(self) -> None:
        with pytest.raises(AuthError):
            resolve_api_key(None)

    def test_flag_whitespace_stripped(self) -> None:
        assert resolve_api_key("  hello  ") == "hello"


class TestSaveAndClear:
    def test_save_creates_file_and_restricts_perms(self, isolated_home: Path) -> None:
        path = save_api_key("ms_sk_x")
        assert path == auth_mod.CREDENTIALS_FILE
        assert path.read_text(encoding="utf-8").strip() == "ms_sk_x"
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_clear_credentials_noop_when_missing(self) -> None:
        assert clear_credentials() is False

    def test_clear_credentials_removes_file(self, isolated_home: Path) -> None:
        save_api_key("ms_sk_x")
        assert auth_mod.CREDENTIALS_FILE.exists()
        assert clear_credentials() is True
        assert not auth_mod.CREDENTIALS_FILE.exists()

    def test_save_overwrites_existing(self, isolated_home: Path) -> None:
        save_api_key("old")
        save_api_key("new")
        assert auth_mod.CREDENTIALS_FILE.read_text().strip() == "new"

    def test_login_session_stores_refresh_separately(self, isolated_home: Path) -> None:
        save_login_session("ms_sk_access", "ms_rt_refresh")
        assert resolve_api_key(None) == "ms_sk_access"
        assert load_refresh_token() == "ms_rt_refresh"
        mode = (auth_mod.CREDENTIALS_DIR / "refresh").stat().st_mode & 0o777
        assert mode == 0o600
        assert clear_credentials() is True
        assert load_refresh_token() is None
