"""Encrypted marketplace configuration, opened only at the sandbox boundary."""

from __future__ import annotations

import re
from typing import Any

from src.configuration.config import get_settings
from src.infrastructure.security.encryption_service import get_encryption_service

PREFIX = "memstack-sealed-v1:"
PLACEHOLDER = re.compile(r"\$\{(?:user_config\.|env\.)?([A-Za-z_][A-Za-z0-9_]*)\}")


def seal(value: str) -> str:
    """Require a durable application key; never persist using a transient dev key."""
    key = get_settings().llm_encryption_key
    try:
        valid = key is not None and len(bytes.fromhex(key)) == 32
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Configure LLM_ENCRYPTION_KEY before saving plugin credentials")
    return PREFIX + get_encryption_service().encrypt(value)


def open_transport(value: Any) -> Any:  # noqa: ANN401
    """Resolve sealed leaf values only when sending configuration to a sandbox."""
    if isinstance(value, str) and value.startswith(PREFIX):
        return get_encryption_service().decrypt(value[len(PREFIX) :])
    if isinstance(value, list):
        return [open_transport(item) for item in value]
    if isinstance(value, dict):
        return {key: open_transport(item) for key, item in value.items()}
    return value


def configure_transport(value: Any, credentials: dict[str, str]) -> Any:  # noqa: ANN401
    """Resolve declared placeholders and encrypt every resulting secret-bearing leaf."""
    if isinstance(value, str):
        matches = list(PLACEHOLDER.finditer(value))
        if not matches:
            return value
        if any(match[1] not in credentials for match in matches):
            raise ValueError("Plugin requires additional credential configuration")
        plaintext = PLACEHOLDER.sub(lambda match: open_transport(credentials[match[1]]), value)
        return seal(plaintext)
    if isinstance(value, list):
        return [configure_transport(item, credentials) for item in value]
    if isinstance(value, dict):
        return {key: configure_transport(item, credentials) for key, item in value.items()}
    return value
