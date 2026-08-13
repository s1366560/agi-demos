#!/usr/bin/env python3
"""Fill missing local-only Workspace Core settings without exposing credentials."""

from __future__ import annotations

import argparse
import os
import secrets
import tempfile
from pathlib import Path
from urllib.parse import quote

_CREDENTIAL_KEYS = (
    "WORKSPACE_CORE_SERVICE_TOKEN",
    "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN",
    "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN",
    "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN",
    "AVERNET_SECRET_PRINCIPAL_SIGNING_KEY_VALUE",
    "BCS_SECRET_WORKSPACE_CORE_GROUP_SESSION_WS_JWT",
)


def _assignment(line: str) -> tuple[str, str] | None:
    candidate = line.strip()
    if not candidate or candidate.startswith("#") or "=" not in candidate:
        return None
    if candidate.startswith("export "):
        candidate = candidate.removeprefix("export ").lstrip()
    key, _, value = candidate.partition("=")
    key = key.strip()
    if not key or not key.replace("_", "a").isalnum():
        return None
    return key, value.strip()


def _decoded_value(raw_value: str) -> str:
    if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {'"', "'"}:
        return raw_value[1:-1]
    if raw_value.startswith("#"):
        return ""
    return raw_value


def _read_values(lines: list[str]) -> tuple[dict[str, str], dict[str, int]]:
    values: dict[str, str] = {}
    positions: dict[str, int] = {}
    for index, line in enumerate(lines):
        parsed = _assignment(line)
        if parsed is None:
            continue
        key, raw_value = parsed
        values[key] = _decoded_value(raw_value)
        positions[key] = index
    return values, positions


def _postgres_url(values: dict[str, str]) -> str:
    user = values.get("POSTGRES_USER") or "postgres"
    password = values.get("POSTGRES_PASSWORD") or "password"
    database = values.get("POSTGRES_DB") or "memstack"
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@postgres:5432/{quote(database, safe='')}"
    )


def _unique_token(used_values: set[str]) -> str:
    while True:
        token = secrets.token_urlsafe(32)
        if token not in used_values:
            used_values.add(token)
            return token


def _write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            os.chmod(temporary.fileno(), 0o600)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def bootstrap_local_env(path: Path) -> int:
    if not path.is_file():
        raise FileNotFoundError(f"Local environment file does not exist: {path}")

    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    values, positions = _read_values(lines)
    used_values = {values[key] for key in _CREDENTIAL_KEYS if values.get(key)}
    required_values = {
        "WORKSPACE_CORE_BASE_URL": "http://127.0.0.1:4319",
        "WORKSPACE_CORE_DATABASE_URL": _postgres_url(values),
    }
    for key in _CREDENTIAL_KEYS:
        required_values[key] = _unique_token(used_values)

    changed_keys: list[str] = []
    for key, generated_value in required_values.items():
        if values.get(key):
            continue
        replacement = f"{key}={generated_value}"
        if key in positions:
            lines[positions[key]] = replacement
        else:
            lines.append(replacement)
        changed_keys.append(key)

    if changed_keys:
        content = "\n".join(lines).rstrip("\n") + "\n"
        _write_private(path, content)
    else:
        os.chmod(path, 0o600)

    print(f"Workspace Core local configuration is ready ({len(changed_keys)} values added).")
    return len(changed_keys)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    bootstrap_local_env(args.env_file)


if __name__ == "__main__":
    main()
