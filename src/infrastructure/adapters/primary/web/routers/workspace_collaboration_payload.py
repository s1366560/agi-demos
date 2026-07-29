"""Strict payload helpers shared by Workspace Collaboration dispatchers."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel


def workspace_payload_model[PayloadModel: BaseModel](
    model_type: type[PayloadModel],
    payload: Mapping[str, object],
    *,
    excluded: tuple[str, ...] = (),
) -> PayloadModel:
    """Validate a body without silently accepting path or unknown fields."""
    body = dict(payload)
    for key in excluded:
        workspace_payload_id(payload, key)
        body.pop(key, None)
    unknown = set(body).difference(model_type.model_fields)
    if unknown:
        raise ValueError("payload contains unsupported fields")
    return model_type.model_validate(body)


def workspace_payload_id(payload: Mapping[str, object], name: str) -> str:
    """Read one bounded non-empty path identifier."""
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"{name} is invalid")
    return value


def require_workspace_payload_keys(
    payload: Mapping[str, object],
    allowed: set[str],
) -> None:
    """Reject unexpected fields for path-only commands."""
    if set(payload).difference(allowed):
        raise ValueError("payload contains unsupported fields")
