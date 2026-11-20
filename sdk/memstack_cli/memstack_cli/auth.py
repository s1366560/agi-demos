"""Credential storage and API key resolution.

Auth precedence (first hit wins):
    1. --api-key flag
    2. MEMSTACK_API_KEY env var
    3. ~/.memstack/credentials   (file, single line: ms_sk_...)
"""

from __future__ import annotations

import contextlib
import os
import stat
from pathlib import Path

CREDENTIALS_DIR = Path.home() / ".memstack"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials"


def _refresh_file() -> Path:
    return CREDENTIALS_DIR / "refresh"


class AuthError(RuntimeError):
    """Raised when no credentials can be resolved."""


def resolve_api_key(flag_value: str | None) -> str:
    """Resolve an API key using flag > env > file.

    Raises AuthError if nothing is found.
    """
    if flag_value:
        return flag_value.strip()
    env = os.environ.get("MEMSTACK_API_KEY")
    if env:
        return env.strip()
    if CREDENTIALS_FILE.exists():
        text = CREDENTIALS_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text
    raise AuthError(
        "No API key configured. Run `memstack login`, set MEMSTACK_API_KEY, "
        "or pass --api-key."
    )


def save_api_key(api_key: str) -> Path:
    """Persist an API key to ~/.memstack/credentials with 0600 perms.

    Returns the credentials file path.
    """
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(CREDENTIALS_DIR, stat.S_IRWXU)
    CREDENTIALS_FILE.write_text(api_key.strip() + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(CREDENTIALS_FILE, stat.S_IRUSR | stat.S_IWUSR)
    return CREDENTIALS_FILE


def save_login_session(access_token: str, refresh_token: str | None = None) -> Path:
    """Persist an access token and, when issued, its rotating refresh token.

    The access token stays in the historical one-line credentials file so
    existing readers keep working. The refresh token is a separate 0600 file.
    """
    path = save_api_key(access_token)
    refresh_file = _refresh_file()
    if refresh_token and refresh_token.strip():
        refresh_file.write_text(refresh_token.strip() + "\n", encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(refresh_file, stat.S_IRUSR | stat.S_IWUSR)
    elif refresh_file.exists():
        refresh_file.unlink()
    return path


def load_refresh_token() -> str | None:
    """Return the stored refresh token, if this login issued one."""
    refresh_file = _refresh_file()
    if not refresh_file.exists():
        return None
    text = refresh_file.read_text(encoding="utf-8").strip()
    return text or None


def clear_credentials() -> bool:
    """Remove stored credentials; returns True if a file was deleted."""
    removed = False
    if CREDENTIALS_FILE.exists():
        CREDENTIALS_FILE.unlink()
        removed = True
    refresh_file = _refresh_file()
    if refresh_file.exists():
        refresh_file.unlink()
        removed = True
    return removed
