"""Consume durably admitted scoped reservations at an authenticated Agent boundary."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

from .boundary import (
    OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2,
    # Share the boundary's context ownership without exposing raw lease entry publicly.
    _pin_agent_turn_on_generation_v2,  # pyright: ignore[reportPrivateUsage]
    _pin_reserved_generation_v2,  # pyright: ignore[reportPrivateUsage]
)
from .runtime import OperationContextV2, RuntimeV2Error
from .scope import validate_scope_v2
from .scoped_runtime_registry import ScopedRuntimeReservationV2


@asynccontextmanager
async def pin_scoped_agent_turn_operation_v2(
    reservation: ScopedRuntimeReservationV2,
    *,
    operation_id: str,
    tenant_id: str,
    project_id: str,
    session_id: str,
    services: Mapping[str, object] | None = None,
) -> AsyncIterator[OperationContextV2]:
    """Consume one coordinator reservation; caller supplies authenticated scope identity.

    This boundary performs no new current-generation acquisition. It never inherits
    a surrounding HTTP operation, which may belong to a different authority.
    """
    reservation.claim()
    try:
        scope = validate_scope_v2(
            ScopeV2(
                kind=ScopeKindV2.SESSION,
                tenant_id=tenant_id,
                project_id=project_id,
                session_id=session_id,
            )
        )
        if reservation.scope != scope:
            raise RuntimeV2Error(
                "scope_reservation_mismatch", "admitted reservation differs from operation scope"
            )
        generation = reservation.lease.generation
        distribution = reservation.host.distribution_for_generation(generation).to_payload()
        if distribution.get("descriptor") != generation.descriptor.to_payload():
            raise RuntimeV2Error(
                "generation_descriptor_mismatch", "admitted distribution differs from generation"
            )
        resolved_services = dict(services or {})
        if OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2 in resolved_services:
            raise RuntimeV2Error(
                "scope_distribution_override", "scoped distribution is owned by its admission"
            )
        async with (
            _pin_reserved_generation_v2(reservation.host, reservation.lease),
            _pin_agent_turn_on_generation_v2(
                generation,
                operation_id=operation_id,
                scope=scope,
                services=resolved_services,
                parent=None,
            ) as operation,
        ):
            yield operation
    finally:
        await reservation.lease.release()
