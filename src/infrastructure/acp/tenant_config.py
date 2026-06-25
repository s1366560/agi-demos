"""Tenant ACP external-agent runtime configuration helpers."""

from __future__ import annotations

from typing import Any, cast

from src.infrastructure.acp.client import ExternalACPAgentConfig
from src.infrastructure.adapters.secondary.persistence.models import ACPExternalAgentConfigModel
from src.infrastructure.security.encryption_service import get_encryption_service


def decrypt_stored_config_values(
    raw_values: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    """Split stored ACP env/header config into env refs and decrypted values."""
    env_refs: dict[str, str] = {}
    secrets: dict[str, str] = {}
    encryption_service = get_encryption_service()
    for name, raw_value in raw_values.items():
        if not isinstance(raw_value, dict):
            continue
        value_type = raw_value.get("type")
        stored_value = raw_value.get("value")
        if not isinstance(stored_value, str) or not stored_value:
            continue
        if value_type == "env_ref":
            env_refs[name] = stored_value
        elif value_type == "secret":
            secrets[name] = encryption_service.decrypt(stored_value)
    return env_refs, secrets


def runtime_config_from_row(row: ACPExternalAgentConfigModel) -> ExternalACPAgentConfig:
    """Build an executable external ACP config from a tenant DB row."""
    env_refs, env_values = decrypt_stored_config_values(row.env or {})
    header_refs, header_values = decrypt_stored_config_values(row.headers or {})
    return ExternalACPAgentConfig(
        id=row.agent_key,
        name=row.name,
        transport=cast(Any, row.transport),
        command=row.command,
        args=list(row.args or []),
        url=row.url,
        env=env_refs,
        headers_env=header_refs,
        env_values=env_values,
        headers=header_values,
        enabled=row.enabled,
        source="tenant",
    )
