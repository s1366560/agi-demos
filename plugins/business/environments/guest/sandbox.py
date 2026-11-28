"""Project sandbox documents inside the guest. Private handles never leave this module."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError


def project_sandbox(
    tenant_id: str, project_id: str, value: dict[str, Any] | None
) -> dict[str, Any] | None:
    from plugins.business.environments.backend.package_sandbox_operations import _Sandbox

    if value is None:
        return None
    try:
        sandbox = _Sandbox.model_validate(value)
    except ValidationError as exc:
        raise OptionalBusinessError("runtime_unavailable", "Invalid sandbox state") from exc
    if (sandbox.tenant_id, sandbox.project_id) != (tenant_id, project_id):
        raise OptionalBusinessError("forbidden", "Sandbox scope mismatch")
    return sandbox.model_dump(exclude={"project_id", "tenant_id"}, exclude_none=True)


def project_metrics(project_id: str, sandbox_id: str, value: dict[str, Any]) -> dict[str, Any]:
    from plugins.business.environments.backend.package_sandbox_operations import _Stats

    try:
        stats = _Stats.model_validate(value)
    except ValidationError as exc:
        raise OptionalBusinessError("runtime_unavailable", "Invalid sandbox metrics") from exc
    if (stats.project_id, stats.sandbox_id) != (project_id, sandbox_id):
        raise OptionalBusinessError("forbidden", "Sandbox metrics scope mismatch")
    return stats.model_dump(exclude={"project_id", "sandbox_id"}, exclude_none=True)
