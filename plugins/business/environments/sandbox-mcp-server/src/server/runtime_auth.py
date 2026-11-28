"""Private runtime authentication shared by KasmVNC and ttyd."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SERVICE_AUTH_USERNAME = "sandbox"


def get_runtime_service_credentials() -> tuple[str, str]:
    """Return the per-sandbox interactive credential or fail closed."""
    token = os.getenv("SANDBOX_SERVICE_AUTH_TOKEN") or os.getenv("MCP_STATIC_TOKEN")
    if not token:
        raise RuntimeError("Interactive services require a runtime authentication capability")
    return SERVICE_AUTH_USERNAME, token


def write_kasm_password_file(path: Path, username: str, token: str) -> None:
    """Create KasmVNC's hashed password file without shell interpolation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["vncpasswd", "-u", username, "-w", str(path)],
        input=f"{token}\n{token}\n",
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not path.is_file():
        raise RuntimeError("KasmVNC credential generation failed")
    path.chmod(0o600)
