"""Scope host identity and lease ownership through actual operation boundaries."""

import asyncio

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2,
    _distribution_payload_for_generation_v2,
    current_generation_v2,
    current_operation_context_v2,
    fork_current_agent_operation_v2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.scoped_boundary import pin_scoped_agent_turn_operation_v2
from src.tests.unit.infrastructure.plugins.v2.test_scoped_runtime_registry import (
    _SERVICE,
    _profile,
    _publish,
    _registry,
    _scope,
)

pytestmark = pytest.mark.unit


def _enter(reservation, **kwargs):
    return pin_scoped_agent_turn_operation_v2(
        reservation,
        operation_id="scoped-turn",
        tenant_id="a",
        project_id="p",
        session_id="s",
        **kwargs,
    )


async def test_scoped_boundary_restores_outer_root_and_fork_survives_recreation():
    scope = _scope()
    root_scope = ScopeV2(kind=ScopeKindV2.ROOT)
    disposed = []

    def apply(context, _config):
        value = object()
        context.provide(_SERVICE, value)
        return lambda: disposed.append(value)

    registry = _registry(_profile(scope), apply)
    try:
        await _publish(registry, root_scope)
        await _publish(registry, scope)
        root = await registry.acquire_bound(root_scope)
        reservation = await registry.acquire_bound(scope)
        generation = reservation.lease.generation
        value = generation.resolve(_SERVICE, scope)
        async with pin_generation_v2(root.host) as outer:
            async with _enter(reservation) as operation:
                assert current_generation_v2() is generation
                assert current_operation_context_v2() is operation
                assert operation.require(OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2) == (
                    reservation.host.distribution_for_generation(generation).to_payload()
                )
                fork = await fork_current_agent_operation_v2()
                await registry.close_scope(scope)
                await _publish(registry, scope)
                assert value not in disposed
            assert current_generation_v2() is outer
        await root.lease.release()
        assert value not in disposed
        async with fork.admit(operation_id="child", metadata={}) as child:
            assert child.generation is generation
            assert child.generation.resolve(_SERVICE, scope) is value
            assert child.require(OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2)["descriptor"] == (
                generation.descriptor.to_payload()
            )
        assert disposed.count(value) == 1
        with pytest.raises(RuntimeV2Error):
            current_generation_v2()
    finally:
        await registry.close()


@pytest.mark.parametrize("invalid", ["scope", "distribution"])
async def test_rejected_admission_releases_owned_lease(invalid):
    scope = _scope() if invalid == "distribution" else _scope("b")
    disposed = []

    def apply(context, _config):
        context.provide(_SERVICE, object())
        return lambda: disposed.append(True)

    registry = _registry(_profile(scope), apply)
    try:
        await _publish(registry, scope)
        reservation = await registry.acquire_bound(scope)
        await registry.close_scope(scope)
        services = (
            {OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2: {}} if invalid == "distribution" else {}
        )
        with pytest.raises(RuntimeV2Error) as error:
            async with _enter(reservation, services=services):
                pytest.fail("invalid reservation was admitted")
        assert error.value.code == (
            "scope_distribution_override"
            if invalid == "distribution"
            else "scope_reservation_mismatch"
        )
        assert disposed == [True]
    finally:
        await registry.close()


async def test_reservation_cannot_be_entered_twice_and_foreign_parent_is_rejected():
    scope = _scope()
    registry = _registry(_profile(scope), lambda context, _: context.provide(_SERVICE, 7))
    try:
        await _publish(registry, scope)
        reservation = await registry.acquire_bound(scope)
        async with _enter(reservation) as operation:
            with pytest.raises(RuntimeV2Error, match="consum"):
                async with _enter(reservation):
                    pytest.fail("reservation entered twice")
            assert current_operation_context_v2() is operation
            await _publish(registry, scope, 2)
            other = await registry.acquire_bound(scope)
            try:
                with pytest.raises(RuntimeV2Error) as error:
                    _distribution_payload_for_generation_v2(
                        other.lease.generation, parent=operation
                    )
                assert error.value.code == "generation_descriptor_mismatch"
            finally:
                await other.lease.release()
    finally:
        await registry.close()


async def test_cancelled_operation_releases_reservation_and_restores_context():
    scope = _scope()
    disposed = []

    def apply(context, _config):
        context.provide(_SERVICE, 7)
        return lambda: disposed.append(True)

    registry = _registry(_profile(scope), apply)
    try:
        await _publish(registry, scope)
        reservation = await registry.acquire_bound(scope)
        await registry.close_scope(scope)
        with pytest.raises(asyncio.CancelledError):
            async with _enter(reservation):
                raise asyncio.CancelledError
        assert disposed == [True]
        with pytest.raises(RuntimeV2Error):
            current_generation_v2()
        with pytest.raises(RuntimeV2Error):
            current_operation_context_v2()
    finally:
        await registry.close()
