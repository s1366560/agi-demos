"""Managed MCP children receive process essentials and explicitly granted variables."""

import os

_PROCESS_ENV = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "SystemRoot",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XDG_RUNTIME_DIR",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)


def worker_environment() -> dict[str, str]:
    return {name: os.environ[name] for name in _PROCESS_ENV if name in os.environ}
