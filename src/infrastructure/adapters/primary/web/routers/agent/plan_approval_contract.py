"""Structural request identity and permission bounds for versioned plan approval."""

from typing import Any

from fastapi import HTTPException

from src.infrastructure.i18n import gettext as _

# These are the declared permission profiles, ordered by their allowed effects.
# A workspace ceiling never enlarges the explicit permission requested for a run.
_ALLOWED_REQUEST_PROFILES = {
    "read_only": frozenset({"read_only"}),
    "workspace_write": frozenset({"read_only", "workspace_write"}),
    "full_access": frozenset({"read_only", "workspace_write", "full_access"}),
}


def require_requested_permission_profile(requested: str, policy_ceiling: str) -> str:
    if requested not in _ALLOWED_REQUEST_PROFILES.get(policy_ceiling, frozenset()):
        raise HTTPException(
            status_code=403,
            detail=_("Requested run permissions exceed the workspace policy"),
        )
    return requested


def approval_request_identity(
    request_fields: dict[str, Any], *, tenant_id: str, user_id: str
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "request": request_fields,
    }


def require_matching_approval_request(
    stored_identity: object, expected_identity: dict[str, Any], *, run_id: str
) -> None:
    if not isinstance(stored_identity, dict):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PLAN_APPROVAL_RECEIPT_UNVERIFIABLE",
                "message": _("Original approval request is unavailable; inspect the existing run"),
                "run_id": run_id,
            },
        )
    if stored_identity != expected_identity:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PLAN_APPROVAL_IDEMPOTENCY_CONFLICT",
                "message": _("Plan approval idempotency conflict"),
                "run_id": run_id,
            },
        )
