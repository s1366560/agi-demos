"""Operation-owned synchronous capture permission; no background scheduler activation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.domain.model.plugins.generated_v2 import ScopeKindV2

from .runtime import OperationContextV2, RuntimeV2Error

if TYPE_CHECKING:
    from .runtime_host import PlatformPluginRuntimeHostV2

_CAPTURE_SERVICE = "service:operation.skill-evolution-capture"


@dataclass(frozen=True)
class _CaptureAdmission:
    operation: OperationContextV2
    consumer: object


def admit_worker_skill_capture_v2(
    operation: OperationContextV2, host: PlatformPluginRuntimeHostV2
) -> None:
    from .skill_evolution_runtime import (
        SKILL_EVOLUTION_RUNTIME_MODULE_V2,
        SKILL_EVOLUTION_RUNTIME_SERVICE_V2,
    )

    # Only the successful data-plane admission path may install this permission.
    distribution = host.distribution_for_generation(operation.generation)
    if distribution.descriptor != operation.descriptor:
        raise RuntimeV2Error(
            "skill_capture_admission_mismatch", "capture generation was not admitted"
        )
    if operation.context.scope.kind is not ScopeKindV2.SESSION:
        return
    if not any(
        e.enabled and e.module_ref == SKILL_EVOLUTION_RUNTIME_MODULE_V2
        for e in operation.generation.snapshot.entries
    ):
        return
    consumer = operation.require(SKILL_EVOLUTION_RUNTIME_SERVICE_V2)
    operation.provide(
        _CAPTURE_SERVICE, _CaptureAdmission(operation, consumer), label="worker-skill-capture"
    )


def current_worker_capture_operation_v2() -> OperationContextV2 | None:
    from .boundary import current_operation_context_v2

    try:
        operation = current_operation_context_v2()
        admission = operation.require(_CAPTURE_SERVICE)
    except RuntimeV2Error as error:
        if error.code in {"operation_context_not_pinned", "missing_service"}:
            return None
        raise
    if not isinstance(admission, _CaptureAdmission) or admission.operation is not operation:
        raise RuntimeV2Error("skill_capture_admission_mismatch", "invalid capture operation owner")
    return operation


def require_worker_skill_capture_v2(consumer: object, payload: Mapping[str, object]) -> None:
    operation = current_worker_capture_operation_v2()
    if operation is None:
        raise RuntimeV2Error(
            "skill_evolution_runtime_unavailable", "Skill Evolution generation is not admitted"
        )
    admission = operation.require(_CAPTURE_SERVICE)
    if not isinstance(admission, _CaptureAdmission) or admission.consumer is not consumer:
        raise RuntimeV2Error(
            "skill_capture_admission_mismatch", "capture belongs to another generation"
        )
    scope = operation.context.scope
    for field, expected in (
        ("tenant_id", scope.tenant_id),
        ("project_id", scope.project_id),
        ("conversation_id", scope.session_id),
    ):
        if not expected or payload.get(field) != expected:
            raise RuntimeV2Error(
                "skill_capture_scope_mismatch", "capture differs from admitted session"
            )
