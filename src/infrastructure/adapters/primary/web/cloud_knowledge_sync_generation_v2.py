"""HTTP-only generation preconditions for observed cloud synchronization requests."""

from __future__ import annotations

import json
from typing import cast

from fastapi import HTTPException, Request

from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.boundary import current_generation_descriptor_v2

KNOWLEDGE_SYNC_GENERATION_HEADER = "X-Memstack-Knowledge-Sync-Generation"
KNOWLEDGE_SYNC_GENERATION_CONTRACT_VERSION = "1.0.0"
MAX_GENERATION_HEADER_BYTES = 2048


def cloud_knowledge_sync_generation_payload_v2() -> dict[str, object]:
    return {
        "contract_version": KNOWLEDGE_SYNC_GENERATION_CONTRACT_VERSION,
        "descriptor": current_generation_descriptor_v2().to_payload(),
    }


def observe_cloud_knowledge_sync_generation_v2(request: Request) -> PluginGenerationDescriptorV2:
    return _check_generation(request, required=False)


def require_cloud_knowledge_sync_generation_v2(request: Request) -> PluginGenerationDescriptorV2:
    return _check_generation(request, required=True)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("generation condition contains duplicate JSON fields")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"generation condition contains non-JSON constant {value}")


def _parse_generation(value: str) -> PluginGenerationDescriptorV2:
    # ASGI header values are decoded as Latin-1, so this is also the wire-byte bound.
    if len(value) > MAX_GENERATION_HEADER_BYTES:
        raise ValueError("generation condition exceeds its header bound")
    payload: object = json.loads(
        value, object_pairs_hook=_unique_object, parse_constant=_reject_constant
    )
    if not isinstance(payload, dict):
        raise ValueError("generation condition envelope must be an object")
    envelope = cast("dict[str, object]", payload)
    if set(envelope) != {"contract_version", "descriptor"}:
        raise ValueError("generation condition has invalid envelope fields")
    if envelope["contract_version"] != KNOWLEDGE_SYNC_GENERATION_CONTRACT_VERSION:
        raise ValueError("generation condition has an unsupported contract version")
    descriptor = envelope["descriptor"]
    if not isinstance(descriptor, dict):
        raise ValueError("generation condition descriptor must be an object")
    parsed = PluginGenerationDescriptorV2.from_payload(cast("dict[str, object]", descriptor))
    if parsed.profile_id.strip() != parsed.profile_id:
        raise ValueError("generation condition profile identity must be canonical")
    return parsed


def _check_generation(request: Request, *, required: bool) -> PluginGenerationDescriptorV2:
    current = current_generation_descriptor_v2()
    values = request.headers.getlist(KNOWLEDGE_SYNC_GENERATION_HEADER)
    if not values:
        if required:
            raise HTTPException(
                status_code=428,
                detail={
                    "code": "knowledge_sync_generation_required",
                    "message": _(
                        "Observe knowledge synchronization generation before this request"
                    ),
                },
            )
        return current
    try:
        if len(values) != 1:
            raise ValueError("generation condition requires exactly one header")
        expected = _parse_generation(values[0])
    except (ValueError, RecursionError) as error:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "knowledge_sync_generation_invalid",
                "message": _("Knowledge synchronization generation condition is invalid"),
            },
        ) from error
    if expected != current:
        raise HTTPException(
            status_code=412,
            detail={
                "code": "knowledge_sync_generation_mismatch",
                "message": _("Knowledge synchronization generation changed; observe it again"),
            },
        )
    return current
